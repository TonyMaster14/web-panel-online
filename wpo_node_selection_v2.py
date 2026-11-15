#!/usr/bin/env python3
"""WPO: exact node selection for Happ feeds, with verified remote federation links.

Designed for the already installed Nodes Lab + v28 controller. Does not modify
users, keys, Xray, node registry, or public domain. Never fabricate a profile.
"""
import argparse
import ast
from pathlib import Path

MARKER = "# wpo-exact-node-selection-v1"
BEGIN = '            labels={"vless":"VLESS","hysteria":"Hysteria2"}'
END = '            state=traffic()'
METHOD = '    def serve_subscription(self,token):'
NEXT_METHOD = '    def serve_direct_profile(self,token):'

FEED = '''            # wpo-exact-node-selection-v1: build ONLY the chosen nodes.
            # Missing selections from historical records default to the main
            # node, never silently expose unrelated newly registered servers.
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
            # A remote-only subscription never publishes the controller's local
            # profile, despite the local device registry holding its own key.
            if len(chosen)>1 or chosen[0]!="local":
                first=result["users"][0]
                remote_id=federation_id(first.get("subscription_id",""),
                                        first.get("device_id",""))
                for uid in chosen:
                    if uid=="local": continue
                    node=available[uid]
                    if not node.get("enabled",True):
                        self.send_data("Выбранная VPN-нода выключена.",503); return
                    try:
                        remote=node_api.sync_profile(
                            node,remote_id,node_api.location_prefix(node),wanted)
                        profiles=remote.get("profiles") if isinstance(remote,dict) else None
                        if not isinstance(profiles,list) or len(profiles)!=len(wanted):
                            raise node_api.NodeError("Нода вернула неполный набор протоколов.")
                        by_protocol={}
                        for profile in profiles:
                            if not isinstance(profile,dict):
                                raise node_api.NodeError("Нода вернула некорректный профиль.")
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
                        lines.extend(by_protocol[protocol] for protocol in wanted)
                    except (node_api.NodeError,ValueError,TypeError) as exc:
                        # Do not misrepresent a partially created subscription
                        # as a healthy multi-node feed. Existing Happ cache
                        # remains usable during a transient node outage.
                        print("wpo node sync failed:",uid,type(exc).__name__,
                              file=sys.stderr,flush=True)
                        self.send_data("Одна из выбранных нод не отвечает. "
                                       "Подписка не обновлена; повторите позже.",503); return
'''

def patch_panel(source):
    if source.count(METHOD)!=1 or source.count(NEXT_METHOD)!=1:
        raise ValueError("Unknown WPO subscription handler; no changes applied")
    if "def selected_node_ids(form):" not in source:
        raise ValueError("Controller lacks the Nodes Lab selection API")
    before, remainder = source.split(METHOD,1)
    body, after = remainder.split(NEXT_METHOD,1)
    if MARKER in body:
        return source
    # The handler has a first labels assignment for HTML/QR dashboard;
    # replace only the second assignment in its VPN feed branch.
    if body.count(BEGIN)<2 or body.count(END)!=1:
        raise ValueError("Unexpected subscription body: cannot safely patch")
    prefix, remainder = body.rsplit(BEGIN,1)
    old_block, suffix = remainder.split(END,1)
    if "node_api.sync_profile(" not in old_block:
        raise ValueError("Controller lacks the federation sync bridge")
    body=prefix+FEED+END+suffix
    # The number of local links is zero for remote-only subscriptions. All
    # subsequent routing profiles are applied to the correctly indexed link.
    import re
    m=re.search(r'(?m)^            local_count=len\(result\["users"\]\)(?: if local_selected else 0)?$',body)
    if not m:
        raise ValueError("Cannot locate local routing alignment guard")
    body=body[:m.start()]+'            local_count=len(result["users"]) if local_selected else 0'+body[m.end():]
    # Ensure auto is only offered when at least two different VPN hosts exist.
    if 'failover=bool(lines)' in body:
        body=body.replace('            failover=bool(lines)',
                          '            distinct_nodes={urlparse(link).hostname for link in lines if urlparse(link).hostname}\n'
                          '            failover=bool(subscription.get("failover_enabled",True)) and len(distinct_nodes)>1',1)
    if 'len(distinct_nodes)>1' not in body:
        raise ValueError("No safe multi-node auto-select guard")
    # Keep existing Happ response format; never change VLESS/Hysteria transports.
    result=before+METHOD+body+NEXT_METHOD+after
    # Installing eight engines (including MTProxy and AWG builds) can exceed
    # the historical 15-minute enrollment TTL on a small VPS. Keep the
    # cryptographically random token single-use, but allow two hours to finish.
    if 'if path==PANEL_PATH+"/node-bootstrap":' in result:
        old_ttl='"expires_at":now+900'
        old_ui='"expires_in":900'
        if result.count(old_ttl)==1 and result.count(old_ui)==1:
            result=result.replace(old_ttl,'"expires_at":now+7200',1)
            result=result.replace(old_ui,'"expires_in":7200',1)
        elif not ('"expires_at":now+7200' in result and '"expires_in":7200' in result):
            raise ValueError("Unexpected bootstrap token expiry settings")
    ast.parse(result,filename="panel.py")
    return result

def verify_subscriptions(source):
    required=(
        "def clean_node_ids(value):",
        "'node_ids':clean_node_ids(request.get('node_ids',['local']))",
        "sub['node_ids']=clean_node_ids(request.get('node_ids'))"
    )
    missing=[m for m in required if m not in source]
    if missing: raise ValueError("Subscriptions do not persist selected nodes: "+", ".join(missing))
    ast.parse(source,filename="wpp_subscriptions.py")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--panel",type=Path,required=True)
    p.add_argument("--subscriptions",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    verify_subscriptions(a.subscriptions.read_text(encoding="utf-8"))
    modified=patch_panel(a.panel.read_text(encoding="utf-8"))
    a.output.write_text(modified,encoding="utf-8")
    print("✓ WPO: выбранные ноды сохраняются и проверяются")
    print("✓ Happ: только выбранные ноды, без чужих серверов")
    print("✓ Для нескольких узлов — все VPN-профили или явная ошибка")
    print("✓ Автовыбор — только при нескольких разных VPN-адресах")

if __name__=="__main__":
    main()
