#!/usr/bin/env python3
"""Reskin WPO Routing as protocol choice cards and multi-select rule cards.

Visual-only transformation: all POST endpoints, input names, operations and
existing routing state remain unchanged. Inactive presets and AWG controls
keep their established server-side semantics. Exact anchors prevent applying
to a different UI version.
"""
import argparse
import ast
import re
from pathlib import Path

MARKER = "/* wpo-routing-protocol-cards-v1 */"

OLD_CHOICES = """    choices=[item for item in connections if selectable_connection(item) and item.get('enabled') and item.get('protocol') in ('vless','hysteria','awg20','awg31')]"""
NEW_CHOICES = """    choices=sorted(
        (item for item in connections if selectable_connection(item)
         and item.get('enabled') and item.get('protocol') in ('vless','hysteria','awg20','awg31')),
        key=lambda item: {'vless':0,'hysteria':1,'awg20':2,'awg31':3}.get(item.get('protocol'),4))
"""

OLD_OPTIONS = """    options=''.join(f'<option value="{esc(item["id"])}">{esc(item.get("name","VLESS"))}</option>' for item in choices)"""
NEW_OPTIONS = """    options=''.join(f'<option value="{esc(item["id"])}">{esc(item.get("name","VLESS"))}</option>' for item in choices)
    routing_tabs=[]
    for protocol,title in (('vless','VLESS XHTTP'),('hysteria','Hysteria2'),
                           ('awg20','AmneziaWG 2.0'),('awg31','AmneziaWG 3.1')):
        available=[item for item in choices if item.get('protocol')==protocol]
        if not available:
            routing_tabs.append(
                '<div class="routing-protocol-card is-unavailable" aria-disabled="true">'
                '<span class="routing-tab-dot" aria-hidden="true"><i></i></span>'
                f'<span class="routing-tab-copy"><b>{esc(title)}</b>'
                '<small>Нет подключения</small></span></div>')
            continue
        for item in available:
            selected=' is-selected' if item is choices[0] else ''
            routing_tabs.append(
                f'<button class="routing-protocol-card{selected}" type="button"'
                f' data-routing-choice="{esc(item["id"])}"'
                f' aria-pressed="{"true" if selected else "false"}">'
                '<span class="routing-tab-dot" aria-hidden="true"><i></i></span>'
                f'<span class="routing-tab-copy"><b>{esc(title)}</b>'
                f'<small>{esc(item.get("name") or title)}</small></span></button>')
    chooser=(
        '<section class="routing-protocol-section" aria-label="Протоколы маршрутизации">'
        '<div class="routing-protocol-head"><h2>Маршрутизация</h2>'
        '<p>Выберите подключение для настройки правил</p></div>'
        '<div class="routing-protocol-grid" role="group" aria-label="Выбор подключения">'
        +''.join(routing_tabs)+'</div></section>')
"""

RULE_PAT = re.compile(
    r'(<label class="routing-toggle\{active\(\x27(?:ru_direct|private_direct|youtube_proxy|push_proxy|captive_direct|block_bittorrent|split_dns)\x27\)\}">'
    r'<input type="checkbox" name="select_[a-z_]+" value="1">)'
    r'<span><b>')

OLD_BOTTOM = """</style><div class="routing-picker"><label>Подключение для маршрутизации<select id="routingConnection">{options}</select></label></div>{''.join(forms)}"""
NEW_BOTTOM = """</style>{chooser}<select id="routingConnection" hidden aria-label="Текущее подключение для маршрутизации">{options}</select>{''.join(forms)}"""

