#!/usr/bin/env python3
"""WPO V28 test patch: per-node routing status and actual read-only Xray JSON.

Install on additional nodes first, then on the test controller. V27 required.
No changes to actual Xray/HAProxy/Caddy config, credentials, ports or routing.
"""
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

PIN="25471b1c3f5f605578539bdf88a4e01cd7c8e088"
ROOT_URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"+PIN+"/src/"
MARK="# WPO_XRAY_NODE_VIEW_V28"
BACKUPS=Path("/var/backups/web-panel-online")

def one(source,old,new,name):
    n=source.count(old)
    if n!=1:
        raise RuntimeError("V28: "+name+": ожидалось 1 вхождение, найдено "+str(n)+". Изменений нет.")
    return source.replace(old,new,1)

def patch_mode_ui(source):
    if MARK in source:return source
    old='    ns[\'nodes_ui\'] = nodes_ui'
    new='''    ns['nodes_ui'] = nodes_ui
    import wpo_xray_node_view_ui
    wpo_xray_node_view_ui.install_ui(ns)'''
    return one(source,old,new,"Xray Node UI wrapper")+"\n"+MARK+"\n"

def patch_editor(source):
    if MARK in source:return source
    # The original advanced panel still shows old XHTTP JSON when REALITY is
    # selected; keep the JSON editor ONLY for true XHTTP. Hysteria and REALITY
    # use the per-node read-only live inspector instead.
    choices=[
      "const supported=new Set(['vless','reality','hysteria']);",
      "const supported=new Set(['vless','hysteria']);",
    ]
    present=[s for s in choices if s in source]
    if len(present)!=1 or source.count(present[0])!=1:
        raise RuntimeError("V28: редактор Xray изменился; не трогаем интерфейс.")
    return one(source,present[0],
               "const supported=new Set(['vless']);",
               "hide non-XHTTP advanced editor")+"\n"+MARK+"\n"

def patch_panel(source):
    if MARK in source:return source
    if 'operation=="xray_mode"' not in source:
        raise RuntimeError("V28 требует установленного V27 на основной панели.")
    anchor='        if path==PANEL_PATH+"/node-action":'
    handler='''        if path==PANEL_PATH+"/node-xray-view":
            try:
                import wpo_xray_node_view
                uid=str(form.get("id",""))
                reveal=form.get("reveal","0")=="1"
                if uid=="local":
                    try:
                        import wpo_reality
                        profile=wpo_reality.read_profile()
                    except (ImportError,OSError,ValueError):
                        profile=None
                    result=wpo_xray_node_view.view(XRAY_CONFIG,reveal=reveal,
                                                    reality_profile=profile)
                else:
                    node=next((n for n in node_api.load_nodes(NODES_FILE)
                               if str(n.get("id"))==uid),None)
                    if node is None or not re.fullmatch(r"[a-f0-9]{16}",uid):
                        self.send_json({"ok":False,"message":"Нода не найдена."},404)
                        return
                    result=node_api.request(node,"POST",
                        node_api.API_PREFIX+"/federation/xray-config",
                        {"reveal":reveal},timeout=25)
                self.send_json(result)
            except (ValueError,OSError,json.JSONDecodeError,node_api.NodeError) as exc:
                self.send_json({"ok":False,"message":"Не удалось прочитать Xray JSON выбранной ноды."},503)
            return

'''
    return one(source,anchor,handler+anchor,"authenticated node JSON endpoint")+"\n"+MARK+"\n"

def patch_vpn(source):
    if MARK in source:return source
    if "wpo_xray_modes" not in source:
        raise RuntimeError("V28 требует установленного V27 на Node Agent.")
    source=one(source,
        "import wpo_xray_modes\n",
        "import wpo_xray_modes\nimport wpo_xray_node_view\n",
        "node inspector import")
    source=one(source,
        '                             "/wpp-api/v1/federation/xray-mode",',
        '                             "/wpp-api/v1/federation/xray-mode",\n'
        '                             "/wpp-api/v1/federation/xray-config",',
        "node API allowlist")
    source=one(source,
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
        "node inspector endpoint")
    return source+"\n"+MARK+"\n"

def active(name):
    return subprocess.run(["systemctl","is-active","--quiet",name],
                          check=False).returncode==0

def get_module(name):
    req=Request(ROOT_URL+name,headers={"User-Agent":"WPO-V28-Installer"})
    with urlopen(req,timeout=35) as answer:
        raw=answer.read(180001)
    if not raw or len(raw)>180000:
        raise RuntimeError("Некорректный размер модуля "+name)
    content=raw.decode("utf-8")
    compile(content,name,"exec")
    return content

