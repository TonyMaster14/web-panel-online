"""Idempotent targeted patch for installed WPO; does not replace registries."""
import ast
from pathlib import Path
import shutil

MARKER='# wpo-fast-actions-v2'


def patch_manager(source):
    if MARKER in source:return source
    anchor='cmd=sys.argv[1] if len(sys.argv)>1 else "init"'
    if source.count(anchor)!=1:raise ValueError('Unknown manager entrypoint')
    # Bound the stats RPC itself, including existing periodic collectors.
    source=source.replace('"api","statsquery","--server="+XRAY_API,timeout=15',
                          '"api","statsquery","--server="+XRAY_API,"--timeout=2",timeout=3')
    if source.count('elif cmd=="connections-refresh": refresh_connections()')!=1:
        raise ValueError('Unknown connection refresh entrypoint')
    source=source.replace('elif cmd=="connections-refresh": refresh_connections()',
                          'elif cmd=="connections-refresh": refresh_connections(json.loads(sys.stdin.read() or "{}"))')
    source=source.replace(anchor,MARKER+'\nimport wpo_fast_actions\nwpo_fast_actions.install(globals())\n'+anchor)
    ast.parse(source);return source


def patch_panel(source):
    source=source.replace('("vless","hysteria","awg20","awg31")',
                          '("vless","reality","hysteria","awg20","awg31")')
    if MARKER in source:return source
    if source.count('ctl_manager_json("connections-refresh",{})')!=3:
        raise ValueError('Unknown panel connection handlers')
    source=source.replace('ctl_manager_json("connections-refresh",{})',
                          'ctl_manager_json("connections-refresh",{"previous_registry":previous_registry})',2)
    source+='\n'+MARKER+'\n'
    ast.parse(source);return source


def patch_ui(source):
    source=source.replace("('vless','hysteria','awg20','awg31')",
                          "('vless','reality','hysteria','awg20','awg31')")
    source=source.replace("{'vless':0,'hysteria':1,'awg20':2,'awg31':3}",
                          "{'vless':0,'reality':1,'hysteria':2,'awg20':3,'awg31':4}")
    source=source.replace("(('vless','VLESS XHTTP'),('hysteria','Hysteria2'),",
                          "(('vless','VLESS XHTTP'),('reality','VLESS TCP REALITY Vision'),('hysteria','Hysteria2'),")
    source=source.replace('.routing-protocol-section .routing-protocol-grid{{\n    grid-template-columns:repeat(5,minmax(0,1fr));gap:8px',
                          '.routing-protocol-section .routing-protocol-grid{{\n    grid-template-columns:repeat(6,minmax(0,1fr));gap:8px')
    marker='# wpo-quiet-client-pending-v2'
    if marker not in source:
        source+='\n'+marker+"\nCSS += '\\n.clients-table tr.client-pending .client-name:after{content:none!important}\\n'\n"
    ast.parse(source);return source



def apply(app,manager,source):
    candidates=[(manager,patch_manager(manager.read_text())),
                (app/'panel.py',patch_panel((app/'panel.py').read_text())),
                (app/'wpp_ui.py',patch_ui((app/'wpp_ui.py').read_text()))]
    for path,text in candidates:compile(text,str(path),'exec')
    shutil.copy2(source/'wpo_fast_actions.py',app/'wpo_fast_actions.py')
    for path,text in candidates:
        if text==path.read_text():continue
        shutil.copy2(path,str(path)+'.before-fast-actions-v2')
        path.write_text(text)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,default=Path('/opt/tproxy-panel'))
    p.add_argument('--manager',type=Path,default=Path('/usr/local/sbin/web-proxy-panelctl'))
    args=p.parse_args();apply(args.app,args.manager,Path(__file__).resolve().parent)
