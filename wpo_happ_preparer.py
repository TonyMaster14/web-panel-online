#!/usr/bin/env python3
"""WPO controller proactive provisioning of real remote VPN identities.

Runs as a bounded one-shot service outside the Happ HTTP request. Existing
subscriber IDs/credentials are preserved, including the first preallocated
device on a newly created multi-node subscription. Records only *readiness*
timestamps, never remote VLESS/Hysteria secrets. Uses authenticated Node API
and verifies every returned link before marking its selected node ready.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

APP=Path("/opt/tproxy-panel")
sys.path.insert(0,str(APP))
import wpp_nodes as api
import wpo_happ_async_feed as feed

USERS=Path("/etc/web-proxy-panel/users.json")
NODES=Path("/var/lib/tproxy-panel/nodes.json")
READY=Path("/var/lib/tproxy-panel/happ-node-ready.json")
RECHECK_AFTER=12*3600
MAX_IDENTITIES=2000

def domain():
    result=subprocess.run(["systemctl","show","-p","Environment","--value",
                           "tproxy-panel.service"],capture_output=True,text=True,
                          timeout=10,check=True)
    for item in shlex.split(result.stdout):
        if item.startswith("WEBPROXY_DOMAIN="):
            value=item.split("=",1)[1].strip().lower()
            if re.fullmatch(r"[a-z0-9.-]{3,253}",value) and "." in value:
                return value
    raise ValueError("Основной домен WPO не найден")

def load_state():
    try:
        data=json.loads(READY.read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError,ValueError,UnicodeError):
        return {}

def save_state(record):
    READY.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=str(READY.parent),prefix=".happ-ready-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(record,out,separators=(",",":"))
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,READY)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def tasks():
    name=domain()
    data=json.loads(USERS.read_text(encoding="utf-8"))
    subs=data.get("subscriptions",[]) if isinstance(data,dict) else []
    nodes={str(n.get("id","")):n for n in api.load_nodes(NODES)}
    jobs=[]
    if not isinstance(subs,list):
        raise ValueError("Повреждён реестр подписок")
    for sub in subs:
        if (not isinstance(sub,dict) or not sub.get("enabled",True)
                or not isinstance(sub.get("node_ids"),list)):
            continue
        chosen=sub["node_ids"]
        if not any(uid!="local" for uid in chosen):
            continue
        if any(uid!="local" and uid not in nodes for uid in chosen):
            print("! У подписки выбрана отсутствующая нода",flush=True)
            continue
        connections=sub.get("connections",[])
        protocols=tuple(dict.fromkeys(c.get("protocol") for c in connections
            if isinstance(c,dict) and c.get("protocol") in ("vless","hysteria")))
        if not protocols:
            continue
        devices=sub.get("devices",[])
        if not isinstance(devices,list):continue
        for device in devices:
            if (not isinstance(device,dict) or device.get("revoked")
                    or not re.fullmatch(r"[a-f0-9]{16}",str(device.get("id","")))):
                continue
            sid=str(sub.get("id",""))
            did=device["id"]
            if not re.fullmatch(r"[a-f0-9]{16}",sid):
                continue
            ext=hashlib.sha256((name+":"+sid+":"+did).encode()).hexdigest()
            for uid in chosen:
                if uid=="local":continue
                node=nodes[uid]
                if not node.get("enabled",True):continue
                digest=hashlib.sha256(
                    (ext+":"+uid+":"+str(node.get("url",""))+":"+",".join(protocols)).encode()
                ).hexdigest()
                jobs.append((digest,node,ext,api.location_prefix(node),protocols))
                if len(jobs)>MAX_IDENTITIES:
                    raise ValueError("Слишком много профилей для одновременной подготовки")
    return jobs

def prepare():
    current=load_state()
    jobs=tasks()
    now=int(time.time())
    due=[job for job in jobs if now-int(current.get(job[0],0) or 0)>=RECHECK_AFTER]
    # Remove stale cache for deleted/rotated subscriptions or removed nodes.
    active={j[0] for j in jobs}
    current={key:value for key,value in current.items()
             if key in active and isinstance(value,int)}
    if not due:
        print("✓ Дополнительные VPN-профили уже подготовлены:",len(jobs),flush=True)
        save_state(current)
        return True
    print("Подготавливаю VPN-профили:",len(due),
          "на выбранных дополнительных нодах, не блокируя Happ",flush=True)
    def one(job):
        key,node,ext,label,protocols=job
        started=time.monotonic()
        try:
            links=feed.verified_links(api,node,ext,label,protocols,timeout=90)
            return key,node,True,len(links),time.monotonic()-started
        except Exception as exc:
            # Do not print raw remote messages, tokens or credential-bearing URIs.
            code=getattr(getattr(exc,"__cause__",None),"code",None)
            status=("HTTP "+str(code)) if isinstance(code,int) else type(exc).__name__
            return key,node,False,status,time.monotonic()-started
    passed=True
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for key,node,good,detail,elapsed in pool.map(one,due):
            hostname=node.get("url","unknown-node").split("://")[-1][:120]
            if good:
                current[key]=int(time.time())
                print("✓",hostname,":",detail,"VPN-профиль(я),",round(elapsed,2),"с",flush=True)
            else:
                passed=False
                print("✗",hostname,":",detail,",",round(elapsed,2),"с",flush=True)
    save_state(current)
    if passed:
        print("✓ Все выбранные удалённые VPN-профили проверены и сохранены на нодах.",flush=True)
    else:
        print("! Не все ноды создали профиль. WPO повторит подготовку без потери ключей.",flush=True)
    return passed

if __name__=="__main__":
    try:
        sys.exit(0 if prepare() else 6)
    except (OSError,RuntimeError,ValueError,TypeError,subprocess.SubprocessError) as exc:
        print("Подготовка нод остановлена:",type(exc).__name__,file=sys.stderr)
        sys.exit(6)
