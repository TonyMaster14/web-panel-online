#!/usr/bin/env python3
"""WPO V27 three per-node Xray configurations (test branch only).

Use on extra nodes first, then on the panel. No configuration change is made
during installation: only the ability to choose is installed.
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
from urllib.request import urlopen,Request

REPO="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"
PIN="30999fb5670a7ddb22dd0889412dd39e69ca7776"
BACKUP=Path("/var/backups/web-panel-online")
MARK="# WPO_XRAY_MODES_V27"

def swap(source,old,new,label):
    n=source.count(old)
    if n!=1:
        raise RuntimeError(f"V27: {label}: ожидалось 1 вхождение, найдено {n}; ничего не изменено")
    return source.replace(old,new,1)

def patch_reality(source):
    if MARK in source:return source
    old="config=copy.deepcopy(config); config['inbounds'].extend(inbounds(clients))"
    new="""config=copy.deepcopy(config); config['inbounds'].extend(inbounds(clients))
            import wpo_xray_modes
            config=wpo_xray_modes.tune_config(config,wpo_xray_modes.get(wpo_xray_modes.PANEL_STATE),enable_extras=wpo_xray_modes.PANEL_STATE.is_file())"""
    return swap(source,old,new,'manager REALITY inbound')+"\n"+MARK+"\n"

def patch_manager(source):
    if MARK in source:return source
    old='if cmd=="reality-config":'
    if old not in source:
        raise RuntimeError("WPO REALITY manager is not installed; no changes")
    new="""if cmd=="xray-mode":
    import wpo_xray_modes
    request=json.load(sys.stdin)
    with open(XRAY_CONFIG,encoding="utf-8") as stream:
        current=json.load(stream)
    print(json.dumps(wpo_xray_modes.switch(
        wpo_xray_modes.PANEL_STATE,request.get("mode"),current,
        lambda: sync_xray(load())),ensure_ascii=True))
