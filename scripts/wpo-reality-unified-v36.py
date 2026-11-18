#!/usr/bin/env python3
"""WPO V36 universal REALITY baseline (test branch only).

One command on every WPO VPS. Auto-detect panel vs additional node, guard
against unintended changes, preserve original SNI/ports/users/secret keys.
Success criterion: exactly 1 VLESS REALITY inbound and
realitySettings.minClientVer = "1.0.0"; other Xray JSON fields unchanged.
Extra nodes also get the authenticated read-only JSON inspection API.

--check: read-only preview, compare current vs reconstructed config, Xray and
HAProxy preflight. --apply: same checks + backup, atomic replacement, restart
only affected services, authenticated local API check and automatic rollback.

Legacy links using a removed alternative SNI will cease to work. Refresh HAPP.
Never overwrites GitHub main. This script ONLY modifies local test VPS files.
"""
from __future__ import annotations
import argparse
import ast
import copy
from datetime import datetime, timezone
import fcntl
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError

ROOT = Path("/opt")
NODE = ROOT / "wpp-node-agent"
PANEL = ROOT / "tproxy-panel"
REALITY_ROOT = Path("/etc/web-proxy-panel/reality")
PROFILE = REALITY_ROOT / "profile.json"
ROUTER = REALITY_ROOT / "haproxy.cfg"
XRAY_BIN = Path("/opt/web-panel-proxy/xray/xray")
NODE_JSON = Path("/etc/wpp-node-vpn/xray.json")
PANEL_JSON = Path("/etc/web-panel-proxy-xray/config.json")
BACKUP_ROOT = Path("/var/backups/web-panel-online")
NODE_LOCK = Path("/etc/wpp-node-vpn/.federation.lock")
PANEL_LOCK = Path("/etc/web-proxy-panel/manager.lock")
VIEW_URL = ("https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"
            "f36abb6c16da7ff65538f9b662ac9ec3a7b8914e/src/wpo_xray_node_view.py")
ROUTES_MARK = "# WPO_UNIFIED_REALITY_ROUTES_V36"
INBOUNDS_MARK = "# WPO_UNIFIED_REALITY_INBOUNDS_V36"
RENDER_MARK = "# WPO_UNIFIED_REALITY_RENDER_V36"
ENDPOINT = "/wpp-api/v1/federation/xray-config"

ROUTES_HOOK = '''
# WPO_UNIFIED_REALITY_ROUTES_V36
_wpo_unified_original_routes = reality_routes
def reality_routes(profile=None):
    routes = _wpo_unified_original_routes(profile)
    selected = (profile or read_profile())["sni"]
    chosen = [(host, port) for host, port in routes if host == selected]
    if len(chosen) != 1:
        raise RuntimeError("Selected REALITY SNI has no unique route")
    return chosen
'''
INBOUNDS_HOOK = '''
# WPO_UNIFIED_REALITY_INBOUNDS_V36
_wpo_unified_original_inbounds = inbounds
def inbounds(*args, **kwargs):
    entries = _wpo_unified_original_inbounds(*args, **kwargs)
    reals = [i for i in entries if i.get("protocol") == "vless"
             and i.get("streamSettings", {}).get("security") == "reality"]
    if len(reals) != 1:
        raise RuntimeError("Expected one REALITY inbound")
    reals[0]["streamSettings"]["realitySettings"]["minClientVer"] = "1.0.0"
    return entries
'''
RENDER_HOOK = '''
# WPO_UNIFIED_REALITY_RENDER_V36
_wpo_unified_original_render = render_xray
def render_xray(*args, **kwargs):
    result = _wpo_unified_original_render(*args, **kwargs)
    real = [i for i in result.get("inbounds", []) if
            i.get("protocol") == "vless"
            and i.get("streamSettings", {}).get("security") == "reality"]
    if not real:
        return result
    profile = wpo_reality.read_profile()
    sni = profile["sni"]
    chosen = [i for i in real if i.get("streamSettings",{}).get(
              "realitySettings",{}).get("serverNames") == [sni]]
    if len(chosen) != 1:
        raise RuntimeError("Current REALITY SNI must match exactly one inbound")
    if any(i.get("settings",{}).get("clients",[]) != chosen[0].get(
           "settings",{}).get("clients",[]) for i in real):
        raise RuntimeError("Cannot consolidate REALITY inbounds with different users")
    chosen[0]["streamSettings"]["realitySettings"]["minClientVer"] = "1.0.0"
    result["inbounds"] = [
        i for i in result["inbounds"]
        if not (i.get("protocol") == "vless"
                and i.get("streamSettings",{}).get("security") == "reality")
        or i is chosen[0]]
    return result
'''

