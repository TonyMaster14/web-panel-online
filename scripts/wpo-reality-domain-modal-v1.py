#!/usr/bin/env python3
"""WPO REALITY modal: safe, reversible node-domain SNI display.

Adds only tightly validated UI changes to the current locally installed
module, preserving all existing UI translations, CSS and button behavior.
Does NOT modify real node/REALITY settings.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime,timezone
import fcntl
import hashlib
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
MODULE=APP/"wpo_reality_ui.py"
SERVICE="tproxy-panel.service"
DATA=Path("/var/lib/tproxy-panel")
STATE=DATA/"wpo-reality-domain-modal-v1-state.json"
LOCK=Path("/run/wpo-reality-domain-modal-v1.lock")
REF="39997122e191c515b9edcbfd4290d3fba391120b"
URL=("https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"
     +REF+"/src/wpo_reality_domain_ui_transform_v1.py")
MARK="# WPO_REALITY_DOMAIN_MODAL_V1"
MAX_BYTES=200000


def cmd(*args,timeout=20):
    return subprocess.run(list(args),text=True,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,
                          timeout=timeout)


def need(*args,timeout=20):
    r=cmd(*args,timeout=timeout)
    if r.returncode:raise RuntimeError(args[0]+": "+(r.stderr or r.stdout)[-300:])
    return r


def atomic(path,payload,metadata=None,mode=0o600):
    fd,tmp=tempfile.mkstemp(prefix=".wpo-real-modal-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        if metadata is not None:
            os.chown(tmp,metadata.st_uid,metadata.st_gid)
            os.chmod(tmp,stat.S_IMODE(metadata.st_mode))
        else:os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def blob(raw):
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()


def download_transform():
    import importlib.util
    opener=build_opener(ProxyHandler({}))
    with opener.open(Request(URL,headers={"User-Agent":"WPO-reality-domain-modal-v1"}),timeout=15) as response:
        raw=response.read(MAX_BYTES+1)
    if not 3000<len(raw)<MAX_BYTES:
        raise RuntimeError("Неожиданный размер проверяемого патча UI")
    source=raw.decode("utf-8")
    ast.parse(source)
    spec=importlib.util.spec_from_loader("wpo_domain_ui_patcher",loader=None)
    module=importlib.util.module_from_spec(spec)
    exec(compile(source,"<WPO UI patch>","exec"),module.__dict__)
    if not callable(module.patch) or MARK!=module.MARK:
        raise RuntimeError("Неизвестный патч REALITY")
    return module.patch


def check():
    if not MODULE.is_file() or MODULE.is_symlink():
        raise RuntimeError("Модуль REALITY интерфейса не найден")
    if STATE.exists():
        raise RuntimeError("Обновление уже применялось; используй --status или --rollback")
    installed=MODULE.read_bytes()
    try:
        candidate=download_transform()(installed.decode("utf-8")).encode("utf-8")
    except ValueError as e:
        raise RuntimeError("Локальный REALITY UI несовместим: "+str(e)[:210]) from e
    ast.parse(candidate.decode("utf-8"))
    if cmd("systemctl","is-active","--quiet",SERVICE,timeout=5).returncode:
        raise RuntimeError("Основная панель WPO не активна")
    print("✓ Локальная версия REALITY UI совместима с точечным обновлением")
    print("✓ Старые ноды сохраняют свои существующие NVIDIA/Apple/SNI настройки")
    print("✓ Новые managed REALITY ноды показывают доменный SNI только для чтения")
    print("✓ Протоколы, подписки и Xray не меняются")
    return candidate


def health():
    if cmd("systemctl","is-active","--quiet",SERVICE,timeout=5).returncode:
        return False
    p=Path("/etc/systemd/system/tproxy-panel.service")
    if not p.is_file():return False
    m=re.search(r"(?m)^Environment=WEBPROXY_PANEL_PATH=(/panel-[a-z0-9-]{3,64})\s*$",
                p.read_text())
    if not m:return False
    import urllib.request
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:8090"+m.group(1)+"/__health",
                         timeout=3) as response:return response.status==200
    except Exception:return False


def rollback():
    if not STATE.is_file() or STATE.is_symlink():
        raise RuntimeError("Нет установленного обновления")
    data=json.loads(STATE.read_text(encoding="utf-8"))
    backup=Path(data.get("backup",""))
    if not backup.is_file() or DATA not in backup.parents:
        raise RuntimeError("Резервная копия не найдена")
    current=MODULE.read_bytes()
    if blob(current) not in (data.get("updated_blob"),data.get("old_blob")):
        raise RuntimeError("REALITY UI изменён после обновления, автоматический откат запрещён")
    atomic(MODULE,backup.read_bytes(),MODULE.stat())
    need("systemctl","restart",SERVICE,timeout=25)
    for _ in range(16):
        if health():break
        time.sleep(.5)
    else:raise RuntimeError("Панель не подтвердила восстановление")
    STATE.unlink(missing_ok=True)
    print("✓ Прежний интерфейс REALITY восстановлен. Xray и ноды не менялись.")


def apply():
    data=check()
    folder=DATA/("wpo-reality-domain-modal-v1-"+
                 datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    folder.mkdir(parents=True,mode=0o700,exist_ok=False)
    backup=folder/"wpo_reality_ui.py"
    shutil.copy2(MODULE,backup)
    os.chmod(backup,0o600)
    state={"backup":str(backup),"updated_blob":blob(data),
           "old_blob":blob(MODULE.read_bytes())}
    atomic(STATE,json.dumps(state).encode(),mode=0o600)
    try:
        atomic(MODULE,data,MODULE.stat())
        need(sys.executable,"-m","py_compile",str(MODULE),timeout=15)
        need("systemctl","restart",SERVICE,timeout=25)
        for _ in range(16):
            if health():break
            time.sleep(.5)
        else:raise RuntimeError("Панель не ответила после изменения REALITY UI")
        print("✓ REALITY UI READY: нодный SNI отображается по фактическому режиму")
        print("✓ Резервная копия:",str(backup))
        print("✓ Откат: sudo python3 /root/wpo-reality-domain-modal-v1.py --rollback")
    except Exception:
        print("! Ошибка обновления, возвращаю прежний UI",file=sys.stderr)
        try:rollback()
        except Exception as e:print("! Откат требует проверки:",str(e)[:250],file=sys.stderr)
        raise


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_mutually_exclusive_group(required=True)
    for a in ("check","apply","rollback","status"):
        sub.add_argument("--"+a,action="store_true")
    a=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError("Нужен sudo")
    with open(LOCK,"a+") as f:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        if a.check:check();print("✓ Только проверка, файлы не изменены")
        elif a.apply:apply()
        elif a.rollback:rollback()
        else:
            print("UI обновлён" if STATE.exists() else "Обновление не применено")
            print("Панель отвечает" if health() else "Панель не отвечает")


if __name__=="__main__":
    try:main()
    except (OSError,ValueError,RuntimeError,KeyError,UnicodeError,
            subprocess.SubprocessError) as exc:
        print("ОШИБКА:",str(exc)[:700],file=sys.stderr)
        raise SystemExit(1)
