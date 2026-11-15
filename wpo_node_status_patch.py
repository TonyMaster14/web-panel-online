"""Refresh cached capabilities from the authenticated agent, not registration only."""
import argparse
import ast
from pathlib import Path

MARKER = '# wpo-live-node-capabilities-v1'
OLD = '                    node["status"]="online"; node["status_detail"]="API отвечает"'
NEW = '''                    # wpo-live-node-capabilities-v1
                    caps=state.get("capabilities",[])
                    node["capabilities"]=[x for x in caps if isinstance(x,str)][:32] if isinstance(caps,list) else []
                    node["status"]="online"; node["status_detail"]="API отвечает"'''

def patch(source):
    if MARKER in source:
        ast.parse(source)
        return source
    if source.count(OLD) != 1:
        raise ValueError('Unknown node status handler; no changes made')
    result = source.replace(OLD, NEW, 1)
    ast.parse(result)
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.write_text(patch(args.input.read_text()))