PREVIEW = r'''
import importlib.util, inspect, json, sys
from pathlib import Path
role, original_module, new_module, candidate_json, candidate_router, agent_file = sys.argv[1:]
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value
old=load(original_module,"wpo_reality_old_preview")
new=load(new_module,"wpo_reality_new_preview")
profile=new.read_profile()
sni=profile["sni"]
port=int(profile.get("port",443))
def router(m):
    if not callable(getattr(m,"haproxy_config",None)):
        raise RuntimeError("No haproxy_config() generator")
    kwargs={"port":port} if "port" in inspect.signature(m.haproxy_config).parameters else {}
    return m.haproxy_config(sni,**kwargs)
if candidate_router!="-":
    actual=Path("/etc/web-proxy-panel/reality/haproxy.cfg").read_text(encoding="utf-8")
    before=router(old)
    after=router(new)
    if actual!=before:
        raise RuntimeError("Current HAProxy has custom changes; refusing to overwrite")
    bind=lambda cfg:sorted(line.strip() for line in cfg.splitlines()
                           if line.strip().startswith("bind "))
    if bind(before)!=bind(after):
        raise RuntimeError("Public HAProxy listener ports changed")
    if "backend website" not in after:
        raise RuntimeError("Website HAProxy backend disappeared")
    Path(candidate_router).write_text(after,encoding="utf-8")
if role=="panel":
    current=json.loads(Path("/etc/web-panel-proxy-xray/config.json").read_text())
    real=[i for i in current["inbounds"] if
          i.get("protocol")=="vless" and
          i.get("streamSettings",{}).get("security")=="reality"]
    selected=[i for i in real if i.get("streamSettings",{}).get(
              "realitySettings",{}).get("serverNames")==[sni]]
    if len(selected)!=1:
        raise RuntimeError("Selected SNI does not match exactly one live inbound")
    clients=selected[0].get("settings",{}).get("clients",[])
    generated=new.inbounds(clients)
    if len(generated)!=1:
        raise RuntimeError("Patched panel generator emits more than one REALITY")
    proposed=json.loads(Path(candidate_json).read_text())
    expected=[i for i in proposed["inbounds"] if
              i.get("protocol")=="vless" and
              i.get("streamSettings",{}).get("security")=="reality"]
    if generated!=expected:
        raise RuntimeError("Panel generator does not reproduce selected REALITY inbound")
else:
    sys.path.insert(0,"/opt/wpp-node-agent")
    agent=load(agent_file,"wpo_node_agent_preview_v36")
    agent.wpo_reality=new
    state=agent.read_json(agent.STATE,{"profiles":{}})["profiles"]
    settings=agent.read_json(agent.SETTINGS)
    generated=agent.render_xray(state,settings)
    expected=json.loads(Path(candidate_json).read_text())
    if generated!=expected:
        raise RuntimeError("Node generator differs from live config beyond expected REALITY change")
print("PASS: REALITY generator will persist single inbound with minClientVer 1.0.0")
'''

def run(*argv,timeout=40):
    return subprocess.run([str(a) for a in argv],check=False,text=True,
                          capture_output=True,timeout=timeout)

def active(service):
    return run("systemctl","is-active","--quiet",service,timeout=5).returncode==0

