#!/usr/bin/env python3
"""WPO isolated provisioning preflight for an existing Sweden REALITY node.

NO POST requests, NO mutation of existing users, Xray files, panel databases,
services or TLS. Build candidate configurations for hypothetical clients only
in a temporary directory, validate with Xray run -test, then discard.
This does not claim a successful runtime POST: it identifies compile/key errors.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit,parse_qs

AGENT=Path("/opt/wpp-node-agent")
CANARY=Path("/etc/wpo-reality-remna-test/xray.json")
MARKER=Path("/etc/wpo-reality-remna-test/managed.json")
XRAY=Path("/opt/web-panel-proxy/xray/xray")
DOMAIN="swejeep.goodarielservice.xyz"


def test_candidate(binary,cfg,tag):
    with tempfile.TemporaryDirectory(prefix="wpo-preflight-xray-") as d:
        p=Path(d)/"candidate.json"
        p.write_text(json.dumps(cfg,separators=(",",":")))
        proc=subprocess.run([str(binary),"run","-test","-config",str(p)],
                            text=True,capture_output=True,timeout=25)
        print(tag,"Xray config valid",proc.returncode==0)
        if proc.returncode:
            # Never print raw Xray output: it can include file names or keys.
            print(tag,"failure type","XrayConfigRejected")
        return proc.returncode==0


def main():
    sys.path.insert(0,str(AGENT))
    import wpo_node_vpn as vpn
    import wpo_node_eight as eight
    import wpo_real443_bridge as bridge

    settings=vpn.read_json(vpn.SETTINGS)
    if settings.get("domain")!=DOMAIN:
        raise RuntimeError("Run this only on Sweden")
    if not CANARY.is_file() or not MARKER.is_file():
        raise RuntimeError("Direct443 managed mode missing")
    if not bridge.enabled_for(DOMAIN):
        raise RuntimeError("Direct443 marker is not enabled")
    existing=vpn.read_json(vpn.STATE,{"profiles":{}}).get("profiles",{})
    if not isinstance(existing,dict):
        raise RuntimeError("Stored profiles damaged")
    current=json.loads(CANARY.read_text())
    baseline=vpn.render_xray(existing,settings)
    print("=== BASELINE ===")
    print("stored profiles",len(existing))
    print("canary mirror matches",bridge.mirror_config(baseline,current)==current)
    print("active protocols",",".join(sorted(eight.available() & {"reality","vless","hysteria"})))
    count=0
    for uid,record in existing.items():
        if not isinstance(record,dict):continue
        kinds=list(record.get("secrets",{})) + list(record.get("native",{}))
        if not kinds:continue
        try:
            simulated=eight.with_profile(existing,uid,record["name"],kinds)
        except (ValueError,TypeError,KeyError) as exc:
            print("existing profile no-op check",False,"category",type(exc).__name__)
            break
        if simulated==existing:
            count+=1
    print("existing identities with nonmutating re-sync",count)

    print("=== HYPOTHETICAL NEW CLIENTS (no persistence) ===")
    for kind in ("vless","reality","hysteria","vless+reality+hysteria"):
        protocols=kind.split("+")
        uid=secrets.token_hex(32)
        candidate_state=copy.deepcopy(existing)
        candidate_state[uid]={"name":"WPO preview","secrets":{p:str(uuid.uuid4()) for p in protocols}}
        try:
            canonical=vpn.render_xray(candidate_state,settings)
            canary=bridge.mirror_config(canonical,current)
            test_candidate(XRAY,canonical,kind+" base")
            test_candidate(XRAY,canary,kind+" direct443")
            target=(canonical.get("inbounds") or [])
            listeners=[i.get("port") for i in target if isinstance(i,dict)]
            print(kind,"expected XHTTP on 19000",19000 in listeners)
            # Test generated links without exposing IDs or secrets.
            for p in protocols:
                uri=vpn.link(p,candidate_state[uid]["secrets"][p],"Preview",settings)
                parsed=urlsplit(uri)
                qs=parse_qs(parsed.query)
                if parsed.hostname!=DOMAIN:
                    raise ValueError("link host mismatch")
                if p=="reality" and (qs.get("sni")!=[DOMAIN] or parsed.port!=443):
                    # The managed wrapper should use the established node SNI.
                    raise ValueError("REALITY SNI mismatch")
            print(kind,"generated link metadata valid",True)
        except Exception as exc:
            # Do not leak exception text or generated client credentials.
            print(kind,"preview failed",type(exc).__name__)
    print("=== END: NO CHANGES ===")

if __name__=="__main__":
    import os
    if os.geteuid()!=0:raise SystemExit("Requires root")
    main()
