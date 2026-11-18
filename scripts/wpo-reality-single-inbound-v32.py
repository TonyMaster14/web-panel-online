#!/usr/bin/env python3
"""WPO V32 (test): one REALITY inbound per node, minClientVer=1.0.0.

Use on a *test additional node* with wpo-node-vpn, not the WPO controller.
--check validates everything WITHOUT modifying files or restarting services.
--apply validates Xray and HAProxy BEFORE writing, then applies atomically;
backs up original source/configs and restores them if any check fails.

CAUTION: legacy links using different SNI preset hosts may stop working.
Uses the node's selected SNI and existing HAProxy/Caddy architecture, NOT
RemnaWave's PROXY-v1 Unix socket (which WPO has not deployed).
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

APP=Path("/opt/wpp-node-agent")
SRC=APP/"wpo_reality.py"
REALITY_DIR=Path("/etc/web-proxy-panel/reality")
PUBLIC=REALITY_DIR/"profile.json"
HAPROXY=REALITY_DIR/"haproxy.cfg"
XRAY=Path("/etc/wpp-node-vpn/xray.json")
LOCK=Path("/etc/wpp-node-vpn/.federation.lock")
BACKUPS=Path("/var/backups/web-panel-online")
XRAY_BIN=Path("/opt/web-panel-proxy/xray/xray")
MARK="# WPO_SINGLE_REALITY_V32"
RUN_TEST=r'''
import importlib.util,inspect,json,sys
from pathlib import Path
sys.path.insert(0,"/opt/wpp-node-agent")
import wpo_node_vpn as vpn
spec=importlib.util.spec_from_file_location("wpo_reality_preview_v32",sys.argv[1])
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
vpn.wpo_reality=mod
state=vpn.read_json(vpn.STATE,{"profiles":{}})["profiles"]
settings=vpn.read_json(vpn.SETTINGS)
config=vpn.render_xray(state,settings)
real=[i for i in config["inbounds"] if i.get("protocol")=="vless"
      and i.get("streamSettings",{}).get("security")=="reality"]
if len(real)!=1:raise RuntimeError("Expected exactly one REALITY inbound")
current=json.loads(vpn.XRAY.read_text(encoding="utf-8"))
old_real=[i for i in current.get("inbounds",[]) if i.get("protocol")=="vless"
          and i.get("streamSettings",{}).get("security")=="reality"]
profile=mod.read_profile()
matching=[i for i in old_real if
          i.get("streamSettings",{}).get("realitySettings",{}).get(
          "serverNames")==[profile["sni"]]]
if len(matching)!=1 or matching[0].get("settings",{}).get("clients",[])!=real[0].get(
    "settings",{}).get("clients",[]):
    raise RuntimeError("Saved node users do not match the live REALITY configuration")
rs=real[0]["streamSettings"]["realitySettings"]
if rs.get("minClientVer")!="1.0.0" or rs.get("serverNames")!=[profile["sni"]]:
    raise RuntimeError("Incorrect SNI or minClientVer")
if real[0]["port"]!=mod.PORT or real[0]["listen"]!="127.0.0.1":
    raise RuntimeError("Internal REALITY listener changed")
def nonreality(a):
    return [i for i in a if not
      (i.get("protocol")=="vless" and
       i.get("streamSettings",{}).get("security")=="reality")]
current=json.loads(vpn.XRAY.read_text(encoding="utf-8"))
if nonreality(current["inbounds"])!=nonreality(config["inbounds"]):
    raise RuntimeError("Another inbound (including Hysteria2/XHTTP) changed")
if config.get("outbounds")!=current.get("outbounds") or config.get("api")!=current.get("api"):
    raise RuntimeError("Xray API/outbounds unexpectedly changed")
with open(sys.argv[2],"w",encoding="utf-8") as out:
    json.dump(config,out,ensure_ascii=False)
kwargs={}
if "port" in inspect.signature(mod.haproxy_config).parameters:
    kwargs["port"]=int(profile.get("port",443))
text=mod.haproxy_config(profile["sni"],**kwargs)
if "use_backend reality if { req.ssl_sni -i "+profile["sni"]+" }" not in text:
    raise RuntimeError("HAProxy does not route to selected SNI")
if text.count("use_backend reality")!=1 or "backend reality_" in text:
    raise RuntimeError("Legacy REALITY backends remain")
if "bind 0.0.0.0:443" not in text:
    raise RuntimeError("Panel HTTPS bind lost")
with open(sys.argv[3],"w",encoding="utf-8") as out:
    out.write(text)
print("CHECK OK: REALITY=1, minClientVer=1.0.0; other protocols preserved")
'''

def cmd(*args,timeout=30):
    return subprocess.run(list(map(str,args)),check=False,text=True,
                          capture_output=True,timeout=timeout)

def active(name):
    return cmd("systemctl","is-active","--quiet",name,timeout=6).returncode==0

def secure_stat(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Required file missing or symlink: "+str(path))
    return path.stat()

def patch(source):
    if MARK in source:
        return source,False
    replacements=[
        ("    return [(host, PORT + offset) for offset, host in enumerate(hosts)]",
         "    return [(current, PORT)]",
         "one selected REALITY target"),
        ("                    'shortIds': [profile['short_id']]}}",
         "                    'shortIds': [profile['short_id']],\n"
         "                    'minClientVer': '1.0.0'}}",
         "RemnaWave minimum client version"),
    ]
    for old,new,label in replacements:
        count=source.count(old)
        if count!=1:
            raise RuntimeError(
                "Installed REALITY generator unexpected ("+label+
                ", matches "+str(count)+"). Nothing changed.")
        source=source.replace(old,new,1)
    compile(source,str(SRC),"exec")
    return source+"\n"+MARK+"\n",True

def atomically_replace(path,data,owner):
    mode=stat.S_IMODE(owner.st_mode)
    fd,temp=tempfile.mkstemp(prefix=".wpo-v32-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temp,owner.st_uid,owner.st_gid)
        os.chmod(temp,mode)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def wait_units(names):
    for _ in range(10):
        if all(active(name) for name in names):return True
        time.sleep(1)
    return False

def inspect():
    for unit in ("wpo-node-xray.service","wpo-node-vpn.service","wpo-tls-router.service"):
        if not active(unit):
            raise RuntimeError("Expected live service is not running: "+unit)
    for f in (SRC,PUBLIC,HAPROXY,XRAY,XRAY_BIN):
        secure_stat(f)
    current=json.loads(XRAY.read_text(encoding="utf-8"))
    profile=json.loads(PUBLIC.read_text(encoding="utf-8"))
    real=[inb for inb in current.get("inbounds",[]) if
          isinstance(inb,dict) and inb.get("protocol")=="vless"
          and inb.get("streamSettings",{}).get("security")=="reality"]
    if not real:raise RuntimeError("No REALITY inbounds found")
    if not isinstance(profile,dict) or not isinstance(profile.get("sni"),str):
        raise RuntimeError("REALITY SNI profile is incomplete")
    selected=profile["sni"]
    sni_found=[r for r in real if r.get("streamSettings",{}).get(
        "realitySettings",{}).get("serverNames")==[selected]]
    if len(sni_found)!=1:
        raise RuntimeError("Selected SNI must match exactly one existing REALITY inbound")
    # Ensure this does not silently drop identities from any alias inbound.
    same_clients=all(r.get("settings",{}).get("clients",[])==
                     sni_found[0].get("settings",{}).get("clients",[])
                     for r in real)
    if not same_clients:
        raise RuntimeError("REALITY alias inbounds have different users; consolidation unsafe")
    print("✓ Текущий выбранный SNI:",selected)
    print("✓ Внешний REALITY TCP-порт:",profile.get("port",443))
    print("✓ REALITY inbound сейчас:",len(real))
    print("✓ Пользовательские ключи в дополнительных REALITY совпадают:",same_clients)
    return current,profile,real

def main():
    parser=argparse.ArgumentParser()
    choices=parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--check",action="store_true")
    choices.add_argument("--apply",action="store_true")
    a=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError("sudo is required")
    if (Path("/opt/tproxy-panel/panel.py").is_file()
            and active("tproxy-panel.service")):
        raise RuntimeError("This is the controller. V32 is for a TEST additional node.")
    if not active("wpo-node-vpn.service"):
        raise RuntimeError("No running WPO Node VPN Agent found")
    current,profile,real=inspect()
    original=SRC.read_text(encoding="utf-8")
    proposed,changed=patch(original)
    if not changed and len(real)==1 and real[0].get("streamSettings",{}).get(
        "realitySettings",{}).get("minClientVer")=="1.0.0":
        print("✓ V32 already active. No modifications.")
        return
    if not changed:
        raise RuntimeError("Source already V32, but active configuration differs; stop and inspect")
    if len(real)>1:
        print("! После перехода останется один выбранный SNI.")
        print("! Старые клиентские ссылки с другими SNI перестанут подключаться.")
    # Lock Node Agent profile mutations for the entire read/validate/apply.
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    with open(LOCK,"a+",encoding="ascii") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        before_stats={f:secure_stat(f) for f in (SRC,XRAY,HAPROXY)}
        with tempfile.TemporaryDirectory(prefix=".wpo-reality-v32-",dir=str(APP)) as folder:
            temp=Path(folder)
            module=temp/"wpo_reality_preview_v32.py"
            candidate=temp/"candidate-xray.json"
            router=temp/"candidate-haproxy.cfg"
            module.write_text(proposed,encoding="utf-8")
            module.chmod(0o600)
            r=cmd(sys.executable,"-c",RUN_TEST,module,candidate,router,timeout=30)
            if r.returncode:
                raise RuntimeError("Cannot create short REALITY config: "+(r.stderr or "unknown")[-900:])
            print("✓",r.stdout.strip())
            x=cmd(XRAY_BIN,"run","-test","-config",candidate,timeout=30)
            if x.returncode:
                raise RuntimeError("Xray rejects candidate config. No changes made. "+(x.stderr or "")[-500:])
            h=cmd("haproxy","-c","-f",router,timeout=20)
            if h.returncode:
                raise RuntimeError("HAProxy rejects candidate config. No changes made. "+(h.stderr or "")[-500:])
            print("✓ Xray и HAProxy приняли сокращённую конфигурацию")
            print("✓ Остальные inbound, включая Hysteria2, остались без изменений")
            if a.check:
                print("✓ Только проверка: серверные файлы не менялись")
                return
            backups=BACKUPS/("reality-single-v32-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            backups.mkdir(parents=True,mode=0o700,exist_ok=False)
            for f in (SRC,XRAY,HAPROXY):
                shutil.copy2(f,backups/f.name)
                os.chmod(backups/f.name,0o600)
            print("✓ Резервная копия:",backups)
            patched=[]
            try:
                for f,data in ((SRC,proposed.encode("utf-8")),(XRAY,candidate.read_bytes()),
                               (HAPROXY,router.read_bytes())):
                    atomically_replace(f,data,before_stats[f])
                    patched.append(f)
                for service in ("wpo-node-xray.service","wpo-tls-router.service","wpo-node-vpn.service"):
                    r=cmd("systemctl","restart",service,timeout=40)
                    if r.returncode:
                        raise RuntimeError("Failed restarting "+service)
                if not wait_units(("wpo-node-xray.service","wpo-tls-router.service",
                                   "wpo-node-vpn.service")):
                    raise RuntimeError("Services did not recover")
                live=json.loads(XRAY.read_text(encoding="utf-8"))
                updated=[i for i in live.get("inbounds",[])
                         if i.get("protocol")=="vless" and
                         i.get("streamSettings",{}).get("security")=="reality"]
                if len(updated)!=1 or updated[0]["streamSettings"]["realitySettings"].get(
                    "minClientVer")!="1.0.0":
                    raise RuntimeError("Running JSON does not show expected V32 REALITY")
                print("✓ V32 applied: one REALITY inbound, minClientVer 1.0.0")
                print("✓ SNI, external TCP port, private key, Short ID and Hysteria2 preserved")
                print("✓ Restarted node Xray/router/API; reconnect to this node in HAPP.")
            except Exception:
                for f in patched:
                    original_data=(backups/f.name).read_bytes()
                    atomically_replace(f,original_data,before_stats[f])
                for service in ("wpo-node-xray.service","wpo-tls-router.service","wpo-node-vpn.service"):
                    cmd("systemctl","restart",service,timeout=40)
                print("! V32 failed: original configs and services restored")
                raise

if __name__=="__main__":
    try:main()
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as e:
        print("ОШИБКА:",str(e)[:1000],file=sys.stderr)
        sys.exit(1)
