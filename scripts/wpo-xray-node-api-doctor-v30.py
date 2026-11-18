#!/usr/bin/env python3
"""WPO V30 doctor for a missing remote Xray JSON viewer.

Run --check on a controller or remote VPN node. On remote nodes --repair
installs the read-only viewer endpoint ONLY if V27 is present and endpoint
is missing. Never changes Xray configs, routing, listeners, user secrets,
service xray process or other federation routes. No tokens/JSON are printed.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
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
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener, urlopen

PIN="4c6723948101934777be99e7e9e656ca0483f47a"
VIEW_URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"+PIN+"/src/wpo_xray_node_view.py"
NODE_DIR=Path("/opt/wpp-node-agent")
PANEL_DIR=Path("/opt/tproxy-panel")
SRC=NODE_DIR/"wpo_node_vpn.py"
VIEW=NODE_DIR/"wpo_xray_node_view.py"
SETTINGS=Path("/etc/wpp-node-agent/config.json")
LOCAL_JSON=Path("/etc/wpp-node-vpn/xray.json")
PANEL_NODES=Path("/var/lib/tproxy-panel/nodes.json")
PANEL_JSON=Path("/etc/web-panel-proxy-xray/config.json")
BACKUPS=Path("/var/backups/web-panel-online")
ENDPOINT="/wpp-api/v1/federation/xray-config"
MARK="# WPO_XRAY_VIEW_REPAIR_V30"

def is_active(unit):
    return subprocess.run(["systemctl","is-active","--quiet",unit],
                          check=False).returncode==0

def status(name,ok,note=""):
    print(("✓ " if ok else "✗ ")+name+(": "+note if note else ""))
    return bool(ok)

def inspect_file(path):
    if path.is_symlink() or not path.is_file():
        return False,"файл отсутствует или является ссылкой"
    try:
        size=path.stat().st_size
        if size < 2 or size > 820000:
            return False,"размер вне диапазона 2–820000 байт"
        value=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value,dict) or not isinstance(value.get("inbounds"),list):
            return False,"нет списка inbounds"
        return True,f'inbounds: {len(value["inbounds"])}; размер: {size} байт'
    except (OSError, UnicodeError, ValueError) as exc:
        return False,"не удалось разобрать JSON: "+type(exc).__name__

def local_rpc(token):
    request=Request("http://127.0.0.1:9089"+ENDPOINT,
        data=b'{"reveal":false}',method="POST",
        headers={"Authorization":"Bearer "+token,
                 "Content-Type":"application/json","Accept":"application/json"})
    try:
        opener=build_opener(ProxyHandler({}))
        with opener.open(request,timeout=8) as response:
            data=response.read(1048577)
            if len(data)>1048576:
                return False,"ответ больше 1 МиБ"
            payload=json.loads(data.decode("utf-8"))
            if not isinstance(payload,dict) or payload.get("ok") is not True:
                return False,"API ответил без ok=true"
            config=payload.get("config")
            if not isinstance(config,dict) or not isinstance(config.get("inbounds"),list):
                return False,"API не вернул серверные inbounds"
            return True,"HTTP 200; inbounds: "+str(len(config["inbounds"]))+"; ключи скрыты"
    except HTTPError as exc:
        try:
            payload=json.loads(exc.read(1024).decode("utf-8"))
            error=str(payload.get("message",""))[:120] if isinstance(payload,dict) else ""
        except (OSError,UnicodeError,ValueError):
            error=""
        return False,"HTTP "+str(exc.code)+(" · "+error if error else "")
    except (OSError,URLError,TimeoutError,UnicodeError,ValueError) as exc:
        return False,"сбой подключения/ответа: "+type(exc).__name__

def load_token():
    raw=json.loads(SETTINGS.read_text(encoding="utf-8"))
    value=raw.get("api_key")
    if not isinstance(value,str) or not value:
        raise RuntimeError("API-токен ноды отсутствует; не печатаем секреты")
    return value

def node_check():
    ok=True
    for unit in ("wpo-node-vpn.service","wpo-node-xray.service","caddy.service"):
        ok=status(unit,is_active(unit)) and ok
    if not SRC.is_file() or SRC.is_symlink():
        return status("Node Agent",False,"нет исходника")
    source=SRC.read_text(encoding="utf-8")
    has_route=ENDPOINT in source and 'if operation == "xray-config":' in source
    ok=status("Обработчик xray-config",has_route,
              "установлен" if has_route else "не установлен на этой ноде") and ok
    has_module=VIEW.is_file() and not VIEW.is_symlink()
    ok=status("Модуль просмотра JSON",has_module) and ok
    valid,info=inspect_file(LOCAL_JSON)
    ok=status("Серверный Xray JSON",valid,info) and ok
    if valid and has_module:
        try:
            sys.path.insert(0,str(NODE_DIR))
            import wpo_xray_node_view as v
            result=v.view(LOCAL_JSON)
            ok=status("Безопасный просмотр из Python",
                      result.get("ok") is True and result.get("secrets_visible") is False,
                      "ключи не выдаются") and ok
        except Exception as exc:
            ok=status("Безопасный просмотр из Python",False,type(exc).__name__) and ok
    if SETTINGS.is_file():
        try:
            token=load_token()
            rpc_ok,info=local_rpc(token)
            ok=status("Локальный авторизованный API POST",rpc_ok,info) and ok
        except (ValueError,OSError,RuntimeError) as exc:
            ok=status("Локальный авторизованный API POST",False,type(exc).__name__) and ok
    else:
        ok=status("Настройки Node Agent",False,"файл отсутствует") and ok
    return ok

def _patch_node(source):
    route='if operation == "xray-config":'
    if ENDPOINT in source and route in source:
        return source,False
    if ENDPOINT in source or route in source:
        raise RuntimeError("Обработчик установлен частично: требуется ручная проверка.")
    if "import wpo_xray_modes\n" not in source or 'if operation == "xray-mode":' not in source:
        raise RuntimeError("Node Agent старше V27; безопасно исправить автоматически нельзя.")
    patches=[
        ("import wpo_xray_modes\n",
         "import wpo_xray_modes\nimport wpo_xray_node_view\n","импорт"),
        ('                             "/wpp-api/v1/federation/xray-mode",',
         '                             "/wpp-api/v1/federation/xray-mode",\n'
         '                             "/wpp-api/v1/federation/xray-config",',"API allowlist"),
        ('            if operation == "xray-mode":',
         '''            if operation == "xray-config":
                try:
                    profile=wpo_reality.read_profile() if REALITY_READY else None
                except (OSError,ValueError):
                    profile=None
                self.respond(wpo_xray_node_view.view(XRAY,
                    reveal=data.get("reveal") is True, reality_profile=profile))
                return
            if operation == "xray-mode":''',"read-only endpoint"),
    ]
    for old,new,label in patches:
        if source.count(old)!=1:
            raise RuntimeError("Node Agent отличается от ожидаемого ("+label+"); изменений нет")
        source=source.replace(old,new,1)
    compile(source,str(SRC),"exec")
    return source+"\n"+MARK+"\n",True

def _download_viewer():
    req=Request(VIEW_URL,headers={"User-Agent":"WPO-Node-JSON-Doctor/30"})
    with urlopen(req,timeout=25) as response:
        data=response.read(120001)
    if not data or len(data)>120000:
        raise RuntimeError("Не удалось получить модуль безопасного просмотра")
    new=data.decode("utf-8")
    compile(new,str(VIEW),"exec")
    if "def view(" not in new or "HIDDEN =" not in new:
        raise RuntimeError("Загружен неожиданный модуль просмотра")
    return new

def repair_node():
    if not SRC.is_file() or SRC.is_symlink():
        raise RuntimeError("Нет файла Node Agent "+str(SRC))
    before=SRC.read_text(encoding="utf-8")
    after,patched=_patch_node(before)
    if VIEW.is_symlink():
        raise RuntimeError("Модуль просмотра — неожиданная ссылка; не перезаписываем")
    if VIEW.exists():
        existing=VIEW.read_text(encoding="utf-8")
        compile(existing,str(VIEW),"exec")
        if "def view(" not in existing or "HIDDEN =" not in existing:
            raise RuntimeError("Существующий модуль просмотра неизвестен; не перезаписываем")
        module=None
    else:
        module=_download_viewer()
    if not patched and module is None:
        print("✓ Обработчик уже присутствует; изменения не требуются.")
        print("Проверяю, почему API ноды может не отдавать JSON:")
        if not node_check():
            raise RuntimeError("API чтения не прошёл диагностику. Смотрите строки с ✗ выше.")
        return
    changes={SRC:after} if patched else {}
    if module is not None:changes[VIEW]=module
    BACKUPS.mkdir(parents=True,exist_ok=True)
    folder=BACKUPS/("xray-api-v30-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if folder.exists():raise RuntimeError("Резервная копия уже существует")
    folder.mkdir(mode=0o700)
    for path in changes:
        if path.exists():
            shutil.copy2(path,folder/path.name)
            os.chmod(folder/path.name,0o600)
    staged={}
    replaced=[]
    try:
        for path,data in changes.items():
            with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,
                                            prefix=".wpo-view-v30-",suffix=".py",delete=False) as stream:
                stream.write(data)
                staged[path]=Path(stream.name)
            if path.exists():
                st=path.stat()
                os.chown(staged[path],st.st_uid,st.st_gid)
                os.chmod(staged[path],stat.S_IMODE(st.st_mode))
            else:
                os.chmod(staged[path],0o644)
        for path,tmp in staged.items():
            os.replace(tmp,path)
            replaced.append(path)
        subprocess.run(["systemctl","restart","wpo-node-vpn.service"],timeout=40,check=True)
        for _ in range(12):
            if is_active("wpo-node-vpn.service"):break
            time.sleep(1)
        if not is_active("wpo-node-vpn.service"):
            raise RuntimeError("Node Agent не запустился")
        if not SETTINGS.is_file():raise RuntimeError("Node Agent API-токен не найден")
        rpc_ok,info=local_rpc(load_token())
        if not rpc_ok:
            raise RuntimeError("После установки API не отвечает: "+info)
        print("✓ JSON API на ноде восстановлен:",info)
        print("✓ Обновлён только Node Agent, Xray и VPN-настройки не трогались")
        print("✓ Резервные копии: ",folder)
    except Exception:
        for path in replaced:
            backup=folder/path.name
            if backup.exists():shutil.copy2(backup,path)
            else:path.unlink(missing_ok=True)
        subprocess.run(["systemctl","restart","wpo-node-vpn.service"],
                       check=False,timeout=40)
        print("! Ошибка проверки, откат Node Agent выполнен")
        raise
    finally:
        for path in staged.values():path.unlink(missing_ok=True)

def controller_check():
    ok=True
    sys.path.insert(0,str(PANEL_DIR))
    try:
        import wpp_nodes as node_api
        nodes=node_api.load_nodes(PANEL_NODES)
    except Exception as exc:
        raise RuntimeError("Реестр нод недоступен: "+type(exc).__name__) from exc
    print("Нод зарегистрировано:",len(nodes))
    for node in nodes:
        name=str(node.get("name") or node.get("country_name") or node.get("url") or "Нода")[:80]
        try:
            result=node_api.request(node,"POST",ENDPOINT,
                                    {"reveal":False},timeout=14)
            cfg=result.get("config")
            passed=isinstance(cfg,dict) and isinstance(cfg.get("inbounds"),list)
            ok=status(name,passed,
                      "Xray JSON читается, inbounds: "+str(len(cfg.get("inbounds",[]))) if passed
                      else "Некорректный ответ JSON") and ok
        except node_api.NodeError:
            # Probe a second time at the HTTP layer to report the actual
            # status code, without printing the bearer or config content.
            import urllib.error
            import urllib.request
            base=node_api.normalize_url(node.get("url"))
            request=Request(base+ENDPOINT,data=b'{"reveal":false}',method="POST",
                            headers={"Authorization":"Bearer "+str(node.get("token","")),
                                     "Content-Type":"application/json","Accept":"application/json"})
            try:
                opener=build_opener(ProxyHandler({}),node_api.NoRedirect())
                with opener.open(request,timeout=10) as response:
                    response.read(1024)
                    info="API ответил, но результат не распознан панелью"
            except HTTPError as exc:
                info="HTTP "+str(exc.code)
            except (URLError,OSError,TimeoutError) as exc:
                info="ошибка HTTPS: "+type(exc).__name__
            ok=status(name,False,info+"; проверьте Node Agent на этом VPS") and ok
    return ok

def main():
    parser=argparse.ArgumentParser(description="WPO remote Xray JSON API doctor")
    x=parser.add_mutually_exclusive_group(required=True)
    x.add_argument("--check",action="store_true")
    x.add_argument("--repair",action="store_true")
    options=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError("Требуется sudo")
    if (SRC.is_file() and is_active("wpo-node-vpn.service")):
        print("Роль: дополнительная нода")
        if options.repair:
            repair_node()
        else:
            if not node_check():sys.exit(2)
    elif (PANEL_DIR/"panel.py").is_file() and is_active("tproxy-panel.service"):
        print("Роль: основная панель")
        if options.repair:
            raise RuntimeError("--repair предназначен только для дополнительной ноды")
        if not controller_check():sys.exit(2)
    else:
        raise RuntimeError("Не найдена запущенная WPO или wpo-node-vpn.service")

if __name__=="__main__":
    try:main()
    except (OSError,RuntimeError,ValueError,subprocess.CalledProcessError) as exc:
        print("ОШИБКА:",exc,file=sys.stderr)
        sys.exit(1)
