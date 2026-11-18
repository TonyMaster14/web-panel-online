#!/usr/bin/env python3
"""Safe panel-only WPO Happ subscription rescue (test branch).

Patches known async subscription behavior, leaves live Node Agent, Sweden 443,
profiles, users, URLs, keys and other VPN configs untouched. Preserves existing
UI/site template changes. Rollback requires exact installed file checksums.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime,timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import Request,build_opener,ProxyHandler

APP=Path("/opt/tproxy-panel")
DATA=Path("/var/lib/tproxy-panel")
PANEL=APP/"panel.py"
FEED=APP/"wpo_happ_async_feed.py"
STATE=DATA/"wpo-happ-rescue-v1.json"
SERVICE="tproxy-panel.service"
LOCK=Path("/run/wpo-happ-rescue-v1.lock")
REF="6a1173a08268cd0c0b319217ab88422c64c85f2c"
URL=("https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"+REF+
     "/src/wpo_happ_resilient_feed_v1.py")
MAX_BYTES=50000


def run(*cmd,timeout=25):
    return subprocess.run(cmd,check=False,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True,timeout=timeout,
                          stdin=subprocess.DEVNULL)


def require(*cmd,timeout=25):
    result=run(*cmd,timeout=timeout)
    if result.returncode:
        raise RuntimeError("Команда "+cmd[0]+" не выполнена: "+(result.stderr or result.stdout)[-220:])
    return result


def safe_file(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Неизвестный/отсутствующий файл: "+str(path))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path,raw,old=None,mode=0o600):
    fd,tmp=tempfile.mkstemp(prefix=".wpo-happ-rescue-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        if old:
            os.chown(tmp,old.st_uid,old.st_gid)
            os.chmod(tmp,stat.S_IMODE(old.st_mode))
        else:
            os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def load_patch():
    opener=build_opener(ProxyHandler({}))
    with opener.open(Request(URL,headers={"User-Agent":"WPO-HAPP-rescue-v1"}),timeout=18) as stream:
        raw=stream.read(MAX_BYTES+1)
    if not 2000<len(raw)<=MAX_BYTES:
        raise RuntimeError("Недопустимый размер патча HAPP")
    src=raw.decode("utf-8")
    ast.parse(src)
    if "WPO_HAPP_RESILIENT_FEED_V1" not in src or "def patch_panel(" not in src or "def patch_feed(" not in src:
        raise RuntimeError("Недопустимый патч HAPP")
    spec=importlib.util.spec_from_loader("wpo_happ_resilient_feed_v1",loader=None)
    module=importlib.util.module_from_spec(spec)
    exec(compile(src,"<happ-rescue>","exec"),module.__dict__)
    return module


def preview():
    if os.geteuid()!=0:
        raise RuntimeError("Нужен root")
    if STATE.exists():
        raise RuntimeError("Изменение уже применялось, используйте --status или --rollback")
    for p in (PANEL,FEED):safe_file(p)
    if run("systemctl","is-active","--quiet",SERVICE,timeout=5).returncode:
        raise RuntimeError("Панель WPO не работает")
    patch=load_patch()
    old_panel=PANEL.read_bytes()
    old_feed=FEED.read_bytes()
    try:
        new_panel=patch.patch_panel(old_panel.decode("utf-8")).encode("utf-8")
        new_feed=patch.patch_feed(old_feed.decode("utf-8")).encode("utf-8")
    except ValueError as exc:
        raise RuntimeError("Несовместимая версия. Ничего не изменено: "+str(exc)[:220]) from exc
    for name,source in (("panel.py",new_panel),("wpo_happ_async_feed.py",new_feed)):
        ast.parse(source.decode("utf-8"),filename=name)
    if new_panel==old_panel or new_feed==old_feed:
        raise RuntimeError("Обновление не изменило необходимые участки кода")
    print("✓ Панель и обработчик подписок совместимы")
    print("✓ Готовые реальные ссылки больше не блокируются задержанной нодой")
    print("✓ При нулевом числе готовых подключений сохраняется честный HTTP 503")
    print("✓ Исправлена проверка числа реальных нод для авто-переключения HAPP")
    print("✓ Повторные попытки Node Agent ускорены, причины ошибок будут видны без секретов")
    print("✓ Пользователи, подписки, серверы Xray, SNI и шаблоны не меняются")
    return (old_panel,old_feed),(new_panel,new_feed)


def health():
    if run("systemctl","is-active","--quiet",SERVICE,timeout=5).returncode:
        return False
    unit=Path("/etc/systemd/system/tproxy-panel.service")
    if not unit.is_file():return True
    m=re.search(r"(?m)^Environment=WEBPROXY_PANEL_PATH=(/panel-[a-z0-9-]{3,64})\s*$",
                unit.read_text(encoding="utf-8"))
    if m is None:return True
    opener=build_opener(ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:8090"+m.group(1)+"/__health",timeout=3) as response:
            return response.status==200
    except OSError:
        return False


def status():
    if not STATE.is_file():
        print("Не установлено")
    else:
        state=json.loads(STATE.read_text(encoding="utf-8"))
        print("Установлено: тестовое исправление HAPP")
        for file in (PANEL,FEED):
            print(file.name,"совпадает с установленным" if
                  sha(file.read_bytes())==state["updated_sha256"][file.name] else
                  "файл изменялся после обновления")
    print("Основная панель:", "в сети" if health() else "требует проверки")


def rollback():
    safe_file(STATE)
    state=json.loads(STATE.read_text(encoding="utf-8"))
    backup=Path(state.get("backup",""))
    if not backup.is_dir() or DATA not in backup.parents:
        raise RuntimeError("Неверная резервная копия")
    for file in (PANEL,FEED):
        old=backup/file.name
        safe_file(old);safe_file(file)
        actual=sha(file.read_bytes())
        if actual not in (state["updated_sha256"][file.name],
                          state["original_sha256"][file.name]):
            raise RuntimeError("Файл "+file.name+" изменён после обновления; откат остановлен")
        if sha(old.read_bytes())!=state["original_sha256"][file.name]:
            raise RuntimeError("Резервная копия "+file.name+" повреждена")
    for file in (PANEL,FEED):
        atomic(file,(backup/file.name).read_bytes(),file.stat())
    require("systemctl","restart",SERVICE,timeout=30)
    for _ in range(20):
        if health():break
        time.sleep(.5)
    else:
        raise RuntimeError("Старый код восстановлен, но служба ещё не отвечает")
    STATE.unlink(missing_ok=True)
    print("✓ Подписочный механизм восстановлен из резервной копии")
    print("✓ Реестры пользователей и работающая Швеция на 443 не изменены")


def apply():
    old,new=preview()
    backup=DATA/("wpo-happ-rescue-v1-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(parents=True,exist_ok=False,mode=0o700)
    old_map=dict(zip((PANEL,FEED),old))
    new_map=dict(zip((PANEL,FEED),new))
    for path in (PANEL,FEED):
        shutil.copy2(path,backup/path.name)
        os.chmod(backup/path.name,0o600)
    state={"backup":str(backup),
           "original_sha256":{p.name:sha(old_map[p]) for p in old_map},
           "updated_sha256":{p.name:sha(new_map[p]) for p in new_map}}
    atomic(STATE,json.dumps(state).encode(),mode=0o600)
    try:
        for path in (PANEL,FEED):
            atomic(path,new_map[path],path.stat())
        require(sys.executable,"-m","py_compile",str(PANEL),str(FEED),timeout=15)
        require("systemctl","restart",SERVICE,timeout=30)
        for _ in range(20):
            if health():break
            time.sleep(.5)
        else:
            raise RuntimeError("Панель не ответила после исправления")
        print("✓ HAPP SUBSCRIPTIONS RESCUE APPLIED")
        print("✓ Старые ключи, токены, ID подписок и список нод сохранены")
        print("✓ Запросы HAPP выдают проверенные подключения, не блокируя все ноды из-за одной")
        print("✓ Резервная копия:",str(backup))
        print("✓ Откат: sudo python3 /root/wpo-happ-rescue-v1.py --rollback")
    except Exception:
        print("! Ошибка установки, выполняю откат.",file=sys.stderr)
        try:rollback()
        except Exception as exc:
            print("! Откат требует проверки: "+type(exc).__name__,file=sys.stderr)
        raise


def main():
    parser=argparse.ArgumentParser()
    g=parser.add_mutually_exclusive_group(required=True)
    for name in ("check","apply","rollback","status"):g.add_argument("--"+name,action="store_true")
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError("Запусти через sudo")
    with open(LOCK,"a+") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        if args.check:preview();print("✓ Только проверка; сервер не изменён")
        elif args.apply:apply()
        elif args.rollback:rollback()
        else:status()


if __name__=="__main__":
    try:main()
    except (OSError,RuntimeError,ValueError,UnicodeError,KeyError,TypeError,
            subprocess.SubprocessError) as exc:
        print("ОШИБКА:",str(exc)[:400],file=sys.stderr)
        raise SystemExit(1)