def main():
    parser=argparse.ArgumentParser(description="WPO V28 Xray JSON viewer + routing indicator")
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--apply",action="store_true")
    options=parser.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError("Запустите от sudo.")
    panel_dir=Path("/opt/tproxy-panel")
    agent_dir=Path("/opt/wpp-node-agent")
    panel=(panel_dir/"panel.py").is_file() and active("tproxy-panel.service")
    node=(agent_dir/"wpo_node_vpn.py").is_file() and active("wpo-node-vpn.service")
    if panel and node:
        raise RuntimeError("Нельзя определить роль VPS: одновременно панель и Node Agent.")
    if panel:
        patches={
            panel_dir/"panel.py":patch_panel,
            panel_dir/"wpo_xray_modes_ui.py":patch_mode_ui,
            panel_dir/"wpp_ui.py":patch_editor,
        }
        modules={
            panel_dir/"wpo_xray_node_view.py":"wpo_xray_node_view.py",
            panel_dir/"wpo_xray_node_view_ui.py":"wpo_xray_node_view_ui.py",
        }
        units=("tproxy-panel.service",)
    elif node:
        patches={agent_dir/"wpo_node_vpn.py":patch_vpn}
        modules={agent_dir/"wpo_xray_node_view.py":"wpo_xray_node_view.py"}
        units=("wpo-node-vpn.service",)
    else:
        raise RuntimeError("Запущенная тестовая WPO или нода с V27 не найдена.")
    originals={}
    changes={}
    for path,patch in patches.items():
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Ожидаемый исходник отсутствует: "+str(path))
        original=path.read_text(encoding="utf-8")
        transformed=patch(original)
        compile(transformed,str(path),"exec")
        originals[path]=original
        if transformed!=original:
            changes[path]=transformed
    for path,name in modules.items():
        if path.is_symlink():
            raise RuntimeError("Неожиданная ссылка: "+str(path))
        content=get_module(name)
        if path.exists():
            if not path.is_file():
                raise RuntimeError("Неожиданный путь: "+str(path))
            previous=path.read_text(encoding="utf-8")
            if previous!=content:
                raise RuntimeError("Модуль уже изменён вручную: "+str(path))
            originals[path]=previous
        else:
            originals[path]=None
            changes[path]=content
    if not changes:
        print("✓ WPO V28 уже установлен. Изменений нет.")
        return
    print("✓ Проверена версия V27 и",len(changes),"файлов для V28.")
    print("✓ REALITY, Hysteria2, порты, SNI, DNS и правила маршрутизации не изменяются.")
    if options.check:
        print("✓ Предварительная проверка успешна. Ничего не записано.")
        return
    BACKUPS.mkdir(parents=True,exist_ok=True)
    backup=BACKUPS/("xray-view-v28-"+("panel-" if panel else "node-")+
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if backup.exists():
        raise RuntimeError("Резервная копия уже существует")
    backup.mkdir(mode=0o700)
    for path,old in originals.items():
        if path in changes and old is not None:
            shutil.copy2(path,backup/path.name)
            os.chmod(backup/path.name,0o600)
    print("✓ Резервная копия:",backup)
    staged={}
    replaced=[]
    try:
        for path,content in changes.items():
            with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,
                    prefix=".wpo-v28-",suffix=".py",delete=False) as stream:
                stream.write(content)
                staged[path]=Path(stream.name)
            if originals[path] is not None:
                st=path.stat()
                os.chown(staged[path],st.st_uid,st.st_gid)
                os.chmod(staged[path],stat.S_IMODE(st.st_mode))
            else:
                os.chmod(staged[path],0o644)
        for path,tmp in staged.items():
            os.replace(tmp,path)
            replaced.append(path)
        for unit in units:
            subprocess.run(["systemctl","restart",unit],check=True,timeout=45)
        for attempt in range(15):
            if all(active(unit) for unit in units):
                print("✓ WPO V28 установлен. API/панель активны.")
                print("✓ В разделе Ноды доступны JSON-индикатор и просмотр полного Xray-кода.")
                return
            time.sleep(1)
        raise RuntimeError("Служба не запустилась после V28")
    except Exception:
        for path in replaced:
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                shutil.copy2(backup/path.name,path)
        for unit in units:
            subprocess.run(["systemctl","restart",unit],check=False)
        print("! Откат V28: прежние файлы восстановлены")
        raise
    finally:
        for tmp in staged.values():
            tmp.unlink(missing_ok=True)

if __name__=="__main__":
    try:
        main()
    except (ValueError,RuntimeError,OSError,subprocess.CalledProcessError) as error:
        print("ОШИБКА:",error,file=sys.stderr)
        sys.exit(1)
