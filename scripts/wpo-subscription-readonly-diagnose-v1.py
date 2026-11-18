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
    print("=== READ-ONLY REALITY CLIENT MIRROR TEST ===")
    try:
        import sys
        sys.path.insert(0,"/opt/wpp-node-agent")
        import wpo_node_vpn as vpn
        import wpo_real443_bridge as bridge
        local=vpn.read_json(vpn.STATE,{"profiles":{}}).get("profiles",{})
        if not isinstance(local,dict):raise ValueError("registry invalid")
        canonical=vpn.render_xray(local,vpn.read_json(vpn.SETTINGS))
        current=read_json(Path("/etc/wpo-reality-remna-test/xray.json"))
        candidate=bridge.mirror_config(canonical,current)
        print("MIRROR compatible",True,"clients_already_equal",candidate==current)
    except Exception as exc:
        # Only type and known static categories; never print arbitrary exception
        # text that might contain a token, UUID or internal path.
        category="other"
        msg=str(exc)
        if "key/Short ID mismatch" in msg:category="key_shortid_mismatch"
        elif "no longer the tested" in msg:category="canary_structure_mismatch"
        elif "Expected exactly one source" in msg:category="inbound_count_mismatch"
        elif "client" in msg.lower():category="client_validation"
        elif "reality" in msg.lower():category="reality_config_error"
        print("MIRROR compatible",False,"category",category,
              "exception",type(exc).__name__)
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
          "--since","-120min","--no-pager","-o","cat",timeout=12)
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

def traceback_summary(text):
    """Retain exception classes, HTTP codes and stack *function names* only.

    Never emit traceback source lines, URLs, input values, credential strings,
    UUIDs, subscription IDs, domains or raw exception messages.
    """
    blocks=[]
    lines=text.splitlines()
    i=0
    while i<len(lines):
        if "Traceback (most recent call last)" not in lines[i]:
            i+=1;continue
        frames=[]
        classes=[]
        i+=1
        while i<len(lines):
            line=lines[i]
            frame=re.search(r'File "[^"]+", line \d+, in ([a-zA-Z_][a-zA-Z0-9_]{0,80})',line)
            exc=re.match(r'^([a-zA-Z_][a-zA-Z0-9_.]{0,100}(?:Error|Exception|Interrupt))\s*:',line)
            if frame:frames.append(frame.group(1))
            if exc:
                classes.append(exc.group(1))
                i+=1
                break
            if "Traceback (most recent call last)" in line:
                break
            i+=1
        blocks.append({"functions":frames[-8:],"exception":classes[-1] if classes else "not-shown"})
    return blocks[-6:]


def panel():
    print("=== PANEL ===")
    unit_status(UNITS_PANEL)
    path=Path("/opt/tproxy-panel/wpo_happ_async_feed.py")
    print("ASYNC FEED present",present(path))
    p=run("journalctl","-u","tproxy-panel.service","--since","-120min",
          "-o","cat","--no-pager",timeout=14)
    if p:
        classes=[]
        for line in p.stdout.splitlines():
            if "wpo asynchronous node sync failed" in line:
                # The writer logs only safe exception type and opaque node ID,
                # suppress all other fields including the opaque ID.
                m=re.search(r'\s(NodeError|RuntimeError|OSError|ValueError|TypeError|TimeoutError|HTTPError)\b',line)
                classes.append(m.group(1) if m else "sync-failed")
            if "Подписка готовится" in line:classes.append("subscription-preparing")
        print("Recent subscription events",json.dumps(classes[-45:],ensure_ascii=False))
        print("SANITIZED_TRACEBACKS",json.dumps(traceback_summary(p.stdout),ensure_ascii=False))
        status_codes=re.findall(r'(?i)\b(?:HTTP Error|HTTP status|HTTP)\s*[:]?\s*(40[0-9]|50[0-9])\b',p.stdout)
        print("Recent HTTP error codes",",".join(status_codes[-24:]) or "none")
    print("=== NODE READINESS FROM PANEL (GET ONLY) ===")
    try:
        import sys
        sys.path.insert(0,"/opt/tproxy-panel")
        import wpp_nodes as api
        nodes=api.load_nodes(Path("/var/lib/tproxy-panel/nodes.json"))
        print("Registered nodes",len(nodes))
        for index,node in enumerate(nodes,1):
            if not isinstance(node,dict):continue
            cc=str(node.get("country_code","UN"))
            cc=cc if re.fullmatch(r"[A-Z]{2}",cc) else "UN"
            enabled=bool(node.get("enabled",True))
            print("NODE",index,"country",cc,"enabled",enabled)
            if not enabled:continue
            for suffix in ("/status","/federation/status"):
                try:
                    reply=api.request(node,"GET",api.API_PREFIX+suffix,timeout=7)
                    caps=reply.get("capabilities",[])
                    caps=([v for v in caps if v in
                       ("federation","reality","vless","hysteria","reality-direct-443")]
                       if isinstance(caps,list) else [])
                    print(" ",suffix,"HTTP 200","ok",reply.get("ok"),"vpn_caps",",".join(caps))
                except Exception as exc:
                    cause=getattr(exc,"__cause__",None)
                    code=getattr(cause,"code",None)
                    print(" ",suffix,"FAILED",type(exc).__name__,
                          "http_code",code if isinstance(code,int) else "unknown")
    except Exception as exc:
        print("Node discovery failed:",type(exc).__name__)
    print("=== PREPARER SERVICE ===")
    p=run("systemctl","list-units","--all","--no-legend","--plain","wpo*happ*","*preparer*",timeout=7)
    if p:
        for line in p.stdout.splitlines()[:12]:
            unit=line.split()[0] if line.split() else ""
            if re.fullmatch(r"[a-zA-Z0-9_.@-]{3,80}\.(service|timer)",unit):
                print("PREPARER UNIT",unit)
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