OLD_JS_INIT = """const select=document.getElementById('routingConnection'),forms=[...document.querySelectorAll('[data-routing-form]')];"""
NEW_JS_INIT = """const select=document.getElementById('routingConnection'),cards=[...document.querySelectorAll('[data-routing-choice]')],forms=[...document.querySelectorAll('[data-routing-form]')];"""
OLD_JS_SHOW = """const show=()=>forms.forEach(form=>form.hidden=form.dataset.routingForm!==select.value);show();select.addEventListener('change',()=>{{show();history.replaceState(null,'',location.pathname+location.search+'#routing-'+encodeURIComponent(select.value))}});"""
NEW_JS_SHOW = """const show=()=>{{forms.forEach(form=>form.hidden=form.dataset.routingForm!==select.value);cards.forEach(card=>{{const active=card.dataset.routingChoice===select.value;card.classList.toggle('is-selected',active);card.setAttribute('aria-pressed',String(active))}})}};show();cards.forEach(card=>card.addEventListener('click',()=>{{if(select.value===card.dataset.routingChoice)return;select.value=card.dataset.routingChoice;select.dispatchEvent(new Event('change',{{bubbles:true}}))}}));select.addEventListener('change',()=>{{show();history.replaceState(null,'',location.pathname+location.search+'#routing-'+encodeURIComponent(select.value))}});"""

STYLE = r"""
/* wpo-routing-protocol-cards-v1 */
.routing-protocol-section{margin:0 0 13px}
.routing-protocol-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin:0 0 12px}
.routing-protocol-head h2{margin:0;font-size:15px;font-weight:700;color:var(--text)}
.routing-protocol-head p{margin:0;font-size:11px;color:var(--muted)}
.routing-protocol-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.routing-protocol-card{position:relative;display:flex;align-items:center;text-align:left;gap:10px;width:100%;min-height:76px;padding:13px 14px;border:1px solid var(--line);border-radius:12px;background:var(--input);color:var(--text);box-shadow:none;cursor:pointer;transition:border-color .16s,background-color .16s,box-shadow .16s}
.routing-protocol-card:hover:not(:disabled):not(.is-unavailable){border-color:#3b82f6;background:color-mix(in srgb,#3b82f6 6%,var(--input))}
.routing-protocol-card.is-selected{border-color:#3b82f6;background:color-mix(in srgb,#3b82f6 15%,var(--input));box-shadow:inset 0 0 0 1px color-mix(in srgb,#3b82f6 45%,transparent)}
.routing-protocol-card:focus-visible{outline:2px solid #3b82f6;outline-offset:2px}
.routing-protocol-card.is-unavailable{opacity:.44;cursor:not-allowed}
.routing-tab-dot{display:inline-flex;align-items:center;justify-content:center;flex:0 0 17px;width:17px;height:17px;border:1.5px solid #8394a9;border-radius:50%;background:transparent}
.routing-tab-dot i{width:8px;height:8px;border-radius:50%;background:transparent}
.routing-protocol-card.is-selected .routing-tab-dot{border-color:#22c55e;background:color-mix(in srgb,#22c55e 12%,transparent)}
.routing-protocol-card.is-selected .routing-tab-dot i{background:#22c55e}
.routing-tab-copy{min-width:0;display:grid;gap:4px}
.routing-tab-copy b{font-size:12px;line-height:1.25;font-weight:700}
.routing-tab-copy small{font-size:10px;line-height:1.3;color:var(--muted);overflow-wrap:anywhere}
.routing-form .routing-client-notice{margin:13px 14px 0;border:1px solid color-mix(in srgb,var(--red) 52%,var(--line));border-radius:13px;overflow:hidden;box-shadow:inset 4px 0 var(--red),0 4px 15px #00000018}
.routing-form .routing-switches{align-content:start;grid-auto-rows:minmax(77px,auto)}
.routing-form .routing-switches label.routing-toggle{position:relative;display:flex;align-items:center;gap:11px;min-width:0;min-height:77px;height:auto;padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--input);box-shadow:none;cursor:pointer;transition:border-color .16s,background .16s,box-shadow .16s}
.routing-form .routing-switches label.routing-toggle:hover{border-color:#3b82f6}
.routing-form .routing-switches label.routing-toggle.is-active{border-color:var(--line);background:var(--input);box-shadow:none}
.routing-form .routing-switches label.routing-toggle input[type=checkbox]{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;margin:0}
.routing-form .routing-switches label.routing-toggle:focus-within{outline:2px solid #3b82f6;outline-offset:2px}
.routing-form .routing-switches .routing-rule-dot{display:inline-flex;align-items:center;justify-content:center;flex:0 0 16px;width:16px;height:16px;border:1.5px solid #8292a6;border-radius:50%;background:transparent}
.routing-form .routing-switches .routing-rule-dot i{display:block;width:7px;height:7px;border-radius:50%;background:transparent}
.routing-form .routing-switches .routing-rule-copy{display:block;min-width:0;flex:1}
.routing-form .routing-switches label.routing-toggle:has(input:checked){border-color:#3b82f6;background:color-mix(in srgb,#3b82f6 15%,var(--input));box-shadow:inset 0 0 0 1px color-mix(in srgb,#3b82f6 45%,transparent)}
.routing-form .routing-switches label.routing-toggle:has(input:checked) .routing-rule-dot{border-color:#22c55e;background:color-mix(in srgb,#22c55e 10%,transparent)}
.routing-form .routing-switches label.routing-toggle:has(input:checked) .routing-rule-dot i{background:#22c55e}
.routing-form .routing-switches label.routing-toggle em{margin-left:5px;font-size:9px;color:var(--green)}
@media(max-width:1150px){.routing-protocol-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:650px){.routing-protocol-grid{grid-template-columns:1fr 1fr;gap:8px}.routing-protocol-card{min-height:80px;padding:11px 10px;gap:8px}.routing-tab-copy b{font-size:11px}.routing-tab-copy small{font-size:9px}.routing-form .routing-client-notice{margin:10px 10px 0}.routing-protocol-head p{font-size:10px}}
"""

