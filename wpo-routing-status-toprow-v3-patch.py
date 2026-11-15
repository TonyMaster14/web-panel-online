#!/usr/bin/env python3
"""WPO Routing: a fifth non-interactive status tile next to compact protocol tabs.

Status reflects the selected REAL connection (saved routing for VLESS/Hysteria,
stored AllowedIPs configuration for AmneziaWG). Preserves all server actions.
"""
import argparse
import ast
from pathlib import Path

MARKER="/* wpo-routing-status-toprow-v3 */"
FUNCTION="def routing_ui("
OLD_TABS="    routing_tabs=[]\n"
NEW_TABS="""    def routing_enabled(item):
        protocol=item.get('protocol')
        saved=(awg_profiles if protocol in ('awg20','awg31') else profiles).get(item['id'])
        if not isinstance(saved,dict):
            return False
        if protocol in ('awg20','awg31'):
            return bool(saved.get('allowed_ips',[]))
        return bool(saved.get('enabled'))
    routing_tabs=[]
"""
OLD_CARD="""                f' data-routing-choice="{esc(item["id"])}"'
                f' aria-pressed="{"true" if selected else "false"}'>"""
NEW_CARD="""                f' data-routing-choice="{esc(item["id"])}"'
                f' data-routing-enabled="{"1" if routing_enabled(item) else "0"}"'
                f' aria-pressed="{"true" if selected else "false"}'>"""
OLD_CHOOSER="""    chooser=(
        '<section class="routing-protocol-section" aria-label="Протоколы маршрутизации">'
        '<div class="routing-protocol-head"><h2>Маршрутизация</h2>'
        '<p>Выберите подключение для настройки правил</p></div>'
        '<div class="routing-protocol-grid" role="group" aria-label="Выбор подключения">'
        +''.join(routing_tabs)+'</div></section>')"""
NEW_CHOOSER="""    status_class=' is-on' if routing_enabled(choices[0]) else ''
    status_label='Маршрутизация включена' if status_class else 'Маршрутизация отключена'
    status_tile=(
        f'<div id="routingState" class="routing-protocol-status{status_class}"'
        ' role="status" aria-live="polite">'
        '<span class="routing-tab-dot" aria-hidden="true"><i></i></span>'
        f'<span class="routing-tab-copy"><b id="routingStateTitle">{status_label}</b>'
        '<small>Выбранное подключение</small></span></div>')
    chooser=(
        '<section class="routing-protocol-section" aria-label="Протоколы маршрутизации">'
        '<div class="routing-protocol-head"><h2>Маршрутизация</h2>'
        '<p>Выберите подключение для настройки правил</p></div>'
        '<div class="routing-protocol-grid" role="group" aria-label="Выбор подключения">'
        +''.join(routing_tabs)+status_tile+'</div></section>')"""