def required(path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Required regular file missing: "+str(path))
    return path.stat()

def real(item):
    return (isinstance(item,dict) and item.get("protocol")=="vless" and
            item.get("streamSettings",{}).get("security")=="reality")

def patch_reality(source,panel,live_count):
    tree=ast.parse(source)
    functions={node.name for node in tree.body if isinstance(node,ast.FunctionDef)}
    if "read_profile" not in functions:
        raise RuntimeError("Unexpected WPO REALITY profile generator; no changes made")
    if (panel or live_count>1) and "haproxy_config" not in functions:
        raise RuntimeError("Cannot consolidate SNI without a HAProxy generator")
    changed=source
    if "reality_routes" in functions and ROUTES_MARK not in changed:
        changed += "\n"+ROUTES_HOOK
    elif panel and "reality_routes" not in functions:
        raise RuntimeError("Panel REALITY generator cannot limit its SNI routes")
    if panel:
        if "inbounds" not in functions:
            raise RuntimeError("Panel REALITY generator has no inbounds()")
        if INBOUNDS_MARK not in changed:
            changed += "\n"+INBOUNDS_HOOK
    compile(changed,"wpo_reality.py","exec")
    return changed

def patch_agent(source):
    if RENDER_MARK in source:
        result=source
    else:
        tree=ast.parse(source)
        matches=[f for f in tree.body if isinstance(f,ast.FunctionDef)
                 and f.name=="render_xray"]
        if len(matches)!=1:
            raise RuntimeError("Node Agent render_xray() generator not found")
        lines=source.splitlines(keepends=True)
        lines.insert(matches[0].end_lineno,"\n"+RENDER_HOOK+"\n")
        result="".join(lines)
    if ENDPOINT not in result:
        old='                             "/wpp-api/v1/federation/reality",'
        if result.count(old)!=1:
            raise RuntimeError("Old Node Agent has different API allowlist")
        result=result.replace(old,old+'\n'
                  '                             "/wpp-api/v1/federation/xray-config",',1)
        old='            operation = self.path.rsplit("/", 1)[-1]\n            if operation == "reality":'
        new='''            operation = self.path.rsplit("/", 1)[-1]
            if operation == "xray-config":
                import wpo_xray_node_view
                try:
                    profile=wpo_reality.read_profile() if REALITY_READY else None
                except (OSError,ValueError,TypeError):
                    profile=None
                self.respond(wpo_xray_node_view.view(
                    XRAY, reveal=data.get("reveal") is True,
                    reality_profile=profile))
                return
            if operation == "reality":'''
        if result.count(old)!=1:
            raise RuntimeError("Old Node Agent dispatch structure differs")
        result=result.replace(old,new,1)
    elif 'if operation == "xray-config":' not in result:
        raise RuntimeError("Node Agent API endpoint is partially installed")
    compile(result,"wpo_node_vpn.py","exec")
    return result

def fetch_view():
    req=Request(VIEW_URL,headers={"User-Agent":"WPO-unified-V36"})
    with urlopen(req,timeout=25) as resp:raw=resp.read(120001)
    if len(raw)>120000 or not raw:raise RuntimeError("JSON viewer download failed")
    data=raw.decode("utf-8")
    if "def view(" not in data or "HIDDEN =" not in data:
        raise RuntimeError("Unexpected JSON viewer module")
    compile(data,"wpo_xray_node_view.py","exec")
    return data

def generate_candidate(current,sni):
    real_old=[i for i in current["inbounds"] if real(i)]
    selected=[i for i in real_old if i.get("streamSettings",{}).get(
              "realitySettings",{}).get("serverNames")==[sni]]
    if len(selected)!=1:
        raise RuntimeError("Selected SNI must occur in exactly one REALITY inbound")
    wanted=selected[0]
    if any(i.get("settings",{}).get("clients",[]) != wanted.get(
           "settings",{}).get("clients",[]) for i in real_old):
        raise RuntimeError("Old SNI backends have different UUIDs; cannot safely consolidate")
    result=copy.deepcopy(current)
    chosen=next(i for i in result["inbounds"] if real(i) and i.get(
        "streamSettings",{}).get("realitySettings",{}).get("serverNames")==[sni])
    chosen["streamSettings"]["realitySettings"]["minClientVer"]="1.0.0"
    result["inbounds"]=[i for i in result["inbounds"] if not real(i) or i is chosen]
    if len([i for i in result["inbounds"] if real(i)])!=1:
        raise RuntimeError("Candidate did not reduce REALITY to one inbound")
    return result,len(real_old),len(wanted.get("settings",{}).get("clients",[]))

def atomic(path,raw,oldstat=None):
    fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix=".wpo-unified-")
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(raw);out.flush();os.fsync(out.fileno())
        if oldstat is None:
            os.chmod(tmp,0o644)
        else:
            os.chown(tmp,oldstat.st_uid,oldstat.st_gid)
            os.chmod(tmp,stat.S_IMODE(oldstat.st_mode))
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def local_api():
    cfg=json.loads(Path("/etc/wpp-node-agent/config.json").read_text())
    token=cfg.get("api_key","")
    if not token:raise RuntimeError("Node Agent API key missing")
    req=Request("http://127.0.0.1:9089"+ENDPOINT,method="POST",
        data=b'{"reveal":false}',headers={
        "Authorization":"Bearer "+token,"Content-Type":"application/json"})
    opener=build_opener(ProxyHandler({}))
    with opener.open(req,timeout=10) as response:
        raw=response.read(1048577)
        if len(raw)>1048576:raise RuntimeError("Node JSON reply too large")
        data=json.loads(raw.decode("utf-8"))
    if not isinstance(data,dict) or data.get("ok") is not True:
        raise RuntimeError("Node API did not return valid JSON")
    if data.get("secrets_visible") is not False:
        raise RuntimeError("Node API must redact private keys")
    config=data.get("config",{})
    hits=[i for i in config.get("inbounds",[]) if real(i)]
    if len(hits)!=1 or hits[0].get("streamSettings",{}).get(
        "realitySettings",{}).get("minClientVer")!="1.0.0":
        raise RuntimeError("Node API does not expose the expected REALITY config")
    return True