def once(src,old,new,label):
    n=src.count(old)
    if n!=1:
        raise ValueError(f"{label}: ожидалось одно совпадение, найдено {n}. Ничего не изменено.")
    return src.replace(old,new,1)

def patch(src):
    if MARKER in src:
        ast.parse(src,filename="wpp_ui.py")
        if src.count('data-routing-choice=')!=1 or 'routing-rule-dot' not in src:
            raise ValueError("Частично применённая разметка маршрутизации")
        # Earlier UI builds styled AWG's information article as a checkbox.
        # Keep the AWG download/tutorial layout independent from rule labels.
        old_selector=".routing-form .routing-switches .routing-toggle"
        new_selector=".routing-form .routing-switches label.routing-toggle"
        if old_selector in src:
            src=src.replace(old_selector,new_selector)
            ast.parse(src,filename="wpp_ui.py")
        return src
    start=src.index("def routing_ui(")
    end=src.index("\n\ndef connections_ui(",start)
    body=src[start:end]
    body=once(body,OLD_CHOICES,NEW_CHOICES,"протоколы")
    body=once(body,OLD_OPTIONS,NEW_OPTIONS,"выбор подключений")
    body,count=RULE_PAT.subn(
        r'\1<span class="routing-rule-dot" aria-hidden="true"><i></i></span><span class="routing-rule-copy"><b>',
        body)
    if count != 7:
        raise ValueError(f"Ожидалось 7 переключателей, обнаружено {count}")
    css=STYLE.replace("{","{{").replace("}","}}")
    body=once(body,OLD_BOTTOM,css+"\n"+NEW_BOTTOM,"верхний блок")
    body=once(body,OLD_JS_INIT,NEW_JS_INIT,"обработчик выбора подключения")
    body=once(body,OLD_JS_SHOW,NEW_JS_SHOW,"переключение форм")
    out=src[:start]+body+src[end:]
    ast.parse(out,filename="wpp_ui.py")
    return out

if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--input",required=True,type=Path)
    a.add_argument("--output",required=True,type=Path)
    p=a.parse_args()
    source=p.input.read_text(encoding="utf-8")
    result=patch(source)
    p.output.write_text(result,encoding="utf-8")
    print("✓ Выбор маршрутизации: 4 типа протоколов, ровно одно активное подключение")
    print("✓ Правила: независимый множественный выбор, синие карточки и зелёные точки")
    print("✓ Предупреждение: красная плашка с закруглёнными краями")
    print("✓ Имена полей, API, существующие сохранённые правила и действия не изменены")
