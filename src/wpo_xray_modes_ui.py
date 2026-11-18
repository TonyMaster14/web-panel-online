"""WPO Xray choices UI: native-size dropdown in the existing Nodes page."""
from html import escape
import json
import re
import wpo_xray_modes as modes

# JSON imports are not modified and private keys are never shown.
PICKER_STYLE = """
<style id="wpo-xray-modes-v27-style">
.wpo-xray-mode-open{display:inline-flex;align-items:center;justify-content:space-between;gap:9px;
  width:100%;height:38px;min-height:38px;padding:0 12px;border:1px solid var(--line);
  border-radius:9px;background:var(--input);color:var(--text);font-size:11px;cursor:pointer}
.wpo-xray-mode-open:hover{border-color:var(--accent)}
.wpo-xray-mode-open svg{width:14px;height:14px;color:var(--muted)}
.wpo-xray-mode-card{margin:4px 0 3px;min-width:0}
#wpoXrayModeDialog{width:min(430px,calc(100vw - 26px));padding:0;max-height:calc(100dvh - 40px);
 border:1px solid var(--line);border-radius:15px;background:var(--surface);color:var(--text)}
#wpoXrayModeDialog::backdrop{background:rgba(0,0,0,.62)}
#wpoXrayModeDialog form{display:grid;gap:16px;padding:19px}
#wpoXrayModeDialog .wpo-xray-mode-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
#wpoXrayModeDialog .wpo-xray-mode-head h3{margin:0;font-size:17px}
#wpoXrayModeDialog .wpo-xray-mode-head button{width:32px;height:32px;min-height:32px;padding:0}
#wpoXrayModeDialog label{display:grid;gap:7px;font-size:11px;color:var(--muted)}
#wpoXrayModeDialog select{display:block;box-sizing:border-box;width:100%;height:41px;padding:0 36px 0 12px;
 border:1px solid var(--line);border-radius:9px;background-color:var(--input);color:var(--text);
 font-size:12px;appearance:none;-webkit-appearance:none;cursor:pointer;
 background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M3 5h10L8 11z' fill='%23939da9'/%3E%3C/svg%3E");
 background-repeat:no-repeat;background-size:14px 14px;background-position:right 12px center}
#wpoXrayModeDialog p{margin:0;font-size:11px;line-height:1.55;color:var(--muted)}
#wpoXrayModeDialog .wpo-xray-mode-actions{display:flex;justify-content:flex-end;gap:9px}
#wpoXrayModeDialog .wpo-xray-mode-actions button{min-width:90px}
@media(max-width:550px){.wpo-xray-mode-open{height:36px;min-height:36px}}
</style>
"""


def attach(html, nodes, path, csrf):
    # Nodes lab builds one article per registered node; do not touch pending
    # installation cards or assume that card sorting matches node list order.
    if 'wpo-xray-modes-v27-style' in html:
        return html
    cards = re.compile(r'(<article\b[^>]*class="[^"]*\bwpo-node-card\b[^"]*"[^>]*>.*?</article>)', re.S)
    found = set()
    seen_local = False
    def with_button(match):
        nonlocal seen_local
        card = match.group(1)
        if 'wpo-pending-node' in card:
            return card
        if not seen_local:
            uid = 'local'
            seen_local = True
            name = 'Основная нода'
            mode = modes.get(modes.PANEL_STATE)
        else:
            m = re.search(r'data-node-edit="([a-f0-9]{16})"',card)
            if not m:
                return card
            uid = m.group(1)
            node = next((n for n in nodes if str(n.get('id'))==uid),None)
            if node is None:
                return card
            name = str(node.get('name') or node.get('country_name') or 'Нода')[:80]
            mode = modes.normalize(node.get('xray_mode','both'))
        found.add(uid)
        trigger = ('<div class="wpo-xray-mode-card"><button type="button" '
            'class="wpo-xray-mode-open" data-wpo-xray-mode-open="'+escape(uid,quote=True)+'" '
            'data-wpo-xray-mode="'+escape(mode,quote=True)+'" '
            'data-wpo-xray-mode-name="'+escape(name,quote=True)+'" '
            'aria-label="Конфигурация Xray: '+escape(name,quote=True)+'">'
            '<span>Конфигурация Xray</span>'
            '<svg aria-hidden="true" viewBox="0 0 16 16"><path fill="currentColor" d="M3 5h10L8 11z"/></svg>'
            '</button></div>')
        anchor = '<div class="wpo-node-card-bottom">'
        if anchor in card:
            return card.replace(anchor,trigger+anchor,1)
        return card.replace('</article>',trigger+'</article>',1)
    updated = cards.sub(with_button,html)
    if not found or 'local' not in found:
        raise RuntimeError("WPO: карточки нод изменились. Xray-выбор не добавлен.")
    registered = {str(n.get('id')) for n in nodes if n.get('id')}
    if not registered.issubset(found):
        raise RuntimeError("WPO: не все подключённые ноды получили Xray-выбор.")
    js = """
<script id="wpo-xray-mode-v27-js">
(()=>{'use strict';
 const dialog=document.getElementById('wpoXrayModeDialog');
 if(!dialog)return;
 const form=dialog.querySelector('form'),name=dialog.querySelector('[data-xray-node-name]');
 const select=form.elements.mode,uid=form.elements.id;
 document.querySelectorAll('[data-wpo-xray-mode-open]').forEach(button=>{
   button.addEventListener('click',()=>{
     uid.value=button.dataset.wpoXrayModeOpen;
     name.textContent=button.dataset.wpoXrayModeName||'Нода';
     select.value=button.dataset.wpoXrayMode||'both';
     dialog.showModal();
   });
 });
 dialog.querySelectorAll('[data-xray-mode-close]').forEach(btn=>btn.addEventListener('click',()=>dialog.close()));
})();
</script>
"""
    modal = (
        '<dialog id="wpoXrayModeDialog"><form method="post" action="'+escape(path,quote=True)+'/node-action">'
        '<div class="wpo-xray-mode-head"><div><h3>Конфигурация Xray</h3>'
        '<small data-xray-node-name>Нода</small></div>'
        '<button type="button" data-xray-mode-close aria-label="Закрыть">×</button></div>'
        '<input type="hidden" name="csrf" value="'+escape(csrf,quote=True)+'">'
        '<input type="hidden" name="operation" value="xray_mode">'
        '<input type="hidden" name="id" value="local">'
        '<label>Подключения<select name="mode" required>'
        '<option value="both">REALITY + Hysteria2</option>'
        '<option value="reality">REALITY</option>'
        '<option value="hysteria">Hysteria2</option>'
        '</select></label>'
        '<p>Выбор применяется только к этой ноде после проверки Xray. '
        'Активные подключения исключаемого протокола защищены от отключения.</p>'
        '<div class="wpo-xray-mode-actions"><button type="button" data-xray-mode-close>Отмена</button>'
        '<button class="primary" type="submit">Сохранить</button></div></form></dialog>'
    )
    return PICKER_STYLE + updated + modal + js


def install_ui(ns):
    original = ns['nodes_ui']
    def nodes_ui(*args, **kwargs):
        html = original(*args, **kwargs)
        nodes = args[0] if args else kwargs['nodes']
        path = args[3] if len(args)>3 else kwargs['path']
        csrf = args[4] if len(args)>4 else kwargs['csrf']
        return attach(html,nodes,path,csrf)
    ns['nodes_ui'] = nodes_ui
