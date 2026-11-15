#!/usr/bin/env python3
"""Main-WPO only: consult live VPN Federation status when creating a user.

The lightweight Node Agent /status may advertise a stale/missing capability
snapshot although the authenticated VPN sidecar is already available. Never
pretend a remote node is ready: require its actual /federation/status answer.
"""
import argparse
import ast
from pathlib import Path

MARKER = "# wpo-federation-live-create-v1"

BEFORE = '''                # wpo-vpn-controller-v27: no phantom remote connections
                registered=node_api.load_nodes(NODES_FILE)
                wanted_protocols={str(item.get("protocol","")) for item in connection_specs}
                unavailable=[]
                for node in registered:
                    if node.get("id") not in chosen_nodes: continue
                    try:
                        status=node_api.request(node,"GET",node_api.API_PREFIX+"/status",timeout=5)
                        caps=set(status.get("capabilities",[]))
                        if not status.get("ok") or "federation" not in caps or not wanted_protocols.issubset(caps):
                            unavailable.append(node)
                    except node_api.NodeError:
                        unavailable.append(node)
                if unavailable:
                    create_error("VPN-службы выбранной ноды недоступны или не поддерживают нужные протоколы. Обновите Node Agent и проверьте Xray.",409); return'''

AFTER = '''                # wpo-federation-live-create-v1: verify real VPN sidecars, not
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


def patch(source):
    if MARKER in source:
        ast.parse(source, filename="panel.py")
        return source
    if source.count(BEFORE) != 1:
        raise ValueError("Expected installed WPO v27 create-handler missing; no changes")
    result = source.replace(BEFORE, AFTER, 1)
    ast.parse(result, filename="panel.py")
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.output.write_text(patch(args.input.read_text(encoding="utf-8")),encoding="utf-8")
    print("✓ Создание пользователя проверяет действующий VPN Federation API")
    print("✓ Ошибка не маскируется под готовую ноду; основная WPO не изменяется")


if __name__=="__main__":
    main()
