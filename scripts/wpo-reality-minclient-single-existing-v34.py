#!/usr/bin/env python3
"""WPO V34: persist minClientVer=1.0.0 on already-single REALITY nodes.

Test branch only. Safe compatibility repair for a node whose REALITY generator
already emits one inbound (V32's 4->1 source anchor is absent). Only modifies
wpo_reality.py and Xray JSON after proof that the candidate differs from live
config exclusively by REALITY minClientVer. Never touches HAProxy, SNI, TLS,
API tokens, profiles, private keys, ports, Hysteria2 or other inbounds.
--check is read-only. --apply takes backups, validates Xray, restarts services
and rolls files back on failure. Run on additional VPN nodes, NOT main panel.
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

APP = Path("/opt/wpp-node-agent")
SOURCE = APP / "wpo_reality.py"
CONFIG = Path("/etc/wpp-node-vpn/xray.json")
LOCK = Path("/etc/wpp-node-vpn/.federation.lock")
XRAY = Path("/opt/web-panel-proxy/xray/xray")
BACKUPS = Path("/var/backups/web-panel-online")
MARK = "# WPO_REALITY_MINCLIENT_V34"
WRAPPER = '''
# WPO_REALITY_MINCLIENT_V34
_wpo_minclient_original_inbounds = inbounds
def inbounds(clients, profile=None):
    result = _wpo_minclient_original_inbounds(clients, profile)
    for entry in result:
        if (entry.get("protocol") == "vless" and
                entry.get("streamSettings", {}).get("security") == "reality"):
            entry["streamSettings"]["realitySettings"]["minClientVer"] = "1.0.0"
    return result
'''
GENERATION = r'''
import copy, importlib.util, json, sys
from pathlib import Path
sys.path.insert(0, "/opt/wpp-node-agent")
import wpo_node_vpn as vpn
spec = importlib.util.spec_from_file_location("wpo_reality_minclient_preview", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
vpn.wpo_reality = module
state = vpn.read_json(vpn.STATE, {"profiles": {}})["profiles"]
settings = vpn.read_json(vpn.SETTINGS)
future = vpn.render_xray(state, settings)
current = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
def reality(obj):
    return (isinstance(obj, dict) and obj.get("protocol") == "vless" and
            obj.get("streamSettings", {}).get("security") == "reality")
before = [i for i in current.get("inbounds", []) if reality(i)]
after = [i for i in future.get("inbounds", []) if reality(i)]
if len(before) != 1 or len(after) != 1:
    raise RuntimeError("The node must have exactly one REALITY inbound already")
reference = copy.deepcopy(current)
for inbound in reference["inbounds"]:
    if reality(inbound):
        inbound["streamSettings"]["realitySettings"]["minClientVer"] = "1.0.0"
if future != reference:
    raise RuntimeError("Generated Xray differs beyond minClientVer; refusal to change any files")
if after[0]["streamSettings"]["realitySettings"]["minClientVer"] != "1.0.0":
    raise RuntimeError("minClientVer missing from generated config")
with open(sys.argv[3], "w", encoding="utf-8") as stream:
    json.dump(future, stream, ensure_ascii=False)
print("Valid: exactly one REALITY; all other Xray JSON fields identical")
'''


def run(*args,timeout=40):
    return subprocess.run(list(map(str,args)), capture_output=True,
                          text=True, timeout=timeout,check=False)


def is_active(name):
    return run("systemctl","is-active","--quiet",name,timeout=6).returncode==0


def valid_file(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Missing or symlink: "+str(path))
    return path.stat()


def is_reality(item):
    return (isinstance(item,dict) and item.get("protocol")=="vless" and
            item.get("streamSettings",{}).get("security")=="reality")


def atomic(path,data,oldstat):
    fd,temp=tempfile.mkstemp(prefix=".wpo-minclient-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chown(temp,oldstat.st_uid,oldstat.st_gid)
        os.chmod(temp,stat.S_IMODE(oldstat.st_mode))
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser=argparse.ArgumentParser(description="WPO V34 REALITY minClientVer on pre-single inbound nodes")
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--apply",action="store_true")
    options=parser.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError("sudo required")
    if (Path("/opt/tproxy-panel/panel.py").is_file() and
            is_active("tproxy-panel.service")):
        raise RuntimeError("Это основная панель. V34 только для дополнительных нод.")
    for unit in ("wpo-node-xray.service","wpo-node-vpn.service"):
        if not is_active(unit):
            raise RuntimeError("Node VPN/Xray service not active: "+unit)
    original_stats={f:valid_file(f) for f in (SOURCE,CONFIG)}
    valid_file(XRAY)
    current=json.loads(CONFIG.read_text(encoding="utf-8"))
    reality=[i for i in current.get("inbounds",[]) if is_reality(i)]
    if len(reality)!=1:
        raise RuntimeError("V34 applies only to nodes with exactly one REALITY inbound")
    rs=reality[0].get("streamSettings",{}).get("realitySettings",{})
    print("✓ Действующий REALITY: 1 inbound")
    print("✓ SNI:",", ".join(rs.get("serverNames",[])))
    print("✓ Xray port:",reality[0].get("port"))
    print("✓ minClientVer сейчас:",rs.get("minClientVer","(нет)"))
    before=SOURCE.read_text(encoding="utf-8")
    if MARK not in before and "def inbounds(" not in before:
        raise RuntimeError("Generator has no inbounds(): no changes")
    updated=before if MARK in before else before.rstrip()+"\n"+WRAPPER
    compile(updated,str(SOURCE),"exec")

    # This lock is also used for WPO node federation provisioning.
    LOCK.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(LOCK,"a+",encoding="ascii") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix=".wpo-minclient-v34-",dir=str(APP)) as workspace:
            folder=Path(workspace)
            preview=folder/"wpo_reality_minclient_preview.py"
            proposal=folder/"proposed-xray.json"
            preview.write_text(updated,encoding="utf-8")
            check=run(sys.executable,"-c",GENERATION,preview,CONFIG,proposal,timeout=40)
            if check.returncode:
                raise RuntimeError("Не удалось сохранить конфигурацию без других изменений: "+
                                   (check.stderr or check.stdout or "unknown")[-900:])
            print("✓",check.stdout.strip())
            test=run(XRAY,"run","-test","-config",proposal,timeout=30)
            if test.returncode:
                raise RuntimeError("Xray отклонил новый JSON; изменений нет: "+
                                   (test.stderr or test.stdout or "")[-700:])
            print("✓ Xray успешно проверил новый JSON")
            changed_source=(updated!=before)
            changed_config=(proposal.read_bytes()!=CONFIG.read_bytes())
            if not changed_source and not changed_config:
                print("✓ Всё уже установлено, изменений не требуется")
                return
            print("✓ Будут изменены:",", ".join(
                name for name,yes in (("генератор REALITY",changed_source),
                                      ("действующий Xray JSON",changed_config)) if yes))
            if options.check:
                print("✓ Только проверка: файлы и службы не изменены")
                return
            destination=BACKUPS/("reality-minclient-v34-"+
                                 datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            destination.mkdir(parents=True,mode=0o700,exist_ok=False)
            for path in (SOURCE,CONFIG):
                shutil.copy2(path,destination/path.name)
                os.chmod(destination/path.name,0o600)
            print("✓ Резервная копия:",destination)
            touched=[]
            try:
                if changed_source:
                    atomic(SOURCE,updated.encode("utf-8"),original_stats[SOURCE])
                    touched.append(SOURCE)
                if changed_config:
                    atomic(CONFIG,proposal.read_bytes(),original_stats[CONFIG])
                    touched.append(CONFIG)
                for unit in (("wpo-node-xray.service",) if changed_config else ()):
                    res=run("systemctl","restart",unit,timeout=40)
                    if res.returncode:raise RuntimeError("Не удалось перезапустить "+unit)
                if changed_source:
                    res=run("systemctl","restart","wpo-node-vpn.service",timeout=40)
                    if res.returncode:raise RuntimeError("Не удалось перезапустить Node Agent")
                for _ in range(12):
                    if all(is_active(x) for x in ("wpo-node-xray.service","wpo-node-vpn.service")):
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError("Службы не активны после обновления")
                final=json.loads(CONFIG.read_text(encoding="utf-8"))
                active_reality=[i for i in final["inbounds"] if is_reality(i)]
                if len(active_reality)!=1 or active_reality[0]["streamSettings"][
                    "realitySettings"].get("minClientVer")!="1.0.0":
                    raise RuntimeError("Xray JSON не сохранил minClientVer")
                print("✓ V34: REALITY=1, minClientVer 1.0.0, другие настройки сохранены")
                print("✓ Изменены только генератор и Xray JSON; HAProxy не менялся")
            except Exception:
                for path in touched:
                    atomic(path,(destination/path.name).read_bytes(),original_stats[path])
                for unit in ("wpo-node-xray.service","wpo-node-vpn.service"):
                    run("systemctl","restart",unit,timeout=40)
                print("! Ошибка применения: исходные файлы восстановлены")
                raise


if __name__=="__main__":
    try: main()
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as error:
        print("ОШИБКА:",str(error)[:1000],file=sys.stderr)
        sys.exit(1)