OLD_STATUS="""        status_on=has_profile and profile.get('enabled')
        status_title='Маршрутизация включена' if status_on else 'Маршрутизация не подключена'
"""
OLD_HERO='''<section class="routing-hero"><div><span class="connection-protocol">{esc(protocol_title)}</span><h2>{esc(item.get('name','Подключение'))}</h2><p>Отметьте только те правила, которые нужно добавить или убрать.</p></div><div class="routing-status {'on' if status_on else ''}"><i></i><span><b>{status_title}</b><small>Изменения применяются только к выбранным пунктам</small></span></div></section>'''
NEW_HERO='''<section class="routing-hero"><div><span class="connection-protocol">{esc(protocol_title)}</span><h2>{esc(item.get('name','Подключение'))}</h2><p>Отметьте только те правила, которые нужно добавить или убрать.</p></div></section>'''
OLD_SHOW="""const show=()=>{{forms.forEach(form=>form.hidden=form.dataset.routingForm!==select.value);cards.forEach(card=>{{const active=card.dataset.routingChoice===select.value;card.classList.toggle('is-selected',active);card.setAttribute('aria-pressed',String(active))}})}};show();"""
NEW_SHOW="""const show=()=>{{forms.forEach(form=>form.hidden=form.dataset.routingForm!==select.value);cards.forEach(card=>{{const active=card.dataset.routingChoice===select.value;card.classList.toggle('is-selected',active);card.setAttribute('aria-pressed',String(active))}});const chosen=cards.find(card=>card.dataset.routingChoice===select.value);const enabled=chosen?.dataset.routingEnabled==='1';const status=document.getElementById('routingState');status?.classList.toggle('is-on',enabled);const title=document.getElementById('routingStateTitle');if(title)title.textContent=enabled?'Маршрутизация включена':'Маршрутизация отключена'}};show();"""
ANCHOR="</style>{chooser}<select id=\"routingConnection\" hidden"
CSS="""
/* wpo-routing-status-toprow-v3 */
.routing-protocol-section .routing-protocol-grid{
    grid-template-columns:repeat(5,minmax(0,1fr));gap:8px
}
.routing-protocol-section .routing-protocol-card{
    min-height:62px;padding:10px 11px;gap:8px
}
.routing-protocol-section .routing-tab-copy b{font-size:11px}
.routing-protocol-section .routing-tab-copy small{font-size:9px}
.routing-protocol-section .routing-protocol-status{
    display:flex;align-items:center;gap:8px;min-width:0;min-height:62px;
    padding:10px 11px;border:1px solid var(--line);border-radius:12px;
    background:var(--input);color:var(--text);box-shadow:none;
    cursor:default;pointer-events:none;user-select:none
}
.routing-protocol-section .routing-protocol-status .routing-tab-dot{
    border-color:#8394a9
}
.routing-protocol-section .routing-protocol-status .routing-tab-dot i{
    background:transparent
}
.routing-protocol-section .routing-protocol-status.is-on .routing-tab-dot{
    border-color:#22c55e;background:color-mix(in srgb,#22c55e 12%,transparent)
}
.routing-protocol-section .routing-protocol-status.is-on .routing-tab-dot i{
    background:#22c55e
}
@media(max-width:1150px){
    .routing-protocol-section .routing-protocol-grid{
        grid-template-columns:repeat(2,minmax(0,1fr))
    }
    .routing-protocol-section .routing-protocol-status{grid-column:2}
}
@media(max-width:650px){
    .routing-protocol-section .routing-protocol-card,
    .routing-protocol-section .routing-protocol-status{
        min-height:64px;padding:10px 9px;gap:7px
    }
}
"""

def replace_once(src, old, new, label):
    count=src.count(old)
    if count!=1:
        raise ValueError(f"Несовместимый UI: {label}, совпадений {count}. Ничего не изменено.")
    return src.replace(old,new,1)

def patch(source):
    start=source.find(FUNCTION)
    end=source.find("\n\ndef connections_ui(",start)
    if start<0 or end<0:
        raise ValueError("Раздел маршрутизации не найден")
    body=source[start:end]
    if body.count(MARKER)==1:
        ast.parse(source,filename="wpp_ui.py")
        if body.count('id="routingState"')!=1 or body.count('data-routing-enabled=')!=1:
            raise ValueError("Неполная установка статусной карточки")
        return source
    if MARKER in source:
        raise ValueError("Метка обновления уже присутствует вне маршрутизации")
    body=replace_once(body,OLD_TABS,NEW_TABS,"построение протоколов")
    body=replace_once(body,OLD_CARD,NEW_CARD,"переключатели")
    body=replace_once(body,OLD_CHOOSER,NEW_CHOOSER,"контейнер верхнего ряда")
    body=replace_once(body,OLD_STATUS,"","старый статус")
    body=replace_once(body,OLD_HERO,NEW_HERO,"блок подключения под предупреждением")
    body=replace_once(body,OLD_SHOW,NEW_SHOW,"смена протокола")
    body=replace_once(body,ANCHOR,CSS.replace("{","{{").replace("}","}}")+ANCHOR,
                      "стили верхнего ряда")
    updated=source[:start]+body+source[end:]
    ast.parse(updated,filename="wpp_ui.py")
    return updated

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=patch(args.input.read_text(encoding="utf-8"))
    args.output.write_text(result,encoding="utf-8")
    print("✓ Четыре компактные карточки протоколов и пятая статусная справа")
    print("✓ Статус не нажимается, не подсвечивается синим и меняется с протоколом")
    print("✓ Дублирующий блок статуса под красным предупреждением убран")
    print("✓ Маршруты, VPN, ключи и действия не изменены")

if __name__=="__main__":
    main()
