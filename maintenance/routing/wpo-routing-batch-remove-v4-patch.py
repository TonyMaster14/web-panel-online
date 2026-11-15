#!/usr/bin/env python3
"""Fix WPO Routing batch delete and display a red indicator when disabled.

Adds an explicit remove-all operation for highlighted saved routing settings,
while preserving remove-selected for individually checked rules. No changes to
client links, node state, VPN provisioning or the existing routing algorithms.
"""
import argparse
import ast
from pathlib import Path

UI_MARKER="/* wpo-routing-batch-remove-v4 */"
APP_MARKER="# wpo-routing-explicit-remove-all-v4"

OLD_FORM='''<form class="routing-form" data-routing-form="{esc(item['id'])}" method="post" action="{esc(path)}/routing-action" {'hidden' if index else ''}>'''
NEW_FORM='''<form class="routing-form" data-routing-form="{esc(item['id'])}" data-routing-stored="{"1" if has_profile and profile.get('enabled') else "0"}" method="post" action="{esc(path)}/routing-action" {'hidden' if index else ''}>'''

OLD_HANDLER='''                elif operation=="remove-selected": routing_store.update_selected(ROUTING_FILE,connection_id,form,remove=True)
                else: raise routing_store.RoutingError("Неизвестная операция маршрутизации.")'''
NEW_HANDLER='''                elif operation=="remove-selected": routing_store.update_selected(ROUTING_FILE,connection_id,form,remove=True)
                # wpo-routing-explicit-remove-all-v4: remove the whole selected
                # connection's routing profile, including custom exceptions.
                # AWG is managed by its own AllowedIPs update action only.
                elif operation=="remove-all" and not is_awg: routing_store.delete_profile(ROUTING_FILE,connection_id)
                else: raise routing_store.RoutingError("Неизвестная операция маршрутизации.")'''

OLD_SCRIPT="""const update=()=>{{const chosen=fields.some(field=>field.type==='checkbox'?field.checked:Boolean(field.value.trim()));buttons.forEach(button=>button.disabled=!chosen)}};fields.forEach(field=>field.addEventListener(field.type==='checkbox'?'change':'input',update));form.addEventListener('submit',event=>{{if(event.submitter?.value==='remove-selected'&&!confirm('Убрать только выбранные правила маршрутизации? Остальные настройки останутся без изменений.'))event.preventDefault()}});update()"""
NEW_SCRIPT="""const update=()=>{{const chosen=fields.some(field=>field.type==='checkbox'?field.checked:Boolean(field.value.trim()));const saved=form.dataset.routingStored==='1';buttons.forEach(button=>button.disabled=!(chosen||(button.value==='remove-selected'&&saved)))}};fields.forEach(field=>field.addEventListener(field.type==='checkbox'?'change':'input',update));form.addEventListener('submit',event=>{{const button=event.submitter;if(button?.value!=='remove-selected')return;const specific=fields.some(field=>field.type==='checkbox'?field.checked:Boolean(field.value.trim()));if(!specific&&form.dataset.routingStored==='1'){{if(!confirm('Удалить всю маршрутизацию выбранного подключения, включая сохранённые исключения?')){{event.preventDefault();return}}button.value='remove-all'}}else if(!confirm('Убрать только выбранные правила маршрутизации? Остальные настройки останутся без изменений.'))event.preventDefault()}});update()"""

CSS="""
/* wpo-routing-batch-remove-v4 */
/* Visual difference: blue-green = persisted; corner check = explicitly chosen. */
.routing-form .routing-switches label.routing-toggle:has(input:checked)::after{
    content:"✓";position:absolute;right:9px;top:7px;
    color:#60a5fa;font:800 12px/1 system-ui,sans-serif;
    pointer-events:none
}
/* Disabled routing is a real red status, not a neutral inactive dot. */
.routing-protocol-section .routing-protocol-status:not(.is-on) .routing-tab-dot{
    border-color:#ef4444;background:color-mix(in srgb,#ef4444 12%,transparent)
}
.routing-protocol-section .routing-protocol-status:not(.is-on) .routing-tab-dot i{
    background:#ef4444
}
"""

def replace_once(src, old, new, key):
    matches=src.count(old)
    if matches != 1:
        raise ValueError(f"Несовместимая версия WPO: {key} ({matches} совпадений)")
    return src.replace(old,new,1)

def patch_ui(src):
    start=src.find("def routing_ui(")
    end=src.find("\n\ndef connections_ui(", start)
    if start<0 or end<0:
        raise ValueError("Не найдена страница маршрутизации")
    body=src[start:end]
    if body.count(UI_MARKER)==1:
        if body.count("data-routing-stored=")!=1 or "button.value='remove-all'" not in body:
            raise ValueError("Неполная предыдущая версия исправления")
        ast.parse(src,filename="wpp_ui.py")
        return src
    if UI_MARKER in src:
        raise ValueError("Неожиданное расположение маркера маршрутизации")
    body=replace_once(body,OLD_FORM,NEW_FORM,"передача сохранённого состояния")
    body=replace_once(body,OLD_SCRIPT,NEW_SCRIPT,"действие удаления")
    anchor="</style>{chooser}<select id=\"routingConnection\" hidden"
    body=replace_once(body,anchor,CSS.replace("{","{{").replace("}","}}")+anchor,
                      "цвет отключённого статуса и индикатор выбора")
    out=src[:start]+body+src[end:]
    ast.parse(out,filename="wpp_ui.py")
    return out

def patch_app(src):
    if APP_MARKER in src:
        ast.parse(src,filename="panel.py")
        return src
    out=replace_once(src,OLD_HANDLER,NEW_HANDLER,"удаление маршрутизации на сервере")
    ast.parse(out,filename="panel.py")
    return out

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--ui-input",type=Path,required=True)
    parser.add_argument("--ui-output",type=Path,required=True)
    parser.add_argument("--app-input",type=Path,required=True)
    parser.add_argument("--app-output",type=Path,required=True)
    args=parser.parse_args()
    ui=patch_ui(args.ui_input.read_text(encoding="utf-8"))
    app=patch_app(args.app_input.read_text(encoding="utf-8"))
    args.ui_output.write_text(ui,encoding="utf-8")
    args.app_output.write_text(app,encoding="utf-8")
    print("✓ Удаление выбранных правил и отдельное удаление всех сохранённых правил")
    print("✓ После удаления всей маршрутизации точка статуса становится красной")
    print("✓ Неизменённые протоколы, ключи и VPN-подключения сохранены")

if __name__=="__main__":
    main()
