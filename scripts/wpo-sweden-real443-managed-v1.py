#!/usr/bin/env python3
"""WPO Sweden REALITY TCP443 managed integration, test branch only.

--check: nonmutating prerequisites and canonical/client-diff validation.
--apply: patch only local Node Agent import, install module, opt-in marker,
  verify authenticated live API & generated HAPP link. Never touch Xray/Caddy/
  Nginx/HAProxy/reality keys, ports or subscription registry.
--rollback: restore the original Node Agent code, leaving working TCP443 intact.

This is a guarded Sweden-only transitional bridge, NOT a blanket WPO update.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import fcntl
import grp
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, ProxyHandler

DOMAIN = "swejeep.goodarielservice.xyz"
AGENTDIR = Path("/opt/wpp-node-agent")
AGENT = AGENTDIR/"wpo_node_vpn.py"
BRIDGE = AGENTDIR/"wpo_real443_bridge.py"
SITE_AGENT=AGENTDIR/"agent.py"
SITE_UNIT="wpp-node-agent.service"
STATUS_MARK="# WPO_REAL443_SITE_STATUS_V1"
CANARY_ROOT = Path("/etc/wpo-reality-remna-test")
MARKER = CANARY_ROOT/"managed.json"
CANARY_JSON = CANARY_ROOT/"xray.json"
SWITCH_STATE = CANARY_ROOT/"switch-443-state.json"
SETTINGS = Path("/etc/wpp-node-vpn/settings.json")
REGISTRY = Path("/etc/wpp-node-vpn/profiles.json")
NODECFG = Path("/etc/wpp-node-agent/config.json")
STATE = Path("/root/wpo-sweden-real443-managed-v1-state.json")
BACKUPS = Path("/var/backups/web-panel-online")
UNIT = "wpo-node-vpn.service"
REAL443 = "wpo-reality-remna-xray-test.service"
ROUTER = "wpo-tls-router.service"
PROD = "wpo-node-xray.service"
HOOK = "# WPO_SWEDEN_REAL443_MANAGED_HOOK_V1"
URL = "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/a0d8a859f9756ece41a05c159aceb2258a3dbe02/src/wpo_real443_bridge.py"
STATUS_URL = "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/d91e4137e0fd640c32b5600ec509e41e4b9d0cdc/src/wpo_real443_status_advertise_v1.py"
LOCK=Path("/run/wpo-sweden-real443-managed.lock")
MAX_BYTES = 65536


def command(*args, timeout=20):
    try:
        return subprocess.run([str(x) for x in args], text=True, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Время выполнения команды истекло: "+str(args[:2])) from exc


def require(*args, timeout=20):
    p=command(*args,timeout=timeout)
    if p.returncode:
        # Avoid echoing configuration text in external process output.
        raise RuntimeError("Ошибка команды %s: %s" % (args[:2],(p.stderr or p.stdout)[-450:]))
    return p


def active(unit):
    return command("systemctl","is-active","--quiet",unit,timeout=5).returncode==0


def plain_file(path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Ожидается обычный файл: "+str(path))


def parse_json(path):
    plain_file(path)
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict):raise RuntimeError("Неверный JSON: "+str(path))
    return v


def download_bridge():
    # Pinned test-branch commit, not floating main; no data or secrets sent.
    opener=build_opener(ProxyHandler({}))
    with opener.open(Request(URL,headers={"User-Agent":"WPO-Sweden-managed-v1"}),timeout=15) as r:
        data=r.read(MAX_BYTES+1)
    if not 1000<len(data)<=MAX_BYTES:
        raise RuntimeError("Некорректный размер загруженного модуля")
    source=data.decode("utf-8")
    ast.parse(source)
    for needed in ("def mirror_config(", "def install(namespace):", "def verify_active(",
                   "def effective_profile(", "def enabled_for("):
        if needed not in source:
            raise RuntimeError("В модуле отсутствует защита: "+needed)
    return source


def download_status_patch():
    opener=build_opener(ProxyHandler({}))
    with opener.open(Request(STATUS_URL,headers={"User-Agent":"WPO-Sweden-managed-status-v1"}),timeout=15) as r:
        data=r.read(MAX_BYTES+1)
    if not 1000<len(data)<=MAX_BYTES:
        raise RuntimeError("Некорректный размер компонента статуса")
    source=data.decode("utf-8")
    ast.parse(source)
    if "def patch(source):" not in source or STATUS_MARK not in source:
        raise RuntimeError("Неподдерживаемый компонент статуса REALITY")
    return source


def load_bridge(source):
    spec=importlib.util.spec_from_loader("wpo_real443_staged",loader=None)
    mod=importlib.util.module_from_spec(spec)
    exec(compile(source,"<wpo_real443_staged>","exec"),mod.__dict__)
    return mod


def canonical_config():
    # Run the already-installed WPO renderer (including V37 patches). The
    # generated JSON contains secrets, so parse privately and never print it.
    snippet=(
      "import json,sys;"
      "sys.path.insert(0,'/opt/wpp-node-agent');"
      "import wpo_node_vpn as n;"
      "state=n.read_json(n.STATE,{'profiles':{}}).get('profiles',{});"
      "settings=n.read_json(n.SETTINGS);"
      "print(json.dumps(n.render_xray(state,settings)))")
    result=command(sys.executable,"-c",snippet,timeout=25)
    if result.returncode:
        raise RuntimeError("Не получилось проверить локальный генератор WPO: "+
                           result.stderr[-350:])
    value=json.loads(result.stdout)
    if not isinstance(value,dict):
        raise RuntimeError("Генератор WPO вернул некорректный ответ")
    return value


def insert_hook(original):
    if HOOK in original or "wpo_real443_bridge.install(globals())" in original:
        raise RuntimeError("Hook управления REALITY уже установлен")
    matches=list(re.finditer(r'''(?m)^if __name__\s*==\s*["']__main__["']\s*:\s*$''', original))
    if len(matches)!=1:
        raise RuntimeError("Неизвестный формат Node Agent entrypoint, отказ от патча")
    inject=("\n"+HOOK+"\nimport wpo_real443_bridge\n"
            "wpo_real443_bridge.install(globals())\n\n")
    new=original[:matches[0].start()]+inject+original[matches[0].start():]
    ast.parse(new)
    return new


def probe_local_api():
    cfg=parse_json(NODECFG)
    token=cfg.get("api_key")
    if not isinstance(token,str) or not token:
        raise RuntimeError("Не найден ключ Node Agent")
    url="http://127.0.0.1:9089/wpp-api/v1/federation/reality"
    opener=build_opener(ProxyHandler({}))
    req=Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    with opener.open(req,timeout=8) as resp:
        data=resp.read(10240)
    parsed=json.loads(data)
    if not isinstance(parsed,dict) or parsed.get("ok") is not True:
        raise RuntimeError("Node Agent не подтвердил REALITY-профиль")
    p=parsed.get("profile") or {}
    if (p.get("sni")!=DOMAIN
        or p.get("managed_reality")!="remna-443-mirror-v1"
        or p.get("managed_readonly") is not True):
        raise RuntimeError("Панель пока не получает реальный SNI шведской ноды")
    return True


def probe_site_status():
    cfg=parse_json(NODECFG)
    token=cfg.get("api_key")
    if not isinstance(token,str) or not token:
        raise RuntimeError("Нет ключа Node Agent")
    opener=build_opener(ProxyHandler({}))
    req=Request("http://127.0.0.1:9088/wpp-api/v1/status",
                headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    with opener.open(req,timeout=8) as response:
        result=json.loads(response.read(65536))
    if (result.get("ok") is not True or
        "reality-direct-443" not in result.get("capabilities",[])):
        raise RuntimeError("Node Agent не подтвердил режим REALITY direct443")
    return True


def probe_link():
    # Smoke-check only: no creation of users and no disclosure of credentials.
    snippet=(
      "import sys,json,urllib.parse;"
      "sys.path.insert(0,'/opt/wpp-node-agent');"
      "import wpo_node_vpn as n;"
      "s=n.read_json(n.SETTINGS);"
      "p=n.read_json(n.STATE,{'profiles':{}}).get('profiles',{});"
      "ids=[x.get('secrets',{}).get('reality') for x in p.values() if isinstance(x,dict)];"
      "id=next((x for x in ids if x),'00000000-0000-4000-8000-000000000001');"
      "v=urllib.parse.urlsplit(n.link('reality',id,'Sweden',s));"
      "q=urllib.parse.parse_qs(v.query);"
      "assert v.hostname==s['domain'] and v.port==443 and q.get('sni')==[s['domain']];"
      "print('ok')")
    result=command(sys.executable,"-c",snippet,timeout=15)
    if result.returncode or result.stdout.strip()!="ok":
        raise RuntimeError("Новая HAPP-ссылка не соответствует рабочему SNI Швеции")
    return True


def write_atomic(path,data,owner=None,mode=0o600):
    fd,tmp=tempfile.mkstemp(prefix=".wpo-managed-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush();os.fsync(out.fileno())
        if owner:
            os.chown(tmp,owner.st_uid,owner.st_gid)
            os.chmod(tmp,owner.st_mode & 0o777)
        else:
            os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def preflight():
    if os.geteuid()!=0:raise RuntimeError("Нужен sudo")
    for p in (AGENT,SITE_AGENT,SETTINGS,REGISTRY,NODECFG,CANARY_JSON,SWITCH_STATE):
        plain_file(p)
    if BRIDGE.exists() or MARKER.exists() or STATE.exists():
        raise RuntimeError("Интеграция уже существует или есть следы предыдущего применения; ничего не перезаписываю")
    if Path("/opt/tproxy-panel/panel.py").exists():
        raise RuntimeError("Нельзя запускать на основной панели — только Швеция")
    if parse_json(SETTINGS).get("domain")!=DOMAIN:
        raise RuntimeError("Эта нода не Швеция, остановлено")
    for u in (UNIT,SITE_UNIT,REAL443,PROD,"caddy.service"):
        if not active(u):
            raise RuntimeError("Рабочая служба неактивна: "+u)
    if active(ROUTER):
        raise RuntimeError("Швеция вернулась на HAProxy, прямой REALITY 443 не работает")
    canary=parse_json(CANARY_JSON)
    if len(canary.get("inbounds",[]))!=1 or canary["inbounds"][0].get("port")!=443:
        raise RuntimeError("Нет действующего тестового Xray на TCP443")
    try:
        with socket.create_connection(("127.0.0.1",443),timeout=3):
            pass
    except OSError as exc:
        raise RuntimeError("REALITY TCP443 не слушает") from exc
    runtime=AGENT.read_text(encoding="utf-8")
    updated=insert_hook(runtime)
    source=download_bridge()
    patchmod=load_bridge(download_status_patch())
    original_site=SITE_AGENT.read_text(encoding="utf-8")
    updated_site=patchmod.patch(original_site)
    bridge=load_bridge(source)
    canonical=canonical_config()
    candidate=bridge.mirror_config(canonical,canary)
    if candidate!=canary:
        raise RuntimeError("Число или состав REALITY-клиентов отличаются от WPO; автоматическую замену работающего Xray не делаю")
    print("✓ Швеция: прямой Xray на 443 активен, HAProxy отключён")
    print("✓ REALITY-ключ, Short ID и ВСЕ клиенты совпадают с WPO")
    print("✓ Новый Node Agent совместим с текущим генератором и прошёл проверку синтаксиса")
    print("✓ Ссылки HAPP будут использовать SNI "+DOMAIN)
    print("✓ Изменения касаются только двух API Node Agent, не Xray/Caddy/Nginx")
    print("✓ Нода будет сообщать панели проверенный режим REALITY direct443")
    return runtime,updated,source,original_site,updated_site


def verify_running():
    for _ in range(18):
        if active(UNIT):
            try:
                probe_local_api();probe_link();probe_site_status()
                return
            except Exception:
                pass
        time.sleep(.5)
    # Don't expose URLs/UUIDs in error output.
    raise RuntimeError("Не подтвердились API Node Agent и корректность HAPP-ссылки после перезапуска")


def rollback():
    if not STATE.exists():
        raise RuntimeError("Нет записанной интеграции для отката. Ничего не меняю.")
    state=parse_json(STATE)
    b=Path(state.get("backup",""))
    if not b.is_dir() or BACKUPS not in b.parents:
        raise RuntimeError("Неверная директория резервной копии")
    old=b/"wpo_node_vpn.py"
    old_site=b/"agent.py"
    plain_file(old)
    plain_file(old_site)
    if not AGENT.is_file() or not SITE_AGENT.is_file():
        raise RuntimeError("Node Agent отсутствует")
    def expected(path,mark,oldfile):
        current=path.read_bytes()
        if mark not in current.decode("utf-8") and current!=oldfile.read_bytes():
            raise RuntimeError("Runtime WPO изменён после интеграции, откат вручную")
    expected(AGENT,HOOK,old)
    expected(SITE_AGENT,STATUS_MARK,old_site)
    original_stat=AGENT.stat()
    site_stat=SITE_AGENT.stat()
    write_atomic(AGENT,old.read_bytes(),original_stat)
    write_atomic(SITE_AGENT,old_site.read_bytes(),site_stat)
    MARKER.unlink(missing_ok=True)
    BRIDGE.unlink(missing_ok=True)
    require("systemctl","restart",UNIT,timeout=25)
    require("systemctl","restart",SITE_UNIT,timeout=25)
    if not active(UNIT) or not active(SITE_UNIT):
        raise RuntimeError("Одна из служб Node Agent не поднялась после восстановления")
    STATE.unlink(missing_ok=True)
    print("✓ Интеграция Node Agent отключена, прежний WPO восстановлен.")
    print("✓ Работающий REALITY на TCP443 не менялся.")


def apply():
    old,updated,module,site_old,site_new=preflight()
    b=BACKUPS/("sweden-real443-managed-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    b.mkdir(mode=0o700,parents=True,exist_ok=False)
    shutil.copy2(AGENT,b/"wpo_node_vpn.py")
    shutil.copy2(SITE_AGENT,b/"agent.py")
    os.chmod(b/"wpo_node_vpn.py",0o600)
    os.chmod(b/"agent.py",0o600)
    state={"backup":str(b),"domain":DOMAIN}
    write_atomic(STATE,json.dumps(state).encode("utf-8"),mode=0o600)
    owner=AGENT.stat()
    site_owner=SITE_AGENT.stat()
    try:
        write_atomic(BRIDGE,module.encode("utf-8"),mode=0o644)
        write_atomic(AGENT,updated.encode("utf-8"),owner)
        write_atomic(SITE_AGENT,site_new.encode("utf-8"),site_owner)
        marker={"mode":"remna-443-mirror-v1","domain":DOMAIN}
        write_atomic(MARKER,json.dumps(marker).encode("utf-8"),mode=0o640)
        os.chown(MARKER,0,grp.getgrnam("xray").gr_gid)
        require("systemctl","restart",UNIT,timeout=25)
        require("systemctl","restart",SITE_UNIT,timeout=25)
        verify_running()
        print("✓ PANEL INTEGRATED: Швеция возвращает рабочий REALITY SNI, Node Agent готов к синхронизации")
        print("✓ В статусе ноды: reality-direct-443, если Xray действительно на 443")
        print("✓ Старые UUID и подписки сохранены; новый Xray 443 НЕ перезапускался")
        print("✓ Резервная копия:",b)
        print("! Для отката ТОЛЬКО интеграции: sudo python3 /root/wpo-sweden-real443-managed-v1.py --rollback")
    except Exception:
        print("! Ошибка интеграции, возвращаю старый Node Agent ...")
        try:rollback()
        except Exception as ex:
            print("! Откат Node Agent требует проверки:",str(ex)[:350],file=sys.stderr)
        raise


def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    for o in ("check","apply","rollback"):
        group.add_argument("--"+o,action="store_true")
    a=p.parse_args()
    if os.geteuid()!=0:raise RuntimeError("Нужен sudo")
    with open(LOCK,"a+") as lf:
        fcntl.flock(lf.fileno(),fcntl.LOCK_EX)
        if a.check:preflight();print("✓ Только проверка. Файлы и службы не менялись.")
        elif a.apply:apply()
        else:rollback()


if __name__=="__main__":
    try:main()
    except (RuntimeError,OSError,ValueError,KeyError,UnicodeError,TimeoutError,
            subprocess.SubprocessError) as exc:
        print("ОШИБКА:",str(exc)[:650],file=sys.stderr)
        raise SystemExit(1)
