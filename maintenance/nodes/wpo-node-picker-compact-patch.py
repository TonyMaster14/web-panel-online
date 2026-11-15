#!/usr/bin/env python3
"""Apply compact single-line VPN node cards to an installed WPO v28 form.

Surgical, idempotent and version-checked; never changes node eligibility,
checkbox names, protocol selection, user data or server configuration.
"""
import argparse
import ast
from pathlib import Path

MARKER='class="wpo-v28-node-title"'
CHANGES=(
    (
        """        f'<span><strong>{h(local_label)}</strong><small>Основная · VPN готов</small></span></label>'""",
        """        f'<span class="wpo-v28-node-title"><strong>{h(local_label)}</strong>'\n        '<span class="wpo-v28-node-star" title="Основная нода" aria-label="Основная нода">★</span>'\n        '</span></label>'"""
    ),
    (
        '''        state = "VPN готова" if ready else "VPN пока не готова"\n''',
        ''
    ),
    (
        """            f'<span><strong>{h(name)}</strong><small>{h(state)}</small></span></label>'""",
        """            f'<span class="wpo-v28-node-title"><strong>{h(name)}</strong></span></label>'"""
    ),
    (
        '.wpo-v28-flag{font-size:19px}.wpo-v28-dialog .unavailable{opacity:.48;cursor:not-allowed}',
        '.wpo-v28-flag{display:inline-flex;align-items:center;justify-content:center;\n'
        ' flex:0 0 auto;font-size:19px;line-height:1}\n'
        '.wpo-v28-node>span.wpo-v28-node-title{display:inline-flex;align-items:center;\n'
        ' gap:7px;min-width:0;line-height:1.25}\n'
        '.wpo-v28-node-title strong{display:block;min-width:0;font-size:11px;\n'
        ' line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n'
        '.wpo-v28-node-star{display:inline-flex;align-items:center;justify-content:center;\n'
        ' flex:0 0 auto;color:#facc15;font-size:15px;font-weight:750;\n'
        ' line-height:1}\n'
        '.wpo-v28-dialog .unavailable{opacity:.48;cursor:not-allowed}'
    )
)

def patch(source):
    if MARKER in source:
        ast.parse(source)
        if 'wpo-v28-node-star' not in source:
            raise ValueError('Incomplete node-picker patch')
        old_star = 'flex:0 0 auto;color:var(--accent);font-size:15px;font-weight:750;'
        yellow_star = 'flex:0 0 auto;color:#facc15;font-size:15px;font-weight:750;'
        if old_star in source:
            source = source.replace(old_star, yellow_star, 1)
            ast.parse(source)
        return source
    result=source
    for old,new in CHANGES:
        if result.count(old)!=1:
            raise ValueError('Unexpected WPO v28 form version; no changes made')
        result=result.replace(old,new,1)
    ast.parse(result)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    old=args.input.read_text(encoding='utf-8')
    new=patch(old)
    args.output.write_text(new,encoding='utf-8')
    print('✓ Флаги и названия нод выровнены по центру')
    print('✓ Надписи о готовности убраны; основная нода отмечена ★')
    print('✓ Статусы и ограничения выбора VPN-нод сохранены')
