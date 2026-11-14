#!/usr/bin/env python3
"""Patch installed WPO multi-node Happ handler: never wait on VPN provisioning.

Each remote profile is created in a bounded worker and only authenticated,
verified URLs enter a subscription. Preserve existing per-device credentials,
exact node selection, routing and Happ response format.
"""
import argparse
import ast
from pathlib import Path

OLD_MARKER="            # wpo-multinode-parallel-v1: exact chosen nodes, concurrent federation"
NEW_MARKER="            # wpo-happ-background-federation-v1: fast verified remote nodes"
END="            state=traffic()"

FEED='''            # wpo-happ-background-federation-v1: fast verified remote nodes
            # Import is bounded to a few seconds even when an existing node
            # is restarting Xray/other native services for its first profile.
            # Never fabricate credentials and never add unselected nodes.
            chosen=subscription.get("node_ids")
            if chosen is None: chosen=["local"]
            if (not isinstance(chosen,list) or not chosen or len(chosen)>17
                    or len(chosen)!=len(set(str(x) for x in chosen))
                    or any(not isinstance(x,str) for x in chosen)):
                self.send_data("Список выбранных нод повреждён.",409); return
            registered=node_api.load_nodes(NODES_FILE)
            available={str(n.get("id","")):n for n in registered}
            if any(uid!="local" and uid not in available for uid in chosen):
                self.send_data("Выбранная нода удалена. Обновите подписку.",409); return
            local_selected="local" in chosen
            labels={"vless":"VLESS","hysteria":"Hysteria2"}
            local_name=node_api.location_prefix(node_api.load_location(LOCATION_FILE))
            wanted=list(dict.fromkeys(u["protocol"] for u in result["users"]
                                      if u["protocol"] in ("vless","hysteria")))
            if not wanted:
                self.send_data("Подписка не содержит активных VPN-протоколов.",409); return
            lines=[]
            if local_selected:
                lines.extend(proxy_link(u["protocol"],u["secret"],u["backend_port"],
                                        local_name,u.get("username",""))
                             for u in result["users"])
            remote_nodes=[available[uid] for uid in chosen if uid!="local"
                          and available[uid].get("enabled",True)]
            unavailable=sum(1 for uid in chosen if uid!="local"
                            and not available[uid].get("enabled",True))
            pending_count=unavailable
            if remote_nodes:
                first=result["users"][0]
                remote_id=federation_id(first.get("subscription_id",""),
                                        first.get("device_id",""))
                batches,pending=wpo_happ_async_feed.collect(
                    node_api, remote_nodes, remote_id, wanted, grace_seconds=4.5)
                lines.extend(batches)
                pending_count+=pending
            if pending_count:
                # Honest, non-secret status in server logs, not a broken
                # whole-subscription 503 that Happ cannot import.
                print("wpo Happ selected remote provisioning pending:",
                      pending_count,"of",len(chosen)-int(local_selected),
                      file=sys.stderr,flush=True)
            if not lines:
                # A remote-only subscription cannot safely contain invented
                # links. Return an explicit retry instead of fake VPN nodes.
                self.send_data("VPN-ноды ещё подготавливаются. Повторите обновление.",
                               503,headers={"Retry-After":"5"}); return
'''


def patch(source):
    if NEW_MARKER in source:
        return source
    if source.count(OLD_MARKER)!=1 or source.count(END)!=1:
        raise ValueError("Installed WPO does not contain expected concurrent-node feed")
    before,after=source.split(OLD_MARKER,1)
    former,rest=after.split(END,1)
    if 'node_api.sync_profile(' not in former:
        raise ValueError("Expected federation bridge missing")
    if 'import wpp_nodes as node_api' not in before:
        raise ValueError("Expected WPO node import missing")
    source=before+FEED+END+rest
    source=source.replace('import wpp_nodes as node_api',
                          'import wpp_nodes as node_api\nimport wpo_happ_async_feed',1)
    if '            headers={"profile-title":' not in source:
        raise ValueError("Happ HTTP headers missing")
    # One hour is Happ's documented minimum auto-update cadence; prior
    # 6h was far too slow after a new node is installed.
    source=source.replace('"profile-update-interval":"6"',
                          '"profile-update-interval":"1" if pending_count else "6"',1)
    for marker in ('local_count=len(result["users"]) if local_selected else 0',
                   'len(distinct_nodes)>1','SUB_FETCH_SLOTS.release()'):
        if marker not in source:
            raise ValueError("Happ safety invariant missing: "+marker)
    ast.parse(source,filename="panel.py")
    return source


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--panel",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    a.output.write_text(patch(a.panel.read_text(encoding="utf-8")),encoding="utf-8")
    print("✓ Happ does not wait for Xray/other native services to be configured")
    print("✓ Only selected, verified real remote VPN profiles appear; no fake keys")
    print("✓ Main node remains instantly importable while remotes prepare")


if __name__=="__main__":
    main()
