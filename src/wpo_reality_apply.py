"""Final, checked migration after historical Nodes Lab source patches."""
import ast
from pathlib import Path
import re
import shutil

MARKER = '# wpo-reality-v1'

def extend_protocols(source):
    # Extend literal supported sets/tuples; never alter the wire protocol 'vless'.
    for old,new in [('"vless","hysteria"','"vless","reality","hysteria"'),
                    ('"vless", "hysteria"','"vless", "reality", "hysteria"'),
                    ("'vless','hysteria'","'vless','reality','hysteria'"),
                    ("'vless', 'hysteria'","'vless', 'reality', 'hysteria'")]:
        source=source.replace(old,new)
    source=source.replace('"vless":"VLESS","hysteria":','"vless":"VLESS","reality":"VLESS REALITY","hysteria":')
    return source

def patch_manager(source):
    if MARKER in source: return source
    source=extend_protocols(source)
    source=source.replace('    elif protocol=="vless":\n        device_secrets=',
                          '    elif protocol in ("vless","reality"):\n        device_secrets=',1)
    source=source.replace('"backend_port":443 if protocol=="vless" else HYSTERIA_PORT',
                          '"backend_port":443 if protocol in ("vless","reality") else HYSTERIA_PORT')
    anchor='cmd=sys.argv[1] if len(sys.argv)>1 else "init"'
    if source.count(anchor)!=1: raise ValueError('Manager entrypoint changed')
    source=source.replace(anchor,MARKER+'\nimport wpo_reality\nwpo_reality.install_manager(globals())\n'+anchor)
    source=source.replace('if cmd=="init": init()',
        'if cmd=="reality-config":\n    print(json.dumps(wpo_reality.configure(json.load(sys.stdin), lambda: sync_xray(load()))))\nelif cmd=="init": init()')
    ast.parse(source); return source

def patch_panel(source):
    if MARKER in source: return source
    # Use exact node selection before extending the protocol catalog.
    if 'def selected_node_ids(form):' in source:
        import wpo_node_selection_v2 as selection
        source=selection.patch_panel(source)
    source=extend_protocols(source)
    # The expert JSON editor remains specific to existing XHTTP/Hysteria. The
    # REALITY private key is never included in runtime_inbound/UI JSON.
    source=source.replace('protocol in ("vless","reality","hysteria") and form.get("xray_json"',
                          'protocol in ("vless","hysteria") and form.get("xray_json"')
    source=source.replace('if protocol in ("vless","reality","hysteria") else ""',
                          'if protocol in ("vless","hysteria") else ""')
    source=source.replace('("vless" if proto=="vless" else', '("vless" if proto in ("vless","reality") else')
    # Remote REALITY uses node IP. Match the verified node status address too.
    source=source.replace('urlparse(link).hostname!=urlparse(node.get("url","")).hostname',
        'urlparse(link).hostname not in (urlparse(node.get("url","")).hostname, node.get("ip"), node.get("ipv4"))')
    if '# wpo-exact-node-selection-v1' in source:
        method=source.index('    def serve_subscription(self,token):')
        start=source.index('                for uid in chosen:',method)
        end=source.index('            state=traffic()',start)
        source=source[:start]+'''                remote_nodes=[available[uid] for uid in chosen if uid!="local"]
                if any(not n.get("enabled",True) for n in remote_nodes):
                    self.send_data("Выбранная VPN-нода выключена.",503); return
                import wpo_happ_async_feed
                remote_links,pending=wpo_happ_async_feed.collect(node_api,remote_nodes,remote_id,wanted)
                if pending:
                    self.send_data("Подписка готовится. Повторите обновление.",503,headers={"Retry-After":"2"}); return
                lines.extend(remote_links)
'''+source[end:]
    source=source.replace('len(distinct_nodes)>1', 'len(chosen)>1' if '# wpo-exact-node-selection-v1' in source else 'len(distinct_nodes)>1')
    anchor='        if path==PANEL_PATH+"/connection-action":'
    if source.count(anchor)!=1: raise ValueError('Authenticated connection route changed')
    handler='''        if path==PANEL_PATH+"/reality-action":
            try:
                request={"preset":form.get("preset","nvidia"),"sni":form.get("sni",""),
                         "fingerprint":form.get("fingerprint","firefox"),"check_only":form.get("check_only")=="1"}
                uid=form.get("node_id","local")
                if uid!="local":
                    node=next((n for n in node_api.load_nodes(NODES_FILE) if n.get("id")==uid),None)
                    if not node: raise ValueError("Нода не найдена")
                    try:
                        result=node_api.request(node,"GET" if form.get("read_only")=="1" else "POST",
                            "/wpp-api/v1/federation/reality",None if form.get("read_only")=="1" else request,timeout=45)
                    except node_api.NodeError as exc: raise ValueError(str(exc))
                    self.send_json(result)
                elif form.get("read_only")=="1":
                    self.send_json({"ok":True,"profile":wpo_reality.read_profile()})
                else:
                    result=subprocess.run([MANAGER,"reality-config"],input=json.dumps(request),
                                          text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
                    if result.returncode: raise ValueError((result.stderr or "Не удалось применить REALITY")[-1500:])
                    self.send_json(json.loads(result.stdout))
                if form.get("read_only")!="1" and not request["check_only"]:
                    import wpo_happ_async_feed
                    wpo_happ_async_feed.invalidate_all()
            except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
                self.send_json({"ok":False,"message":str(exc)},409)
            return
'''
    source=source.replace(anchor,handler+anchor)
    anchor='if __name__=="__main__":'
    if source.count(anchor)!=1: raise ValueError('Panel entrypoint changed')
    source=source.replace(anchor,MARKER+'\nimport wpo_reality\nwpo_reality.install_panel(globals())\nwpo_reality.install_happ(globals())\n'+anchor)
    ast.parse(source); return source

def patch_ui(source):
    if MARKER in source: return source
    source=extend_protocols(source)
    source=source.replace("'hysteria':'Hysteria2'", "'reality':'VLESS REALITY','hysteria':'Hysteria2'")
    source=source.replace('<option value="hysteria">Hysteria2</option>',
        '<option value="reality">VLESS TCP REALITY Vision</option><option value="hysteria">Hysteria2</option>')
    source+='\n'+MARKER+'\nimport wpo_reality_ui\nwpo_reality_ui.install(globals())\n'
    ast.parse(source); return source

def apply(app, manager, source):
    for name in ('wpo_reality.py','wpo_reality_probe.py','wpo_reality_ui.py','wpo_xray_live.py','wpo_happ_async_feed.py','wpo_happ_preparer.py'):
        shutil.copy2(source/name, app/name)
    for path, fn in ((app/'panel.py',patch_panel),(manager,patch_manager),(app/'wpp_ui.py',patch_ui)):
        old=path.read_text(); new=fn(old)
        if new!=old:
            shutil.copy2(path,str(path)+'.before-reality')
            path.write_text(new)
    import wpo_fast_actions_apply
    wpo_fast_actions_apply.apply(app,manager,source)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,default=Path('/opt/tproxy-panel'))
    parser.add_argument('--manager',type=Path,default=Path('/usr/local/sbin/web-proxy-panelctl'))
    args=parser.parse_args();apply(args.app,args.manager,Path(__file__).resolve().parent)
