#!/usr/bin/env python3
"""Add the already-existing WPO node website mechanics to compact node cards.

This installer touches ONLY panel-side Python UI and template library modules.
It never changes working Sweden, Xray, the remote Agent, site files or TLS.
Pinned additions are original self-contained websites, not arbitrary GitHub code.

sudo python3 wpo-node-site-panel-v1.py --check
sudo python3 wpo-node-site-panel-v1.py --apply
sudo python3 wpo-node-site-panel-v1.py --rollback
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
import socket
import stat
import sys
import subprocess
import tempfile
import time
from urllib.request import Request,build_opener,ProxyHandler

APP=Path("/opt/tproxy-panel")
DATA=Path("/var/lib/tproxy-panel")
UI=APP/"wpp_ui.py"
LIB=APP/"wpp_presets.py"
UI_ADD=APP/"wpo_node_site_view_v1.py"
LIB_ADD=APP/"wpo_node_site_pack_v1.py"
STATE=DATA/"wpo-node-site-panel-v1-state.json"
LOCK=Path("/run/wpo-node-site-panel-v1.lock")
SERVICE="tproxy-panel.service"
MARK_UI="# WPO_NODE_SITE_VIEW_V1_ACTIVE"
MARK_LIB="# WPO_NODE_SITE_PACK_V1_ACTIVE"
REF="acbef6bdcc67998209e7dad21621484599b576ba"
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"+REF+"/src/"
MAX_BYTES=100000
NAMES=("wpo_node_site_view_v1.py","wpo_node_site_pack_v1.py")


def run(*args,timeout=25):
    return subprocess.run(list(args),capture_output=True,text=True,timeout=timeout,
                          stdin=subprocess.DEVNULL)


def require(*args,timeout=25):
    p=run(*args,timeout=timeout)
    if p.returncode:
        raise RuntimeError("Ошибка команды "+args[0]+": "+(p.stderr or p.stdout)[-400:])
    return p


def plain(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Отсутствует обычный файл WPO: "+str(path))


def fetch(name):
    if name not in NAMES:
        raise ValueError("Неизвестный компонент сайта")
    opener=build_opener(ProxyHandler({}))
    req=Request(BASE+name,headers={"User-Agent":"WPO-site-panel-v1"})
    with opener.open(req,timeout=18) as stream:
        raw=stream.read(MAX_BYTES+1)
    if not 1000<len(raw)<=MAX_BYTES:
        raise RuntimeError("Размер компонента сайта неверен")
    source=raw.decode("utf-8")
    ast.parse(source)
    return source


def patch_ui(original):
    if MARK_UI in original or "wpo_node_site_view_v1.install(globals())" in original:
        raise RuntimeError("Интерфейс нод уже обновлён")
    required=("def nodes_ui(", "wpo-node-domain", "wpo-node-template")
    if not all(x in original for x in required):
        raise RuntimeError("Несовместимая версия карточек нод. Отказ от изменений")
    patch="""
# WPO_NODE_SITE_VIEW_V1_ACTIVE: all existing card sizes and domain hyperlinks remain.
import wpo_node_site_view_v1
wpo_node_site_view_v1.install(globals())
# Update the UI cache-busting digest for the additive CSS.
ASSET_REV=hashlib.sha256((CSS+COMMON_JS+globals().get("WPO_SELECT_POPOVER_V2_JS","")).encode("utf-8")).hexdigest()[:12]
"""
    candidate=original.rstrip()+"\n"+patch
    ast.parse(candidate)
    return candidate


def patch_library(original):
    if MARK_LIB in original or "wpo_node_site_pack_v1.install(globals())" in original:
        raise RuntimeError("Библиотека шаблонов уже дополнена")
    if "def presets(" not in original:
        raise RuntimeError("Неизвестная библиотека сайтов")
    candidate=original.rstrip()+"""
