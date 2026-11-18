"""WPO Nodes: compact REALITY status on the existing site-template row.

Adds no extra domain link and does not rearrange, resize, or replace cards.
The transport mode is shown only when the authenticated Node Agent advertises
it; a generic "reality" capability is not proof of direct-443 routing.
"""
from __future__ import annotations
from html import escape
import re

MARKER = "# WPO_NODE_SITE_VIEW_V1"
REAL443 = "reality-direct-443"
CARD = re.compile(r'<article\b[^>]*\bclass="card wpo-node-card[^"]*"[^>]*>.*?</article>', re.S)
SITE = re.compile(r'(<p\s+class="wpo-node-template"[^>]*>)(.*?)(</p>)', re.S)

CSS = r"""
/* WPO_NODE_SITE_VIEW_V1: existing dimensions, site and link locations unchanged. */
.wpo-nodes-page .wpo-node-template.wpo-site-line-v1{
  display:flex;align-items:center;gap:5px;min-width:0;white-space:nowrap;
  font-size:10px;line-height:1.35;max-width:100%;
}
.wpo-nodes-page .wpo-site-label-v1{
  min-width:0;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.wpo-nodes-page .wpo-site-mode-v1{
  display:inline-flex;align-items:center;flex:0 0 auto;
  padding:2px 5px;border:1px solid var(--line);border-radius:5px;
  font:500 9px/1.2 ui-monospace,monospace;color:var(--muted);
  background:color-mix(in srgb,var(--input) 70%,transparent);
}
.wpo-nodes-page .wpo-node-card.wpo-real443-card-v1 .wpo-node-domain{
  /* Keep the existing domain hyperlink and position. */
  text-decoration:none;
}
"""


def _mode(node):
    caps=node.get("capabilities",[])
    if not isinstance(caps,list):
        caps=[]
    if REAL443 in caps or node.get("reality_mode") == "direct-443":
        return "REALITY 443"
    if "reality" in caps:
        return "REALITY"
    return ""


def decorate(markup, nodes):
    """Enrich only linked remote cards; never touch local or pending cards."""
    if not isinstance(markup,str) or not isinstance(nodes,list):
        return markup
    for node in nodes:
        if not isinstance(node,dict) or not isinstance(node.get("id"),str):
            continue
        identifier=node["id"]
        if not re.fullmatch(r"[a-f0-9]{8,64}",identifier):
            continue
        mode=_mode(node)
        pending=bool(node.get("auto_site_template_id") and
                     not node.get("site_template_id"))
        if not mode and not pending:
            continue
        attr="data-node-edit="+chr(34)+escape(identifier,quote=True)+chr(34)
        def transform(match):
            card=match.group()
            # Deliberately use the exact editor ID, never the hostname alone.
            if attr not in card or "wpo-node-domain" not in card or "href=" not in card:
                return card
            if "wpo-site-line-v1" in card:
                return card
            m=SITE.search(card)
            if not m:
                return card
            original=m.group(2)
            if pending:
                original=original.replace("Сайт не выбран","Выбирается автоматически")
            new_inner='<span class="wpo-site-label-v1">'+original+'</span>'
            if mode:
                new_inner+=('<span class="wpo-site-mode-v1"'
                            ' title="Протокол ноды">')+escape(mode)+'</span>'
            paragraph='<p class="wpo-node-template wpo-site-line-v1">'+new_inner+'</p>'
            patched=card[:m.start()]+paragraph+card[m.end():]
            if mode=="REALITY 443":
                patched=patched.replace('class="card wpo-node-card"',
                                        'class="card wpo-node-card wpo-real443-card-v1"',1)
            return patched
        markup=CARD.sub(transform,markup)
    return markup


def install(ns):
    if ns.get("_wpo_node_site_view_v1_installed"):
        return
    original=ns.get("nodes_ui")
    if not callable(original):
        raise RuntimeError("WPO nodes_ui missing")
    ns["_wpo_node_site_view_v1_installed"]=True

    def nodes_ui(*args,**kwargs):
        content=original(*args,**kwargs)
        nodes=kwargs.get("nodes",args[0] if args else None)
        return decorate(content,nodes)

    ns["nodes_ui"]=nodes_ui
    if isinstance(ns.get("CSS"),str) and "WPO_NODE_SITE_VIEW_V1" not in ns["CSS"]:
        ns["CSS"]+="\n"+CSS
