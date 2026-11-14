#!/usr/bin/env python3
"""Reserve the FIRST subscription device's real federation identity at creation.

Only subscriptions explicitly selecting remote nodes are affected. No change to
existing subscriptions, unlimited/shared semantics, token rotation, HWID
limits, or revocation. The first real Happ X-HWID safely claims the reserved
slot, retaining the pre-provisioned per-device Xray credentials.
"""
import argparse
import ast
from pathlib import Path

CREATE_ANCHOR="        accounts(data).append(sub)\n"
ISSUE_ANCHOR="    if device is None:\n        active = sum(not d.get('revoked') for d in sub['devices'])\n"
REV_ANCHOR="            drop_profiles(data, sub['id'])\n        elif operation in ('revoke', 'allow', 'rename-device'):\n"
MARKER="# wpo-happ-preregister-first-device-v1"

HELPER='''def preallocate_first_remote_device(data, sub):
    """Create only one stable slot before the first Happ fetch."""
    if not any(uid != "local" for uid in sub.get("node_ids", ["local"])):
        return
    if sub.get("devices"):
        return
    did = secrets.token_hex(8)
    limited = bool(sub.get("max_devices", 0))
    device = {
        "id": did,
        "hwid_hash": "wpo-pending-" + did if limited else "shared",
        "name": "Ожидает Happ" if limited else "Общий профиль",
        "created_at": int(time.time()),
        "last_seen": 0,
        "revoked": False,
    }
    if limited:
        device["preallocated"] = True
    sub["devices"].append(device)
    provision(data, sub, device)


'''

ISSUE_REPLACE='''    if device is None:
        # wpo-happ-preregister-first-device-v1: the first HWID claims the
        # pre-provisioned, unbound slot. Its keys were created at subscription
        # creation and are already being installed on selected remote nodes.
        reserved = next((d for d in sub["devices"]
                         if d.get("preallocated") and not d.get("revoked")), None)
        active = sum(not d.get('revoked') and not d.get("preallocated")
                     for d in sub['devices'])
        if sub['max_devices'] and active >= sub['max_devices']:
            raise SubscriptionError('Лимит устройств исчерпан. Обратитесь к администратору.', 403, 'device_limit')
        if reserved is not None:
            device = reserved
            device["hwid_hash"] = digest
            device.pop("preallocated", None)
            device["name"] = suggested if (suggested := str(request.get("device_name", "")).strip())
                and len(suggested) <= 40 and not any(ord(c) < 32 for c in suggested)
                else "Устройство " + device["id"][:6]
            for user in data["users"]:
                if user.get("subscription_id") == sub["id"] and user.get("device_id") == device["id"]:
                    user["name"] = sub["name"] + " / " + device["name"]
        else:
            if len(sub['devices']) >= 100:
                raise SubscriptionError('Нужна ротация подписки: слишком много отозванных устройств.', 403, 'device_limit')
            did = secrets.token_hex(8)
            suggested = str(request.get('device_name','')).strip()
            if not suggested or len(suggested)>40 or any(ord(c)<32 for c in suggested):
                suggested='Устройство ' + did[:6]
            device = {'id': did, 'hwid_hash': digest,
                      'name': 'Общий профиль' if digest == 'shared' else suggested,
                      'created_at': int(time.time()), 'last_seen': 0, 'revoked': False}
            sub['devices'].append(device)
            provision(data, sub, device)
'''

def patch(source):
    if MARKER in source:
        ast.parse(source)
        return source
    if "def clean_node_ids(value):" not in source:
        raise ValueError("Must first install WPO saved node selection")
    for anchor in (CREATE_ANCHOR,ISSUE_ANCHOR,REV_ANCHOR):
        if source.count(anchor)!=1:
            raise ValueError("WPO subscription source changed, refusing unsafe patch")
    source=source.replace("def mutate(data, request):",HELPER+"def mutate(data, request):",1)
    source=source.replace(CREATE_ANCHOR,CREATE_ANCHOR+"        preallocate_first_remote_device(data, sub)\n",1)
    # The reserved device is only added on new account creation. On rotation,
    # generate a new slot; this is a token rotation and keys are intended to change.
    source=source.replace(REV_ANCHOR,REV_ANCHOR.replace("        elif operation", "            preallocate_first_remote_device(data, sub)\n        elif operation"),1)
    start=source.index(ISSUE_ANCHOR)
    end=source.index("    device['last_seen'] = int(time.time())",start)
    old=source[start:end]
    if "provision(data, sub, device)" not in old or "sub['devices'].append(device)" not in old:
        raise ValueError("Unknown issue path")
    source=source[:start]+ISSUE_REPLACE+source[end:]
    ast.parse(source,filename="wpp_subscriptions.py")
    return source

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    a.output.write_text(patch(a.input.read_text()),encoding="utf-8")
    print("✓ Новые многонодовые подписки заранее резервируют первый профиль Happ")
    print("✓ Первое устройство получит уже созданные ключи; другие подписки не изменены")

if __name__=="__main__":
    main()