def main():
    parser=argparse.ArgumentParser(description="WPO unified REALITY: 1 SNI + minClientVer 1.0.0")
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check",action="store_true")
    choice.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError("sudo required")
    panel=(PANEL/"panel.py").is_file() and active("tproxy-panel.service")
    node=(NODE/"wpo_node_vpn.py").is_file() and active("wpo-node-vpn.service")
    if panel==node:
        raise RuntimeError("Cannot uniquely determine WPO panel vs Node Agent")
    role="основная панель" if panel else "дополнительная нода"
    base=PANEL if panel else NODE
    xray_path=PANEL_JSON if panel else NODE_JSON
    source=base/"wpo_reality.py"
    agent=NODE/"wpo_node_vpn.py"
    required(source);required(xray_path);required(PROFILE);required(ROUTER)
    required(XRAY_BIN)
    if panel:
        manager=Path("/usr/local/sbin/web-proxy-panelctl")
        required(manager)
        if "wpo_reality.install_manager(globals())" not in manager.read_text(encoding="utf-8"):
            raise RuntimeError("Panel manager has no REALITY generation hook")
    for unit in (("web-panel-proxy-xray.service","wpo-tls-router.service") if panel
                 else ("wpo-node-xray.service","wpo-node-vpn.service","wpo-tls-router.service")):
        if not active(unit):
            raise RuntimeError("Important service not active: "+unit)
    profile=json.loads(PROFILE.read_text(encoding="utf-8"))
    if not isinstance(profile,dict) or not isinstance(profile.get("sni"),str):
        raise RuntimeError("REALITY profile missing SNI")
    sni=profile["sni"]
    current=json.loads(xray_path.read_text(encoding="utf-8"))
    if not isinstance(current,dict) or not isinstance(current.get("inbounds"),list):
        raise RuntimeError("Invalid current Xray JSON")
    candidate,count,clients=generate_candidate(current,sni)
    print("✓ Роль:",role)
    print("✓ REALITY inbound: ",count,"→ 1")
    print("✓ SNI:",sni,"· внешний порт:",profile.get("port",443))
    print("✓ REALITY клиентов:",clients,"· minClientVer: 1.0.0")
    if count>1: print("! Старые ссылки с другими SNI после обновления перестанут работать.")

    before=source.read_text(encoding="utf-8")
    updated_reality=patch_reality(before,panel,count)
    original_agent=agent.read_text(encoding="utf-8") if node else None
    updated_agent=patch_agent(original_agent) if node else None
    module_path=NODE/"wpo_xray_node_view.py"
    view_new=None
    if node and not module_path.exists():
        view_new=fetch_view()
    elif node and module_path.exists():
        required(module_path)
        if "def view(" not in module_path.read_text(encoding="utf-8"):
            raise RuntimeError("Unexpected existing Xray viewer")
    changes={}
    if updated_reality!=before:changes[source]=updated_reality.encode("utf-8")
    if node and updated_agent!=original_agent:
        changes[agent]=updated_agent.encode("utf-8")
    if view_new is not None:changes[module_path]=view_new.encode("utf-8")
    if candidate!=current:
        changes[xray_path]=json.dumps(candidate,ensure_ascii=False,indent=2).encode("utf-8")

    lock_path=PANEL_LOCK if panel else NODE_LOCK
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    with open(lock_path,"a+",encoding="ascii") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix=".wpo-unified-v36-",dir=str(base)) as ws:
            tmp=Path(ws)
            source_preview=tmp/"wpo_reality_preview.py"
            source_old=tmp/"wpo_reality_original.py"
            agent_preview=tmp/"wpo_node_vpn_preview.py"
            candidate_xray=tmp/"xray-test.json"
            candidate_router=tmp/"haproxy-test.cfg"
            source_preview.write_text(updated_reality,encoding="utf-8")
            source_old.write_text(before,encoding="utf-8")
            candidate_xray.write_text(json.dumps(candidate),encoding="utf-8")
            if node:agent_preview.write_text(updated_agent,encoding="utf-8")
            needs_router=count>1
            router_arg=str(candidate_router) if needs_router else "-"
            result=run(sys.executable,"-c",PREVIEW,"panel" if panel else "node",
                       source_old,source_preview,candidate_xray,router_arg,
                       agent_preview if node else "-",timeout=45)
            if result.returncode:
                raise RuntimeError("Generator preview failed, nothing changed: "+
                                   (result.stderr or result.stdout or "unknown")[-1000:])
            print("✓",result.stdout.strip())
            check=run(XRAY_BIN,"run","-test","-config",candidate_xray,timeout=40)
            if check.returncode:
                raise RuntimeError("Xray rejects new JSON; unchanged: "+
                                   (check.stderr or check.stdout or "unknown")[-800:])
            print("✓ Xray: Configuration OK")
            if needs_router:
                hap=run("haproxy","-c","-f",candidate_router,timeout=30)
                if hap.returncode:
                    raise RuntimeError("HAProxy rejects candidate; unchanged: "+
                                       (hap.stderr or hap.stdout or "unknown")[-800:])
                changes[ROUTER]=candidate_router.read_bytes()
                print("✓ HAProxy: configuration OK; external binds unchanged")
            if not changes:
                if node:
                    local_api()
                    print("✓ Node JSON API HTTP 200, credentials redacted")
                print("✓ Эталон Швеции уже активен; изменений не требуется")
                return
            print("✓ Изменения:",", ".join(f.name for f in changes))
            if args.check:
                print("✓ Сухая проверка завершена: файлы и службы не менялись")
                return
            backup=BACKUP_ROOT/("reality-unified-v36-"+
                ("panel-" if panel else "node-")+
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            backup.mkdir(parents=True,mode=0o700,exist_ok=False)
            oldstats={}
            for f in changes:
                if f.exists():
                    oldstats[f]=required(f)
                    shutil.copy2(f,backup/f.name)
                    os.chmod(backup/f.name,0o600)
                else:
                    oldstats[f]=None
            print("✓ Резервная копия:",backup)
            written=[]
            units=["web-panel-proxy-xray.service","wpo-tls-router.service",
                   "tproxy-panel.service"] if panel else [
                   "wpo-node-xray.service","wpo-tls-router.service","wpo-node-vpn.service"]
            try:
                for f,raw in changes.items():
                    atomic(f,raw,oldstats[f]);written.append(f)
                for unit in units:
                    if (unit=="wpo-tls-router.service" and ROUTER not in changes):
                        continue
                    r=run("systemctl","restart",unit,timeout=50)
                    if r.returncode:
                        raise RuntimeError("Restart failed: "+unit)
                for _ in range(12):
                    if all(active(unit) for unit in units):break
                    time.sleep(1)
                else:raise RuntimeError("Not all WPO services recovered")
                final=json.loads(xray_path.read_text(encoding="utf-8"))
                wanted=[r for r in final["inbounds"] if real(r)]
                if len(wanted)!=1 or wanted[0]["streamSettings"][
                    "realitySettings"].get("minClientVer")!="1.0.0":
                    raise RuntimeError("Final JSON is missing single REALITY+minClientVer")
                if node:
                    local_api()
                    print("✓ Авторизованный Node API вернул JSON: 1 REALITY, ключи скрыты")
                print("✓ ГОТОВО: единый стандарт REALITY, 1 SNI, minClientVer 1.0.0")
                print("✓ Ключи, пользователи, SNI, TCP-порт и другие протоколы сохранены")
                print("✓ Проверка через HAPP после установки обязательна")
            except Exception:
                for f in written:
                    if oldstats[f] is None:f.unlink(missing_ok=True)
                    else:atomic(f,(backup/f.name).read_bytes(),oldstats[f])
                for unit in units:
                    run("systemctl","restart",unit,timeout=50)
                print("! ОШИБКА: исходные файлы восстановлены, сервисы перезапущены")
                raise

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print("ОШИБКА:",str(exc)[:1300],file=sys.stderr)
        sys.exit(1)
