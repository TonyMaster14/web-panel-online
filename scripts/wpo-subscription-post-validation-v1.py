#!/usr/bin/env python3
"""Test WPO node federation POST transport with a guaranteed invalid ID.

The invalid external_id is rejected by valid_params() BEFORE registry writes,
Xray reconfig or user creation. This is a negative (HTTP 400) API probe, not a
subscription creation. Run on controller. It does NOT modify nodes.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

APP="/opt/tproxy-panel"
sys.path.insert(0,APP)
import wpp_nodes as api

NODES=Path("/var/lib/tproxy-panel/nodes.json")
VALID_CODES={400:"request reached validation (expected, no changes)",
             401:"API credentials rejected",403:"forbidden",
             404:"route missing",409:"server refused",
             429:"throttled",500:"node internal error",
             502:"upstream gateway",503:"node service not ready",
             504:"node timeout"}

def main():
    nodes=api.load_nodes(str(NODES))
    print("=== NONMUTATING INVALID-ID POST PROBE ===")
    for pos,node in enumerate(nodes,1):
        if not isinstance(node,dict) or not node.get("enabled",True):continue
        cc=str(node.get("country_code","UN"))[:2]
        print("NODE",pos,"country",cc)
        try:
            # Deliberately invalid hex ID: node validation must reject it
            # before any stateful provisioning or creating user secrets.
            api.request(node,"POST",api.API_PREFIX+"/federation/sync",{
                "external_id":"INVALID_DIAGNOSTIC_ID",
                "name":"Validation probe",
                "protocols":["reality"]
            },timeout=10)
            print("  UNEXPECTED SUCCESS: do not continue testing")
        except api.NodeError as exc:
            cause=exc.__cause__
            code=getattr(cause,"code",None)
            print("  HTTP",code if isinstance(code,int) else "unknown",
                  VALID_CODES.get(code,"unclassified"))
        except Exception as exc:
            print("  ERROR",type(exc).__name__)
    print("=== END: zero valid subscriptions submitted ===")
if __name__=="__main__":
    import os
    if os.geteuid()!=0:raise SystemExit("Requires root")
    main()
