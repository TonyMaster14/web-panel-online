#!/usr/bin/env python3
"""WPO main controller: persist selected nodes before provisioning them.

Real remote VPN federation is intentionally asynchronous. The create handler
must not block a valid subscription on GET /federation/status: selected server
profiles are actually provisioned and validated by the separate preparer.
A server is never counted in Happ until its real links are verified.
"""
import argparse
import ast
from pathlib import Path

MARKER="# wpo-happ-queue-create-v2:"

OLD='''                # wpo-federation-live-create-v1: verify real VPN sidecars, not
                # potentially stale Node Agent capabilities from /status.
                registered=node_api.load_nodes(NODES_FILE)
                available_nodes={str(n.get("id","")): n for n in registered}
                remote_ids=[uid for uid in chosen_nodes if uid!="local"]
                if any(uid not in available_nodes for uid in remote_ids):
                    create_error("Выбранная VPN-нода удалена. Обновите список нод.",409); return
                wanted_protocols={str(item.get("protocol","")) for item in connection_specs}
                unavailable=[]
                for uid in remote_ids:
                    node=available_nodes[uid]
                    if not node.get("enabled",True):
                        unavailable.append(uid)
                        continue
                    try:
                        # This is the authenticated, live federation sidecar.
                        status=node_api.request(node,"GET",
                            node_api.API_PREFIX+"/federation/status",timeout=7)
                        caps=set(status.get("capabilities",[]))
                        if not status.get("ok") or "federation" not in caps or not wanted_protocols.issubset(caps):
                            unavailable.append(uid)
                    except node_api.NodeError:
                        unavailable.append(uid)
                if unavailable:
                    create_error("VPN Federation не готова на одной из выбранных нод. Проверьте Xray и состояние VPN-службы. Подписка не создана.",503); return'''

NEW='''                # wpo-happ-queue-create-v2: save valid selection immediately.
                # Remote capability probing/provisioning belongs to preparer,
                # not the admin create request. The Happ feed includes ONLY
                # authenticated, verified live VPN links, never fake profiles.
                registered=node_api.load_nodes(NODES_FILE)
                available_nodes={str(n.get("id","")): n for n in registered}
                remote_ids=[uid for uid in chosen_nodes if uid!="local"]
                if any(uid not in available_nodes for uid in remote_ids):
                    create_error("Выбранная VPN-нода удалена. Обновите список нод.",409); return
                if any(not available_nodes[uid].get("enabled",True) for uid in remote_ids):
                    create_error("Выбрана отключённая нода. Включите её в разделе Ноды.",409); return
                wanted_protocols={str(item.get("protocol","")) for item in connection_specs}
                if remote_ids and (not wanted_protocols or
                                   not wanted_protocols.issubset({"vless","hysteria"})):
                    create_error("Дополнительные ноды доступны для подписки VLESS/Hysteria2.",409); return
                # No network here: an unreachable remote must not block account
                # creation. The pre-provisioner runs after ctl_subscription()
                # commits; later Happ refresh adds only verified profiles.'''

def patch(source):
    if MARKER in source:
        ast.parse(source,filename="panel.py")
        return source
    if source.count(OLD)!=1:
        raise ValueError("Expected previously installed live-federation gate not found; no changes")
    # Creation must have an existing async feed & after-create prewarm hook.
    for required in ("# wpo-happ-fast-feed-v1:",
                     "wpo-happ-prewarm-on-create-v2:",
                     "len(distinct_nodes)>1",
                     "wpo_happ_async_feed.enqueue("):
        if required not in source:
            raise ValueError("Missing asynchronous Happ dependency: "+required)
    updated=source.replace(OLD,NEW,1)
    ast.parse(updated,filename="panel.py")
    return updated

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    opts=p.parse_args()
    opts.output.write_text(patch(opts.input.read_text(encoding="utf-8")),encoding="utf-8")
    print("✓ Создание подписки больше не зависит от готовности удалённого VPN")
    print("✓ В Happ будут только реально подготовленные VLESS/Hysteria2-профили")
    print("✓ Отсутствующие и отключённые ноды по-прежнему блокируются")

if __name__=="__main__":
    main()
