#!/usr/bin/env python3
"""WPO V29: accurate 7-rule routing status + Xray inspector inside node configurator.

This is a read-only display fix. It does NOT touch live Xray, TLS,
HAProxy, Hysteria listeners, VPN user state, subscription data or routing.

On controller: fixes V28 NameError (XRAY_CONFIG -> XRAY_RUNTIME_CONFIG),
provides actionable remote node errors and updates the Nodes UI.
On remote agents: supplies authenticated V28 read-only endpoint if it is
missing, so a controller never silently claims a remote config is available.
Run on all test remote nodes first, then on the test controller.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

PIN="072c71311e1a6dc8eb4819bd70d139629c9e1970"
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"+PIN+"/src/"
BACKUPS=Path("/var/backups/web-panel-online")
MARK="# WPO_XRAY_CONFIG_IN_DIALOG_V29"

def once(text,old,new,label):
    count=text.count(old)
    if count!=1:
        raise RuntimeError("V29: "+label+": ожидалось 1 вхождение, найдено "+str(count)+". Файлы не изменены.")
    return text.replace(old,new,1)

def patch_panel(source):
    if MARK in source:
        return source
    if 'if path==PANEL_PATH+"/node-xray-view":' not in source:
        raise RuntimeError("V29 требует установленный V28 на основном сервере.")
    # V28 accidentally referenced the manager-only variable XRAY_CONFIG.
    # In panel.py the real constant is XRAY_RUNTIME_CONFIG.
    source=once(source,
        'wpo_xray_node_view.view(XRAY_CONFIG,reveal=reveal,',
        'wpo_xray_node_view.view(XRAY_RUNTIME_CONFIG,reveal=reveal,',
        'исправление пути основной ноды')
    old='''            except (ValueError,OSError,json.JSONDecodeError,node_api.NodeError) as exc:
                self.send_json({"ok":False,"message":"Не удалось прочитать Xray JSON выбранной ноды."},503)'''
    new='''            except node_api.NodeError:
                self.send_json({"ok":False,"message":
                    "Нода не передала Xray JSON. Установите V29 на VPS этой ноды "
                    "и проверьте wpo-node-vpn.service и HTTPS API."},503)
            except (ValueError,OSError,json.JSONDecodeError) as exc:
                print("WPO V29: Xray JSON read failed:",type(exc).__name__,
                      file=sys.stderr,flush=True)
                self.send_json({"ok":False,"message":
                    "Не удалось прочитать рабочий Xray JSON. Проверьте файл "
                    "конфигурации и службы Xray на выбранном VPS."},503)'''
    source=once(source,old,new,'сообщения об ошибке JSON')
    return source+"\n"+MARK+"\n"

def patch_node(source):
    if MARK in source:
        return source
    if "import wpo_xray_modes" not in source:
        raise RuntimeError("V29 требует установленный V27 на ноде.")
    if ("/wpp-api/v1/federation/xray-config" in source
            and "import wpo_xray_node_view" in source):
        return source  # V28 endpoint is already present and authorized.
    source=once(source,
        "import wpo_xray_modes\n",
        "import wpo_xray_modes\nimport wpo_xray_node_view\n",
        'импорт read-only JSON')
    source=once(source,
        '                             "/wpp-api/v1/federation/xray-mode",',
        '                             "/wpp-api/v1/federation/xray-mode",\n'
        '                             "/wpp-api/v1/federation/xray-config",',
        'доступ по API после Bearer-проверки')
    source=once(source,
        '            if operation == "xray-mode":',
        '''            if operation == "xray-config":
                try:
                    profile=wpo_reality.read_profile() if REALITY_READY else None
                except (OSError,ValueError):
                    profile=None
                self.respond(wpo_xray_node_view.view(XRAY,
                    reveal=data.get("reveal") is True, reality_profile=profile))
                return
            if operation == "xray-mode":''',
        'read-only RPC Xray')
    return source+"\n"+MARK+"\n"

def active(unit):
    return subprocess.run(["systemctl","is-active","--quiet",unit],
                          check=False).returncode==0

def fetch_module(name):
    url=BASE+name
    req=Request(url,headers={"User-Agent":"WPO-V29"})
    with urlopen(req,timeout=30) as resp:
        content=resp.read(220001)
    if not content or len(content)>220000:
        raise RuntimeError("Не удалось безопасно получить модуль "+name)
    result=content.decode("utf-8")
    compile(result,name,"exec")
    return result

def validate_live_json(config_path):
    path=Path(config_path)
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Рабочий JSON Xray не найден: "+str(path))
    if path.stat().st_size>820000:
        raise RuntimeError("Рабочий JSON Xray превышает ограничение чтения")
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError,ValueError,OSError) as exc:
        raise RuntimeError("Xray JSON не читается: "+str(path)) from exc
    if not isinstance(data,dict) or not isinstance(data.get("inbounds"),list):
        raise RuntimeError("У Xray JSON нет списка inbound: "+str(path))

def main():
    parser=argparse.ArgumentParser(description="WPO V29 node Xray UI and read-only JSON repair")
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check",action="store_true")
    actions.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError("Требуется sudo")
    panel_dir=Path("/opt/tproxy-panel")
    node_dir=Path("/opt/wpp-node-agent")
    panel=(panel_dir/"panel.py").is_file() and active("tproxy-panel.service")
    agent=(node_dir/"wpo_node_vpn.py").is_file() and active("wpo-node-vpn.service")
    if panel and agent:
        raise RuntimeError("На VPS одновременно определены панель и Node Agent")
    if panel:
        patches={panel_dir/"panel.py":patch_panel}
        modules={panel_dir/"wpo_xray_node_view_ui.py":"wpo_xray_node_view_ui.py"}
        required=(panel_dir/"wpo_xray_node_view.py",panel_dir/"wpo_xray_modes_ui.py")
        for path in required:
            if not path.is_file():
                raise RuntimeError("На основной панели сначала установите V28: "+str(path))
        validate_live_json("/etc/web-panel-proxy-xray/config.json")
        units=("tproxy-panel.service",)
        role="основная панель"
    elif agent:
        patches={node_dir/"wpo_node_vpn.py":patch_node}
        modules={node_dir/"wpo_xray_node_view.py":"wpo_xray_node_view.py"}
        validate_live_json("/etc/wpp-node-vpn/xray.json")
        units=("wpo-node-vpn.service",)
        role="дополнительная нода"
    else:
        raise RuntimeError("Не найдена запущенная WPO или нода с V27")
    originals={}
    updated={}
    for path,patch in patches.items():
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Некорректный исходный файл: "+str(path))
        original=path.read_text(encoding="utf-8")
        new=patch(original)
        compile(new,str(path),"exec")
        originals[path]=original
        if new!=original:
            updated[path]=new
    for path,name in modules.items():
        if path.is_symlink():
            raise RuntimeError("Неожиданная ссылка модуля: "+str(path))
        new=fetch_module(name)
        if path.exists():
            if not path.is_file():
                raise RuntimeError("Некорректный путь модуля: "+str(path))
            old=path.read_text(encoding="utf-8")
            # Avoid overwriting unrecognized customized modules.
            if panel and "wpo-xray-view-v28-style" not in old:
                raise RuntimeError("Неизвестный UI-модуль ноды: "+str(path))
            if not panel and 'def view(' not in old:
                raise RuntimeError("Неизвестный Xray просмотрщик: "+str(path))
            originals[path]=old
            if old!=new:
                updated[path]=new
        else:
            originals[path]=None
            updated[path]=new
    print("✓ Цель:",role)
    print("✓ Реальный Xray JSON найден и проверен")
    if not updated:
        print("✓ V29 уже установлен, ничего не изменено")
        return
    print("✓ Файлы для установки:",", ".join(path.name for path in updated))
    if args.check:
        print("✓ Предварительная проверка завершена; изменений нет")
        return
    BACKUPS.mkdir(parents=True,exist_ok=True)
    folder=BACKUPS/("xray-v29-"+("panel-" if panel else "node-")+
                     datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if folder.exists():
        raise RuntimeError("Папка резервной копии уже есть")
    folder.mkdir(mode=0o700)
    for path,old in originals.items():
        if path in updated and old is not None:
            shutil.copy2(path,folder/path.name)
            os.chmod(folder/path.name,0o600)
    print("✓ Резервная копия:",folder)
    staged={}
    replaced=[]
    try:
        for path,content in updated.items():
            with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,
                    prefix=".wpo-v29-",suffix=".py",delete=False) as stream:
                stream.write(content)
                staged[path]=Path(stream.name)
            if originals[path] is not None:
                previous=path.stat()
                os.chown(staged[path],previous.st_uid,previous.st_gid)
                os.chmod(staged[path],stat.S_IMODE(previous.st_mode))
            else:
                os.chmod(staged[path],0o644)
        for path,tmp in staged.items():
            os.replace(tmp,path)
            replaced.append(path)
        for unit in units:
            subprocess.run(["systemctl","restart",unit],check=True,timeout=45)
        for attempt in range(15):
            if all(active(unit) for unit in units):
                print("✓ V29 установлен, служба работает")
                print("✓ Серверные конфиги, порты, ключи, маршруты и подписки не изменялись")
                return
            time.sleep(1)
        raise RuntimeError("Служба WPO не восстановилась после обновления")
    except Exception:
        for path in replaced:
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                shutil.copy2(folder/path.name,path)
        for unit in units:
            subprocess.run(["systemctl","restart",unit],check=False)
        print("! Откат V29 выполнен: исходные файлы возвращены")
        raise
    finally:
        for tmp in staged.values():
            tmp.unlink(missing_ok=True)

if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as exc:
        print("ОШИБКА:",exc,file=sys.stderr)
        sys.exit(1)