# WPO_NODE_SITE_PACK_V1_ACTIVE: four offline-only original landing pages.
import wpo_node_site_pack_v1
wpo_node_site_pack_v1.install(globals())
"""
    ast.parse(candidate)
    return candidate


def module(source,name):
    spec=importlib.util.spec_from_loader(name,loader=None)
    obj=importlib.util.module_from_spec(spec)
    exec(compile(source,name,"exec"),obj.__dict__)
    return obj


def preview():
    if os.geteuid()!=0:
        raise RuntimeError("Требуется root")
    for p in (UI,LIB):
        plain(p)
    if UI_ADD.exists() or LIB_ADD.exists() or STATE.exists():
        raise RuntimeError("Найдена предыдущая установка; используй --status или --rollback")
    ui=UI.read_text(encoding="utf-8")
    lib=LIB.read_text(encoding="utf-8")
    new_ui=patch_ui(ui)
    new_lib=patch_library(lib)
    sources={name:fetch(name) for name in NAMES}
    view=module(sources[NAMES[0]],"wpo_node_site_view_preview")
    pack=module(sources[NAMES[1]],"wpo_node_site_pack_preview")
    names=[p["id"] for p in pack.presets()]
    if len(names)!=4 or len(set(names))!=4:
        raise RuntimeError("Библиотека шаблонов повреждена")
    for p in pack.presets():
        if "https://" in p["html"] or "<script" in p["html"]:
            raise RuntimeError("Новый сайт содержит внешние зависимости или JS")
        if len(p["html"].encode("utf-8"))>2100000:
            raise RuntimeError("Шаблон превышает лимит Node Agent")
    if "wpo-site-line-v1" not in view.decorate(
        '<article class="card wpo-node-card"><a class="wpo-node-domain" href="https://node.example.com">'
        'node.example.com</a><p class="wpo-node-template">Шаблон: Кофейня</p>'
        '<button data-node-edit="abcdef1234567890">Edit</button></article>',
        [{"id":"abcdef1234567890","capabilities":["reality-direct-443"]}]):
        raise RuntimeError("Проверка будущей карточки не прошла")
    if not run("systemctl","is-active","--quiet",SERVICE,timeout=5).returncode==0:
        raise RuntimeError("Панель WPO сейчас не запущена")
    print("✓ Панель WPO активна; текущие карточки совместимы")
    print("✓ Домен остаётся кликабельным на прежнем месте")
    print("✓ Шаблон и REALITY используют одну компактную строку в карточке")
    print("✓ Четыре новых сайта без внешних ресурсов и JavaScript")
    print("✓ Автоподбор и ручное изменение существующих шаблонов не меняем")
    return new_ui,new_lib,sources


def atomic(path,data,original=None,mode=0o644):
    fd,tmp=tempfile.mkstemp(prefix=".wpo-site-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        if original:
            os.chown(tmp,original.st_uid,original.st_gid)
            os.chmod(tmp,stat.S_IMODE(original.st_mode))
        else:
            os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def health():
    if run("systemctl","is-active","--quiet",SERVICE,timeout=5).returncode:
        return False
    unit=Path("/etc/systemd/system/tproxy-panel.service")
    if not unit.is_file():
        return False
    m=re.search(r"(?m)^Environment=WEBPROXY_PANEL_PATH=(/panel-[a-z0-9-]{3,64})\s*$",
                unit.read_text())
    if m is None:
        return False
    # Check through loopback only. No admin token or data is sent over the net.
    import urllib.request
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:8090"+m.group(1)+"/__health",timeout=3) as response:
            return response.status==200
    except Exception:
        return False


def restore(allow_missing=False):
    if not STATE.exists():
        if allow_missing:
            return
        raise RuntimeError("Нет установленного дополнения для отката")
    data=json.loads(STATE.read_text())
    path=Path(data.get("backup",""))
    if not path.is_dir() or DATA not in path.parents:
        raise RuntimeError("Неверная директория резервной копии")
    for file in (UI,LIB):
        old=path/file.name
        plain(old)
        expected=MARK_UI if file==UI else MARK_LIB
        present=hashlib.sha256(file.read_bytes()).hexdigest()
        original=data.get("original_sha256",{}).get(file.name)
        if expected not in file.read_text(encoding="utf-8") and present!=original:
            raise RuntimeError("Исходный файл изменён после обновления: "+str(file))
    for file in (UI,LIB):
        old=path/file.name
        atomic(file,old.read_bytes(),file.stat())
    for addon in (UI_ADD,LIB_ADD):
        addon.unlink(missing_ok=True)
    require("systemctl","restart",SERVICE,timeout=25)
    if not health():
        raise RuntimeError("Исходная панель восстановлена, но health ещё не подтвердился")
    STATE.unlink(missing_ok=True)
    print("✓ Старые карточки и библиотека сайтов восстановлены")
    print("✓ Конфигурации нод, Xray, REALITY, Caddy и шаблоны на VPS не менялись")


def apply():
    new_ui,new_lib,sources=preview()
    backup=DATA/("wpo-site-panel-v1-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(parents=True,mode=0o700,exist_ok=False)
    for file in (UI,LIB):
        shutil.copy2(file,backup/file.name)
        os.chmod(backup/file.name,0o600)
    info={"backup":str(backup),"timestamp":datetime.now(timezone.utc).isoformat(),
          "original_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (UI,LIB)}}
    atomic(STATE,json.dumps(info).encode("utf-8"),mode=0o600)
    try:
        atomic(UI_ADD,sources[NAMES[0]].encode("utf-8"))
        atomic(LIB_ADD,sources[NAMES[1]].encode("utf-8"))
        atomic(UI,new_ui.encode("utf-8"),UI.stat())
        atomic(LIB,new_lib.encode("utf-8"),LIB.stat())
        require("python3","-m","py_compile",UI,LIB,UI_ADD,LIB_ADD,timeout=20)
        require("systemctl","restart",SERVICE,timeout=25)
        for _ in range(20):
            if health():
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Панель не ответила после обновления")
        print("✓ PANEL NODE SITE READY")
        print("✓ Четыре новых шаблона доступны в существующем списке сайтов")
        print("✓ Новые ноды будут получать случайный шаблон через существующий автоподбор")
        print("✓ Текущие домены и карточки сохранены")
        print("✓ Резервная копия: "+str(backup))
        print("✓ Откат: sudo python3 /root/wpo-node-site-panel-v1.py --rollback")
    except Exception:
        print("! Проверка панели не прошла. Выполняю откат.",file=sys.stderr)
        try:
            restore()
        except Exception as e:
            print("! Автоматический откат требует проверки: "+str(e)[:300],file=sys.stderr)
        raise


def main():
    p=argparse.ArgumentParser()
    x=p.add_mutually_exclusive_group(required=True)
    for key in ("check","apply","rollback","status"):
        x.add_argument("--"+key,action="store_true")
    opts=p.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError("Требуется sudo")
    with open(LOCK,"a+") as f:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        if opts.check:
            preview()
            print("✓ Только проверка, ничего не изменено")
        elif opts.apply:
            apply()
        elif opts.rollback:
            restore()
        elif opts.status:
            print("Установлено" if STATE.exists() else "Не установлено")
            print("Панель работает" if health() else "Состояние панели требует проверки")


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError,KeyError,UnicodeError,subprocess.SubprocessError) as exc:
        print("ОШИБКА:",str(exc)[:800],file=sys.stderr)
        raise SystemExit(1)
