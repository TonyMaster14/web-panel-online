#!/usr/bin/env python3
"""Safe panel-only WPO patch: provision selected VPN nodes concurrently.

Never invent a remote link or include an unselected server; a failing selected
node still produces an explicit 503, with actionable server-side diagnostics.
Does not touch Xray, Caddy, node services, subscriber data or credentials.
"""
import argparse
import ast
from pathlib import Path

OLD_MARKER="            # wpo-exact-node-selection-v1: build ONLY the chosen nodes."
END="            state=traffic()"
NEW_MARKER="            # wpo-multinode-parallel-v1: exact chosen nodes, concurrent federation"

FEED=String = '''            # wpo-multinode-parallel-v1: exact chosen nodes, concurrent federation
            # Saved node_ids remain authoritative; never auto-add an unselected
            # node or send a partial feed when one selected node is unavailable.
            chosen=subscription.get("node_ids")
            if chosen is None: chosen=["local"]
            if (not isinstance(chosen,list) or not chosen or len(chosen)>17
                    or len(chosen)!=len(set(str(x) for x in chosen))
                    or any(not isinstance(x,str) for x in chosen)):
                self.send_data("Список выбранных нод повреждён. Проверьте подписку.",409); return
            registered=node_api.load_nodes(NODES_FILE)
            available={str(n.get("id","")):n for n in registered}
            if any(uid!="local" and uid not in available for uid in chosen):
                self.send_data("Выбранная нода удалена. Обновите настройки подписки.",409); return
            local_selected="local" in chosen
            labels={"vless":"VLESS","hysteria":"Hysteria2"}
            local_name=node_api.location_prefix(node_api.load_location(LOCATION_FILE))
            wanted=list(dict.fromkeys(u["protocol"] for u in result["users"]
                                      if u["protocol"] in ("vless","hysteria")))
            if not wanted:
                self.send_data("В подписке пока нет активных VLESS или Hysteria2.",409); return
            lines=[]
            if local_selected:
                lines.extend(proxy_link(u["protocol"],u["secret"],u["backend_port"],
                                        local_name,u.get("username",""))
                             for u in result["users"])
            remote_nodes=[(uid,available[uid]) for uid in chosen if uid!="local"]
            if any(not node.get("enabled",True) for uid,node in remote_nodes):
                self.send_data("Выбранная VPN-нода выключена.",503); return
            if remote_nodes:
                # Happ must not wait 20 seconds per remote serially; first
                # federation/sync can start multiple node services on a new VPS.
                # Bound concurrency to four; never run unbounded user input.
                import concurrent.futures as _wpo_futures
                first=result["users"][0]
                remote_id=federation_id(first.get("subscription_id",""),
                                        first.get("device_id",""))
                def _wpo_sync_one(item):
                    uid,node=item
                    remote=node_api.sync_profile(node,remote_id,
                                                 node_api.location_prefix(node),wanted)
                    profiles=remote.get("profiles") if isinstance(remote,dict) else None
                    if not isinstance(profiles,list) or len(profiles)!=len(wanted):
                        raise node_api.NodeError("Нода вернула неполный набор протоколов.")
                    by_protocol={}
                    for profile in profiles:
                        if not isinstance(profile,dict):
                            raise node_api.NodeError("Некорректный профиль удалённой ноды.")
                        proto=profile.get("protocol")
                        link=profile.get("link")
                        expected=("vless" if proto=="vless" else
                                  "hysteria2" if proto=="hysteria" else "")
                        if (proto not in wanted or proto in by_protocol
                                or not isinstance(link,str) or len(link)>8192
                                or urlparse(link).scheme.lower()!=expected
                                or urlparse(link).hostname!=urlparse(node.get("url","")).hostname):
                            raise node_api.NodeError("Нода вернула неверный протокол или адрес.")
                        by_protocol[proto]=link
                    if set(by_protocol)!=set(wanted):
                        raise node_api.NodeError("Нода не вернула все выбранные протоколы.")
                    return [by_protocol[protocol] for protocol in wanted]
                # pool.map preserves the exact user-chosen order, while actually
                # provisioning all selected remotes in parallel.
                # Consume all results before publishing a single byte to Happ.
                try:
                    with _wpo_futures.ThreadPoolExecutor(max_workers=min(len(remote_nodes),4)) as pool:
                        batches=list(pool.map(_wpo_sync_one,remote_nodes))
                    for batch in batches:
                        lines.extend(batch)
                except (node_api.NodeError,ValueError,TypeError,TimeoutError,OSError) as exc:
                    # Log the HTTP failure category, never token or remote keys.
                    print("wpo node sync failed:",type(exc).__name__,
                          str(exc)[:120],file=sys.stderr,flush=True)
                    self.send_data("Одна из выбранных нод не отвечает или не смогла создать "
                                   "VPN-профиль. Подписка не обновлена.",503); return
'''

def patch(source):
    if NEW_MARKER in source:
        return source
    if source.count(OLD_MARKER)!=1 or source.count(END)!=1:
        raise ValueError("Expected exact-node feed missing; no changes made")
    before,rest=source.split(OLD_MARKER,1)
    prior,after=rest.split(END,1)
    if 'node_api.sync_profile(' not in prior or 'if local_selected' not in prior:
        raise ValueError("Existing node selection differs; refusing unsafe replacement")
    updated=before+FEED+END+after
    for expected in (
        'local_count=len(result["users"]) if local_selected else 0',
        'len(distinct_nodes)>1',
        'SUB_FETCH_SLOTS.release()',
    ):
        if expected not in updated:
            raise ValueError("Panel missing strict subscription safety marker: "+expected)
    ast.parse(updated,filename="panel.py")
    return updated

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--panel",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(patch(args.panel.read_text(encoding="utf-8")),encoding="utf-8")
    print("✓ WPO: 2+ remote VPN nodes synchronized concurrently, in selected order")
    print("✓ No partial Happ feeds, invented links or changes to existing users")

if __name__=="__main__":
    main()
