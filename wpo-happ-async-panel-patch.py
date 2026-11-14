#!/usr/bin/env python3
"""Patch installed WPO multi-node Happ feed to avoid synchronous POST on HTTP.

With a valid local VPN selected, Happ imports immediately and remote profiles
are included once their independent authenticated federation jobs complete.
Never invent a remote link or include a node that was not selected.
"""
import argparse
import ast
from pathlib import Path

BEGIN="            # wpo-multinode-parallel-v1:"
END="            state=traffic()"
NEW="# wpo-happ-fast-feed-v1:"
ASYNC_IMPORT="import wpo_happ_async_feed"
BASE_IMPORT="import wpp_nodes as node_api"

BODY='''            # wpo-happ-fast-feed-v1: no remote POST in the Happ HTTP thread.
            chosen=subscription.get("node_ids")
            if chosen is None: chosen=["local"]
            if (not isinstance(chosen,list) or not chosen or len(chosen)>17
                    or len(chosen)!=len(set(str(x) for x in chosen))
                    or any(not isinstance(x,str) for x in chosen)):
                self.send_data("Выбранные VPN-ноды повреждены.",409); return
            registered=node_api.load_nodes(NODES_FILE)
            available={str(n.get("id","")):n for n in registered}
            if any(uid!="local" and uid not in available for uid in chosen):
                self.send_data("Выбранная нода удалена. Измените подписку.",409); return
            local_selected="local" in chosen
            labels={"vless":"VLESS","hysteria":"Hysteria2"}
            local_name=node_api.location_prefix(node_api.load_location(LOCATION_FILE))
            wanted=list(dict.fromkeys(u["protocol"] for u in result["users"]
                                      if u["protocol"] in ("vless","hysteria")))
            if not wanted:
                self.send_data("В подписке нет VPN-протоколов.",409); return
            lines=[]
            if local_selected:
                lines.extend(proxy_link(u["protocol"],u["secret"],u["backend_port"],
                                        local_name,u.get("username",""))
                             for u in result["users"])
            pending_count=0
            if any(uid!="local" for uid in chosen):
                first=result["users"][0]
                remote_id=federation_id(first.get("subscription_id",""),
                                        first.get("device_id",""))
                remotes=[available[uid] for uid in chosen if uid!="local"]
                # Start every selected node at once. When the controller has
                # already pre-provisioned the device, these calls return
                # immediately and all 3 nodes fit within Happ's 9s default.
                for node in remotes:
                    if node.get("enabled",True):
                        wpo_happ_async_feed.enqueue(
                            node_api,node,remote_id,node_api.location_prefix(node),wanted)
                # Never wait beyond 2.5s even when the node is applying Xray
                # for the first time. Happ's default request limit is 9s.
                # Only wait when the controller has ALREADY provisioned all
                # remote profiles. Otherwise return valid local links promptly,
                # while Node API workers continue in the background.
                if wpo_happ_async_feed.prewarmed(remotes,remote_id,wanted):
                    deadline=time.monotonic()+2.5
                    while time.monotonic()<deadline:
                        if all(wpo_happ_async_feed.enqueue(
                                node_api,n,remote_id,node_api.location_prefix(n),wanted)[0]
                               for n in remotes):
                            break
                        time.sleep(0.05)
                for node in remotes:
                    if not node.get("enabled",True):
                        pending_count+=1
                        continue
                    ready,waiting=wpo_happ_async_feed.enqueue(
                        node_api,node,remote_id,node_api.location_prefix(node),wanted)
                    if ready:
                        lines.extend(ready)
                    else:
                        pending_count+=1
            # No invented or unverified remote credentials. When only a
            # remote node was chosen, there is no safe fallback local link.
            if not lines:
                self.send_data("Подключения выбранных нод подготавливаются. "
                               "Повторите загрузку через 30 секунд.",503,
                               headers={"Retry-After":"30"}); return
'''
def patch(source):
    if NEW in source:
        ast.parse(source,filename="panel.py")
        return source
    if source.count(BEGIN)!=1 or source.count(END)!=1 or source.count(BASE_IMPORT)!=1:
        raise ValueError("Expected exact-node WPO handler not found; no changes")
    before, remainder=source.split(BEGIN,1)
    old, tail=remainder.split(END,1)
    if "ThreadPoolExecutor(max_workers=min(len(remote_nodes),4))" not in old:
        raise ValueError("WPO concurrent federation v1 missing; refusing unsafe patch")
    updated=source.replace(BASE_IMPORT,BASE_IMPORT+"\n"+ASYNC_IMPORT,1)
    # Re-split after import insertion.
    prefix,rem=updated.split(BEGIN,1)
    body,suffix=rem.split(END,1)
    updated=prefix+BODY+END+suffix
    needle='"profile-update-interval":"6"'
    if updated.count(needle)!=1:
        raise ValueError("Happ subscription headers missing")
    # Happ specifies the interval in hours, not seconds; use its minimum.
    updated=updated.replace(needle,'"profile-update-interval":"1"',1)
    for safe in ('local_count=len(result["users"]) if local_selected else 0',
                 'len(distinct_nodes)>1','SUB_FETCH_SLOTS.release()',
                 'wpo_happ_async_feed.enqueue('):
        if safe not in updated:
            raise ValueError("Missing WPO feed safety marker: "+safe)
    ast.parse(updated,filename="panel.py")
    return updated

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--panel",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    a.output.write_text(patch(a.panel.read_text(encoding="utf-8")),encoding="utf-8")
    print("✓ Happ: HTTPS-ответ больше не ждёт перезапуск VPN на дополнительных VPS")
    print("✓ В Happ только проверенные реальные профили, без вымышленных нод")
    print("✓ Догрузка дополнительных нод при повторном обновлении подписки")

if __name__=="__main__":
    main()
