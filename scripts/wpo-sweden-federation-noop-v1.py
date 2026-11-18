#!/usr/bin/env python3
"""Read-preserving localhost federation smoke test for existing Swedish identity.

This does ONE POST using the SAME external_id, name, protocol set and UUIDs
already saved on the node. First prove that wpo_node_eight.with_profile()
returns exactly the existing state. If not, refuse to send POST. No new client,
no token rotation, no deletion. Compare config, registry hashes and service
timestamps before/after; show only HTTP status and validation categories.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import urllib.request
import urllib.error
from urllib.parse import urlsplit

DOMAIN="swejeep.goodarielservice.xyz"
ROOT=Path("/opt/wpp-node-agent")
sys.path.insert(0,str(ROOT))
CANARY=Path("/etc/wpo-reality-remna-test/xray.json")


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def systemd(pid):
    p=subprocess.run(["systemctl","show",pid,"--property=MainPID,ExecMainStartTimestampMonotonic",
                      "--no-pager"],capture_output=True,text=True,timeout=5)
    return tuple(sorted(p.stdout.splitlines()))


def main():
    if os.geteuid()!=0:raise RuntimeError("Root required")
    import wpo_node_vpn as vpn
    import wpo_node_eight as eight
    import wpo_real443_bridge as bridge
    settings=vpn.read_json(vpn.SETTINGS)
    if settings.get("domain")!=DOMAIN or not bridge.enabled_for(DOMAIN):
        raise RuntimeError("Only managed Sweden node supported")
    path=vpn.STATE
    if not path.is_file() or not CANARY.is_file():
        raise RuntimeError("Node registry or canary absent")
    state_before=hash_file(path)
    xray_before=hash_file(vpn.XRAY)
    canary_before=hash_file(CANARY)
    unit_before=(systemd(vpn.UNIT),systemd(bridge.SERVICE))
    profiles=vpn.read_json(path,{"profiles":{}}).get("profiles",{})
    if not isinstance(profiles,dict):
        raise RuntimeError("Invalid node profile state")
    candidate=None
    for ext,entry in profiles.items():
        if (not re.fullmatch(r"[a-f0-9]{64}",str(ext)) or
            not isinstance(entry,dict) or not isinstance(entry.get("name"),str)):
            continue
        choices=list(entry.get("secrets",{}))+list(entry.get("native",{}))
        if not choices:continue
        if len(set(choices))!=len(choices):continue
        # Proven exact no-op: neither Xray nor registry must change.
        if eight.with_profile(profiles,ext,entry["name"],choices)!=profiles:
            continue
        candidate=(ext,entry["name"],choices)
        break
    if candidate is None:
        print("NO SAFE NO-OP PROFILE: request skipped. No changes.")
        return
    ext,name,choices=candidate
    print("Preflight unchanged profile",True,"protocol_count",len(choices))
    config=vpn.read_json(vpn.NODE_CONFIG)
    token=config.get("api_key")
    if not isinstance(token,str) or len(token)<32:
        raise RuntimeError("Node token missing")
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request=urllib.request.Request(
        "http://127.0.0.1:9089/wpp-api/v1/federation/sync",
        data=json.dumps({"external_id":ext,"name":name,"protocols":choices}).encode(),
        method="POST",
        headers={"Authorization":"Bearer "+token,
                 "Accept":"application/json","Content-Type":"application/json"})
    try:
        with opener.open(request,timeout=25) as response:
            raw=response.read(65536)
            status=response.status
        result=json.loads(raw)
        links=result.get("profiles",[]) if isinstance(result,dict) else []
        types=[p.get("protocol") for p in links if isinstance(p,dict)]
        domains_match=all(
            urlsplit(p.get("link","")).hostname==DOMAIN
            for p in links if isinstance(p,dict) and isinstance(p.get("link"),str)
        )
        print("POST /federation/sync HTTP",status,
              "ok",result.get("ok") if isinstance(result,dict) else False,
              "link_count",len(links),"protocols_match",set(types)==set(choices),
              "domain_matches",domains_match)
    except urllib.error.HTTPError as exc:
        # Read the response but emit only an allowlisted category (not body,
        # paths, UUIDs or user input). The server may return a detailed error.
        try:
            answer=json.loads(exc.read(2048))
            msg=str(answer.get("message","")) if isinstance(answer,dict) else ""
        except (ValueError,UnicodeError,OSError):
            msg=""
        category="other"
        for label,needle in (
            ("runtime_xray","Xray did not become ready"),
            ("xray_validation","Xray configuration validation failed"),
            ("vpn_provision","VPN provisioning failed"),
            ("node_not_ready","VPN service is not ready"),
            ("protocol_not_ready","Node protocols not ready"),
            ("invalid_id","Invalid federation ID"),
            ("invalid_protocol","Invalid node protocol selection"),
            ("unknown","Unauthorized"),
        ):
            if needle.lower() in msg.lower():
                category=label;break
        print("POST /federation/sync HTTP",exc.code,"category",category,
              "(response redacted)")
    except (OSError,ValueError) as exc:
        print("POST error",type(exc).__name__)
    finally:
        print("Registry unchanged",hash_file(path)==state_before)
        print("Canonical Xray config unchanged",hash_file(vpn.XRAY)==xray_before)
        print("REALITY443 Xray config unchanged",hash_file(CANARY)==canary_before)
        print("Xray processes not restarted",
              (systemd(vpn.UNIT),systemd(bridge.SERVICE))==unit_before)

if __name__=="__main__":
    main()