elif cmd=="reality-config":"""
    return swap(source,old,new,'manager Xray mode CLI')+"\n"+MARK+"\n"

def patch_panel(source):
    if MARK in source:return source
    old='elif operation=="location":'
    new='''elif operation=="xray_mode":
                    import wpo_xray_modes
                    mode=wpo_xray_modes.normalize(form.get("mode",""))
                    uid=str(form.get("id",""))
                    if uid=="local":
                        result=subprocess.run([MANAGER,"xray-mode"],
                            input=json.dumps({"mode":mode}),text=True,
                            capture_output=True,timeout=95)
                        if result.returncode:
                            raise node_api.NodeError((result.stderr or "Xray отклонил конфигурацию.")[-700:])
                        response=json.loads(result.stdout)
                        if response.get("mode")!=mode or not response.get("ok"):
                            raise node_api.NodeError("Xray не подтвердил выбор.")
                    else:
                        nodes=node_api.load_nodes(NODES_FILE)
                        target=next((n for n in nodes if n.get("id")==uid),None)
                        if target is None: raise node_api.NodeError("Нода не найдена.")
                        previous=node_api.request(target,"GET",
                            node_api.API_PREFIX+"/federation/xray-mode",timeout=20)
                        previous_mode=wpo_xray_modes.normalize(previous.get("mode","both"))
                        response=node_api.request(target,"POST",
                            node_api.API_PREFIX+"/federation/xray-mode",
                            {"mode":mode},timeout=95)
                        if not response.get("ok") or response.get("mode")!=mode:
                            raise node_api.NodeError("Нода не подтвердила конфигурацию Xray.")
                        # The authenticated agent applied the change, but registry
                        # persistence may still fail; roll the agent back.
                        target["xray_mode"]=mode
                        try:
                            node_api.save_nodes(NODES_FILE,nodes)
                        except Exception:
                            try:
                                node_api.request(target,"POST",
                                    node_api.API_PREFIX+"/federation/xray-mode",
                                    {"mode":previous_mode},timeout=95)
                            except Exception:
                                raise node_api.NodeError("Сохранение реестра сорвалось. Проверьте режим на ноде.")
                            raise
                    import wpo_happ_async_feed
                    wpo_happ_async_feed.invalidate_all()
                elif operation=="location":'''
    source=swap(source,old,new,'node-action endpoint')
    return source+"\n"+MARK+"\n"

def patch_ui(source):
    if MARK in source:return source
    old="ns['connections_ui']=connections_ui;ns['nodes_ui']=nodes_ui"
    new="""ns['connections_ui']=connections_ui;ns['nodes_ui']=nodes_ui
    import wpo_xray_modes_ui
    wpo_xray_modes_ui.install_ui(ns)"""
    source=swap(source,old,new,'node UI wrapper')
    return source+"\n"+MARK+"\n"

def patch_feed(source):
    if MARK in source:return source
    source=swap(source,
        "    items = [(n, api.location_prefix(n)) for n in node_items]",
        """    import wpo_xray_modes
    items = [(n, api.location_prefix(n)) for n in node_items
             if wpo_xray_modes.select_for_node(n,protocols)]
    def for_node(n):
        return wpo_xray_modes.select_for_node(n,protocols)""",
        'Happ node filtering')
    source=swap(source,
        "        enqueue(api,node,external_id,name,protocols)",
        "        enqueue(api,node,external_id,name,for_node(node))",
        'Happ per-node enqueue')
    source=swap(source,
        "external_id,tuple(protocols)) for n,_ in items]",
        "external_id,tuple(for_node(n))) for n,_ in items]",
        'Happ per-node pending key')
    source=swap(source,
        "        batch,waiting=enqueue(api,node,external_id,name,protocols)",
        "        batch,waiting=enqueue(api,node,external_id,name,for_node(node))",
        'Happ per-node confirmed links')
    return source+"\n"+MARK+"\n"

def patch_vpn(source):
    if MARK in source:return source
    source=swap(source,
        "import uuid\nfrom http.server",
        "import uuid\nimport wpo_xray_modes\nfrom http.server",
        'Node Agent module import')
    # Explicitly load per-node mode whenever new live config is built.
    source=swap(source,
        '    return {"api":{"tag":"api","listen":"127.0.0.1:19090","services":["HandlerService"]},',
        '    config = {"api":{"tag":"api","listen":"127.0.0.1:19090","services":["HandlerService"]},',
        'Node render starts')
    source=swap(source,
        '            "outbounds": [{"tag": "direct", "protocol": "freedom"}]}\n\n\ndef link',
        '''            "outbounds": [{"tag": "direct", "protocol": "freedom"}]}
    return wpo_xray_modes.tune_config(config,wpo_xray_modes.get(wpo_xray_modes.NODE_STATE),enable_extras=wpo_xray_modes.NODE_STATE.is_file())


def link''',
        'Node render returns tuned config')
    source=swap(source,
        '        elif self.path == "/wpp-api/v1/federation/status":',
        '''        elif self.path == "/wpp-api/v1/federation/xray-mode":
            if not self.authorized():
                self.respond({"ok": False}, 401)
            else:
                self.respond({"ok": True, "mode":
                    wpo_xray_modes.get(wpo_xray_modes.NODE_STATE)})
        elif self.path == "/wpp-api/v1/federation/status":''',
        'Node GET mode')
    source=swap(source,
        '                             "/wpp-api/v1/federation/reality",',
        '                             "/wpp-api/v1/federation/reality",\n'
        '                             "/wpp-api/v1/federation/xray-mode",',
        'Node POST allowlist')
    source=swap(source,
        '            if operation == "reality":',
        '''            if operation == "xray-mode":
                with open(LOCK, "a+", encoding="ascii") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    current=read_json(XRAY,{"inbounds":[]})
                    result=wpo_xray_modes.switch(
                        wpo_xray_modes.NODE_STATE,data.get("mode"),current,
                        lambda: apply(read_json(STATE,{"profiles":{}})["profiles"]))
                    self.respond(result)
                return
            if operation == "reality":''',
        'Node POST applying mode')
    return source+"\n"+MARK+"\n"

def patch_eight(source):
    if MARK in source:return source
    anchor='    missing = sorted(set(raw) - available())'
    source=swap(source,anchor,
        '''    import wpo_xray_modes
    mode=wpo_xray_modes.get(wpo_xray_modes.NODE_STATE)
    forbidden=set(raw).intersection({"reality","hysteria"})-wpo_xray_modes.allowed(mode)
    if forbidden:
        raise RuntimeError("Протокол отключён конфигурацией Xray этой ноды: "+
                           ", ".join(sorted(forbidden)))
'''+anchor,'reject disabled protocols at Node Agent')
    return source+"\n"+MARK+"\n"

def active(unit):
    return subprocess.run(["systemctl","is-active","--quiet",unit],check=False).returncode==0

def fetch_module(name):
    url=REPO+PIN+"/src/"+name
    req=Request(url,headers={"User-Agent":"WPO-Xray-Modes-V27"})
    with urlopen(req,timeout=30) as stream:
        data=stream.read(220000)
    if not data or len(data)>200000:
        raise RuntimeError("Некорректный размер загруженного модуля "+name)
    content=data.decode("utf-8")
    compile(content,name,"exec")
    return content

def main():
    parser=argparse.ArgumentParser(description="WPO test Xray configuration modes V27")
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply",action="store_true")
    group.add_argument("--check",action="store_true")
    args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError("Требуется sudo")
    app=Path("/opt/tproxy-panel")
    node=Path("/opt/wpp-node-agent")
    panel=(app/"panel.py").is_file() and active("tproxy-panel.service")
    agent=(node/"wpo_node_vpn.py").is_file() and active("wpo-node-vpn.service")
    if panel:
        target_paths = {
            app/"panel.py":patch_panel,
            Path("/usr/local/sbin/web-proxy-panelctl"):patch_manager,
            app/"wpo_reality.py":patch_reality,
            app/"wpo_reality_ui.py":patch_ui,
            app/"wpo_happ_async_feed.py":patch_feed,
        }
        modules={app/"wpo_xray_modes.py":"wpo_xray_modes.py",
                 app/"wpo_xray_modes_ui.py":"wpo_xray_modes_ui.py"}
        units=["tproxy-panel.service"]
        destination="основная панель"
    elif agent:
        target_paths={node/"wpo_node_vpn.py":patch_vpn,
                      node/"wpo_node_eight.py":patch_eight}
        modules={node/"wpo_xray_modes.py":"wpo_xray_modes.py"}
        units=["wpo-node-vpn.service"]
        destination="дополнительная нода"
    else:
        raise RuntimeError("Не найдена запущенная WPO или Node Agent")
    originals={};new_content={}
    for path,patch in target_paths.items():
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Файл WPO отсутствует или является ссылкой: "+str(path))
        old=path.read_text(encoding="utf-8")
        newer=patch(old)
        compile(newer,str(path),"exec")
        originals[path]=old
        if newer!=old:new_content[path]=newer
    for path,name in modules.items():
        if path.is_symlink():raise RuntimeError("Неожиданная ссылка: "+str(path))
        newer=fetch_module(name)
        if path.exists():
            if not path.is_file():raise RuntimeError("Некорректный путь модуля: "+str(path))
            originals[path]=path.read_text(encoding="utf-8")
            if MARK in originals[path] or newer==originals[path]:
                continue
            # Never overwrite a manually customized module.
            raise RuntimeError("Модуль "+name+" уже существует и отличается. Не перезаписываем.")
        else:
            originals[path]=None
        new_content[path]=newer
    if not new_content:
        print("✓ V27 уже установлен; изменений нет")
        return
    print("✓ Подготовлено на:",destination)
    print("✓ Файлов к изменению:",", ".join(p.name for p in new_content))
    if args.check:
        print("✓ Проверка исходников пройдена. Файлы не изменены.")
        return
    BACKUP.mkdir(parents=True,exist_ok=True)
    folder=BACKUP/("xray-modes-v27-"+("panel-" if panel else "node-")+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if folder.exists():raise RuntimeError("Резервная копия уже существует.")
    folder.mkdir(mode=0o700)
    for path,old in originals.items():
        if path in new_content and old is not None:
            shutil.copy2(path,folder/path.name)
            os.chmod(folder/path.name,0o600)
    print("✓ Резервная копия:",folder)
    staged={};replaced=[]
    try:
        for path,newer in new_content.items():
            with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,
                    prefix=".wpo-xray-mode-v27-",suffix=".py",delete=False) as stream:
                stream.write(newer);staged[path]=Path(stream.name)
            if path in originals and originals[path] is not None:
                st=path.stat()
                os.chown(staged[path],st.st_uid,st.st_gid)
                os.chmod(staged[path],stat.S_IMODE(st.st_mode))
            else:
                os.chmod(staged[path],0o644)
        for path,tmp in staged.items():
            os.replace(tmp,path);replaced.append(path)
        for unit in units:
            subprocess.run(["systemctl","restart",unit],check=True,timeout=45)
        for _ in range(15):
            if all(active(u) for u in units):
                print("✓ V27 установлен. Службы работают.")
                print("✓ Пользователи, порты, ключи и режим нод не менялись.")
                return
            time.sleep(1)
        raise RuntimeError("Служба WPO не восстановилась")
    except Exception:
        for path in replaced:
            if originals.get(path) is None:path.unlink(missing_ok=True)
            else:shutil.copy2(folder/path.name,path)
        for unit in units:
            subprocess.run(["systemctl","restart",unit],check=False)
        print("! Ошибка установки: предыдущие файлы восстановлены")
        raise
    finally:
        for tmp in staged.values():tmp.unlink(missing_ok=True)

if __name__=="__main__":
    try:main()
    except (OSError,RuntimeError,ValueError,subprocess.CalledProcessError) as error:
        print("ОШИБКА:",error,file=sys.stderr);sys.exit(1)
