#!/usr/bin/env python3
"""Move main-node star from flag badge to the country name on the Nodes page.

Safe, exact-match patch for WPO Nodes Lab v15-v26 installations.
Does not touch VPN readiness, key material, node selection or subscriptions.
"""
import argparse
import ast
from pathlib import Path

OLD_MARKUP = """'<div class="wpo-node-card-head"><span class="wpo-node-flag wpo-node-main-flag">{esc(node_flag(lc))}<span class="wpo-node-main-mark" title="Основная нода" aria-label="Основная нода">★</span></span><div class="wpo-node-label"><h3>{esc(lname)}</h3></div>{status("local","online")}</div>'"""
NEW_MARKUP = """'<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span><div class="wpo-node-label"><h3><span class="wpo-node-main-name">{esc(lname)}</span> <span class="wpo-node-main-star" title="Основная нода" aria-label="Основная нода">★</span></h3></div>{status("local","online")}</div>'"""

OLD_CSS = """.wpo-nodes-page .wpo-node-main-flag{position:relative}
.wpo-nodes-page .wpo-node-main-mark{
    position:absolute;top:-5px;right:-5px;display:grid;place-items:center;
    width:16px;height:16px;border:1px solid var(--line);border-radius:50%;
    background:var(--surface);color:#eab308;
    font:700 10px/1 system-ui,sans-serif
}"""
NEW_CSS = """.wpo-nodes-page .wpo-node-label h3:has(.wpo-node-main-star){
    display:flex;align-items:center;gap:6px;min-width:0
}
.wpo-nodes-page .wpo-node-label .wpo-node-main-name{
    min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis
}
.wpo-nodes-page .wpo-node-label .wpo-node-main-star{
    flex:0 0 auto;display:inline-flex;align-items:center;
    color:#facc15;font:750 15px/1 system-ui,sans-serif
}"""


def patch(source):
    if source.count(NEW_MARKUP) == 1 and source.count(NEW_CSS) == 1:
        ast.parse(source, filename="wpp_ui.py")
        return source
    if source.count(OLD_MARKUP) != 1 or source.count(OLD_CSS) != 1:
        raise ValueError("Неизвестная версия карточек нод. Изменения отменены.")
    updated = source.replace(OLD_MARKUP, NEW_MARKUP, 1).replace(OLD_CSS, NEW_CSS, 1)
    ast.parse(updated, filename="wpp_ui.py")
    return updated


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    source = args.input.read_text(encoding="utf-8")
    args.output.write_text(patch(source), encoding="utf-8")
    print("✓ Звезда ★ теперь после названия основной ноды, с пробелом")
    print("✓ Звезда жёлтая (#facc15), флаг без звезды")
    print("✓ Остальные ноды, статусы и VPN не затронуты")


if __name__ == "__main__":
    main()
