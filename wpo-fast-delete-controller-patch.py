#!/usr/bin/env python3
"""Speed up credential revocation across additional WPO nodes.

All selected subscription devices are revoked as before, but different
physical nodes are contacted simultaneously. Calls to a single node remain
serial to avoid lock contention on its Xray profile registry.
"""
import argparse
import ast
from pathlib import Path

MARKER="# wpo-fast-remote-purge-v1"
BEGIN="def purge_remote_profiles(subscription,device_id=None):\n"
END="\ndef purge_remote_profiles_async(subscription,device_id=None):\n"
OLD='''    for node in node_api.load_nodes(NODES_FILE):
        if not node.get("enabled",True): continue
        for device in devices:
            try: node_api.delete_profile(node,federation_id(subscription.get("id",""),device.get("id","")))
            except node_api.NodeError as exc:
                print("node profile cleanup failed:",node.get("url"),str(exc),file=sys.stderr,flush=True)
'''
NEW='''    # wpo-fast-remote-purge-v1: revoke on different nodes in parallel.
    # Never start concurrent writes for the SAME node's federation registry.
    nodes=[node for node in node_api.load_nodes(NODES_FILE)
           if node.get("enabled",True)]
    def revoke_node(node):
        for device in devices:
            try: node_api.delete_profile(node,federation_id(subscription.get("id",""),device.get("id","")))
            except node_api.NodeError as exc:
                print("node profile cleanup failed:",node.get("url"),type(exc).__name__,file=sys.stderr,flush=True)
    if len(nodes)==1:
        revoke_node(nodes[0])
    elif nodes:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(nodes),4),thread_name_prefix="wpo-revoke") as pool:
            list(pool.map(revoke_node,nodes))
'''

def patch(source):
    if MARKER in source:
        return source
    if source.count(BEGIN)!=1 or source.count(END)!=1:
        raise ValueError("Unknown WPO controller purge source; no changes")
    s=source.index(BEGIN)
    e=source.index(END,s)
    block=source[s:e]
    if block.count(OLD)!=1:
        raise ValueError("Unknown WPO remote cleanup implementation; no changes")
    result=source[:s]+block.replace(OLD,NEW,1)+source[e:]
    if source.startswith("#!/usr/bin/env python3"):
        ast.parse(result,filename="panel.py")
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    opts=ap.parse_args()
    opts.output.write_text(patch(opts.input.read_text(encoding="utf-8")),encoding="utf-8")
    print("✓ Удаление ключей на разных нодах выполняется одновременно")
    print("✓ На одной ноде операции остаются последовательными")

if __name__=="__main__":
    main()
