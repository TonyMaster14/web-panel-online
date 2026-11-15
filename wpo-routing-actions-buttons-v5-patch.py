#!/usr/bin/env python3
"""Routing footer buttons: blue add, red remove, creator-style lift on hover.

UI-only, exact-match edit of the WPO Routing section. It leaves all
POST names/values, saved routing logic, JS event listeners and VPN code intact.
"""
import argparse
import ast
from pathlib import Path

MARKER="/* wpo-routing-actions-buttons-v5 */"
BEGIN="def routing_ui("
END="\n\ndef connections_ui("
OLD_FOOTER='''<footer class="routing-actions"><span class="muted">Выберите пункты, затем добавьте или уберите только их.</span><button class="routing-add" type="submit" name="operation" value="add-selected" disabled>Добавить маршрутизацию</button><button class="danger" type="submit" name="operation" value="remove-selected" disabled>Убрать маршрутизацию</button></footer></form>'''
NEW_FOOTER='''<footer class="routing-actions"><div class="routing-actions-primary"><span class="muted">Выберите пункты, затем добавьте или уберите только их.</span><button class="routing-add" type="submit" name="operation" value="add-selected" disabled>Добавить маршрутизацию</button></div><div class="routing-actions-secondary"><button class="danger" type="submit" name="operation" value="remove-selected" disabled>Убрать маршрутизацию</button></div></footer></form>'''
ANCHOR='''</style>{chooser}<select id="routingConnection" hidden'''
CSS="""
/* wpo-routing-actions-buttons-v5 */
/* Two columns mirror routing-main and routing-custom exactly. */
.routing-form .routing-actions{
    display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,.65fr);
    align-items:stretch;gap:0;padding:0;min-height:76px;
    background:var(--surface);border-top:1px solid var(--line)
}
.routing-form .routing-actions-primary,
.routing-form .routing-actions-secondary{
    display:flex;align-items:center;justify-content:flex-end;
    gap:12px;min-width:0;min-height:76px;padding:14px 20px
}
.routing-form .routing-actions-primary>.muted{
    margin:0 auto 0 0;min-width:0;font-size:10px;line-height:1.4
}
.routing-form .routing-actions-secondary{
    border-left:1px solid var(--line);
    background:color-mix(in srgb,var(--raised) 88%,var(--accent))
}
/* Same elevation and animation as the Create User primary action. */
.routing-form .routing-actions button{
    flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;
    min-width:210px;min-height:46px;padding:12px 20px;
    border:1px solid transparent;border-radius:11px;
    color:#fff;font-size:12px;font-weight:700;line-height:1.3;
    white-space:nowrap;text-align:center;
    box-shadow:0 4px 12px #0003;
    transition:transform .2s cubic-bezier(.2,.75,.25,1),
               background-color .18s ease,border-color .18s ease,
               box-shadow .2s ease,filter .18s ease
}
.routing-form .routing-actions button.routing-add{
    border-color:#3b82f6;background:#2563eb;color:#fff
}
.routing-form .routing-actions button.danger{
    border-color:#e24d61;background:#c9364f;color:#fff
}
@media(hover:hover) and (pointer:fine){
    .routing-form .routing-actions button:hover:not(:disabled){
        transform:translateY(-2px);
        box-shadow:0 9px 20px #0005;
        filter:brightness(1.08)
    }
    .routing-form .routing-actions button.routing-add:hover:not(:disabled){
        border-color:#60a5fa;background:#3478f6
    }
    .routing-form .routing-actions button.danger:hover:not(:disabled){
        border-color:#ff8190;background:#df405a!important
    }
}
.routing-form .routing-actions button:active:not(:disabled){
    transform:translateY(0);box-shadow:0 2px 7px #0003
}
.routing-form .routing-actions button:disabled{
    opacity:.42;box-shadow:none;cursor:not-allowed
}
@media(max-width:1150px){
    .routing-form .routing-actions{
        grid-template-columns:repeat(2,minmax(0,1fr))
    }
    .routing-form .routing-actions-primary>.muted{display:none}
    .routing-form .routing-actions-primary,
    .routing-form .routing-actions-secondary{padding:13px 15px}
    .routing-form .routing-actions button{min-width:0;width:100%}
}
@media(max-width:600px){
    .routing-form .routing-actions{grid-template-columns:1fr}
    .routing-form .routing-actions-primary,
    .routing-form .routing-actions-secondary{min-height:0;padding:12px 15px}
    .routing-form .routing-actions-secondary{
        border-left:0;border-top:1px solid var(--line)
    }
}
@media(prefers-reduced-motion:reduce){
    .routing-form .routing-actions button{transition:none}
    .routing-form .routing-actions button:hover:not(:disabled){transform:none}
}
"""

def replace_once(source,old,new,what):
    occurrences=source.count(old)
    if occurrences!=1:
        raise ValueError(f"Неизвестный шаблон {what}: совпадений {occurrences}")
    return source.replace(old,new,1)

def patch(source):
    begin=source.find(BEGIN)
    end=source.find(END,begin)
    if begin<0 or end<0:
        raise ValueError("Страница маршрутизации не найдена.")
    section=source[begin:end]
    if MARKER in section:
        if "routing-actions-primary" not in section or "routing-actions-secondary" not in section:
            raise ValueError("Неполная версия интерфейса кнопок.")
        ast.parse(source,filename="wpp_ui.py")
        return source
    if MARKER in source:
        raise ValueError("Метка стилей уже встречается вне страницы.")
    section=replace_once(section,OLD_FOOTER,NEW_FOOTER,"кнопок маршрутизации")
    section=replace_once(section,ANCHOR,CSS.replace("{","{{").replace("}","}}")+ANCHOR,
                         "нового CSS")
    result=source[:begin]+section+source[end:]
    ast.parse(result,filename="wpp_ui.py")
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    source=args.input.read_text(encoding="utf-8")
    updated=patch(source)
    args.output.write_text(updated,encoding="utf-8")
    print("✓ Добавить маршрутизацию: крупная синяя кнопка с подъёмом")
    print("✓ Убрать маршрутизацию: крупная красная кнопка с подъёмом")
    print("✓ Кнопки выровнены по границам панелей правил и исключений")
    print("✓ POST-поля и логика удаления/добавления не изменены")
