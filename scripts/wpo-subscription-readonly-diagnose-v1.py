#!/usr/bin/env python3
"""Read-only status diagnostics for WPO subscriptions (Sweden and panel).

No passwords, API keys, UUIDs, customer IDs, site links, URLs or Xray keys
printed or sent elsewhere. No subscriptions created; no files/services changed.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError

UNITS_NODE = (
    "wpo-reality-remna-xray-test.service",
    "wpo-reality-remna-nginx-test.service",
    "wpo-node-xray.service",
    "wpo-node-vpn.service",
    "wpp-node-agent.service",
    "caddy.service",
    "wpo-tls-router.service",
)
UNITS_PANEL=("tproxy-panel.service",)

def run(*args,timeout=8):
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):
        return None

def unit_status(units):
    for name in units:
        p=run("systemctl","is-active",name,timeout=4)
        state=(p.stdout.strip() if p else "unknown")
        print("UNIT",name,state if state in ("active","inactive","failed","activating","deactivating") else "other")

def present(path):
    return path.is_file() and not path.is_symlink()

def read_json(path):
    if not present(path):return {}
    try:
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,UnicodeError,ValueError):
        return {}

def listener(port):
    p=run("ss","-H","-lnt",timeout=4)
    if not p:return "unknown"
    return "yes" if any(re.search(r":%d\s"%port,line) for line in p.stdout.splitlines()) else "no"

def node():
    print("=== NODE SERVICES ===")
    unit_status(UNITS_NODE)
    print("LISTEN 443",listener(443))
    print("LISTEN 9088",listener(9088))
    print("LISTEN 9089",listener(9089))
    print("LISTEN 19000",listener(19000))
    print("=== MANAGED REALITY ===")
    marker=Path("/etc/wpo-reality-remna-test/managed.json")
    state=Path("/root/wpo-sweden-real443-managed-v1-state.json")
    switch=Path("/etc/wpo-reality-remna-test/switch-443-state.json")
    print("MARKER present",present(marker),"state present",present(state),
          "confirmed-switch present",present(switch))
    if present(marker):
        m=read_json(marker)
        print("MARKER mode recognized",m.get("mode")=="remna-443-mirror-v1",
              "Sweden domain recognized",m.get("domain")=="swejeep.goodarielservice.xyz")
    agent=Path("/opt/wpp-node-agent/wpo_node_vpn.py")
    api=Path("/opt/wpp-node-agent/agent.py")
    bridge=Path("/opt/wpp-node-agent/wpo_real443_bridge.py")
    print("NODE MODULES", {k:present(v) for k,v in
          (("vpn",agent),("site_agent",api),("bridge",bridge))})
    if present(agent):
        src=agent.read_text(encoding="utf-8")
        print("NODE VPN bridge hook", "wpo_real443_bridge.install(globals())" in src)
    if present(api):
        print("NODE API status hook","WPO_REAL443_SITE_STATUS_V1" in api.read_text(encoding="utf-8"))
    print("=== XRAY CONFIG COUNTS (never print identities) ===")
    for label,path in (
        ("canonical",Path("/etc/wpp-node-vpn/xray.json")),
        ("direct443",Path("/etc/wpo-reality-remna-test/xray.json"))):
        cfg=read_json(path)
        inbound=cfg.get("inbounds",[])
        if not isinstance(inbound,list):inbound=[]
        summary=[]
        for i in inbound:
            if not isinstance(i,dict):continue
            mode=i.get("streamSettings",{}).get("security","none")
            settings=i.get("settings",{})
            clients=settings.get("clients",[])
            count=len(clients) if isinstance(clients,list) else "invalid"
            summary.append({"protocol":str(i.get("protocol","unknown"))[:16],
                            "port":i.get("port"),"tls":str(mode)[:15],
                            "clients":count})
        print(label,json.dumps(summary,ensure_ascii=False))
    print("=== READ-ONLY LOCAL AUTHENTICATED API ===")
    config=read_json(Path("/etc/wpp-node-agent/config.json"))
    key=config.get("api_key")
    if not isinstance(key,str) or not key:
        print("API key present false")
        return
    opener=build_opener(ProxyHandler({}))
    for port,path in (
        (9088,"/wpp-api/v1/status"),
        (9089,"/wpp-api/v1/federation/status"),
        (9089,"/wpp-api/v1/federation/reality")):
        req=Request("http://127.0.0.1:"+str(port)+path,
                    headers={"Authorization":"Bearer "+key,"Accept":"application/json"})
        label=str(port)+path
        try:
            with opener.open(req,timeout=5) as resp:
                code=resp.status
                data=json.loads(resp.read(30000))
            print("API",label,"HTTP",code,"ok",data.get("ok"),
                  "capabilities",",".join(x for x in data.get("capabilities",[])
                                          if isinstance(x,str))[:150] if isinstance(data.get("capabilities"),list) else "—",
                  "managed",data.get("profile",{}).get("managed_reality","no")
                    if isinstance(data.get("profile"),dict) else "no")
        except HTTPError as exc:
            print("API",label,"HTTP",exc.code)
        except (OSError,ValueError,URLError) as exc:
            print("API",label,"error",type(exc).__name__)
    print("=== SANITIZED RECENT NODE ERRORS ===")
    p=run("journalctl","-u","wpo-node-vpn.service","-u","wpo-node-xray.service",
          "--since","-45min","--no-pager","-o","cat",timeout=12)
    if p:
        lines=p.stdout.splitlines()
        kept=[]
        patterns=("VPN provisioning failed","Xray configuration validation failed",
                  "Xray did not become ready","Exception","Traceback","Error",
                  "failed","permission denied","permission")
        for line in lines:
            if any(q.lower() in line.lower() for q in patterns):
                # Intentionally do not emit any source line. Emit category only.
                detected=next((q for q in patterns if q.lower() in line.lower()),"unknown")
                kept.append(detected)
        print("Recent categories:",json.dumps(kept[-25:],ensure_ascii=False))
    print("=== END READ ONLY ===")

def panel():
    print("=== PANEL ===")
    unit_status(UNITS_PANEL)
    path=Path("/opt/tproxy-panel/wpo_happ_async_feed.py")
    print("ASYNC FEED present",present(path))
    try:
        p=run("journalctl","-u","tproxy-panel.service","--since","-45min",
              "-o","cat","--no-pager",timeout=14)
        if p:
            classes=[]
            for line in p.stdout.splitlines():
                if "wpo asynchronous node sync failed" in line:
                    m=re.search(r" (NodeError|RuntimeError|OSError|ValueError|TypeError|TimeoutError|HTTPError|[A-Za-z]+Error)\b",line)
                    classes.append(m.group(1) if m else "sync-failed")
                if "Подписка готовится" in line:classes.append("subscription-preparing")
                if "Traceback" in line:classes.append("traceback")
            print("Recent subscription events",json.dumps(classes[-50:],ensure_ascii=False))
    except Exception as exc:
        print("LOG",type(exc).__name__)
    print("=== END READ ONLY ===")

if __name__=="__main__":
    import os
    if os.geteuid()!=0:raise SystemExit("Need root")
    if Path("/etc/wpp-node-vpn/settings.json").is_file():
        node()
    elif Path("/opt/tproxy-panel/panel.py").is_file():
        panel()
    else:
        raise SystemExit("Unknown WPO host: no changes made")
