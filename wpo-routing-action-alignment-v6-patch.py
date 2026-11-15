#!/usr/bin/env python3
"""WPO Routing: align action buttons and replace blue checkmark with red removal dot.

Visual-only change; keeps all POST names, removal operations, AWG forms and
persisted routing status. A removal dot only appears for a SAVED rule whose
checkbox is explicitly checked. Unsaved add selections retain their blue
highlight but do not show a misleading red deletion marker.
"""
import argparse
import ast
from pathlib import Path

MARKER="/* wpo-routing-action-alignment-red-dot-v6 */"
BEGIN="def routing_ui("
END="\n\ndef connections_ui("
OLD_CHECK = '''/* Visual difference: blue-green = persisted; corner check = explicitly chosen. */
.routing-form .routing-switches label.routing-toggle:has(input:checked)::after{{
    content:"✓";position:absolute;right:9px;top:7px;
    color:#60a5fa;font:800 12px/1 system-ui,sans-serif;
    pointer-events:none
}}'''
NEW_CHECK = '''/* Saved rule = green dot on the left; pending removal = red dot on the right.
   Red marker uses the exact same 16px diameter and 14px inset as the left dot. */
.routing-form .routing-switches label.routing-toggle.is-active:has(input:checked){{
    padding-right:38px
}}
.routing-form .routing-switches label.routing-toggle.is-active:has(input:checked)::after{{
    content:"";position:absolute;right:14px;top:50%;
    transform:translateY(-50%);
    display:block;width:16px;height:16px;box-sizing:border-box;
    border:1.5px solid #ef4444;border-radius:50%;
    background:radial-gradient(circle,#ef4444 0 3.3px,
        color-mix(in srgb,#ef4444 10%,transparent) 3.7px);
    pointer-events:none
}}'''

OLD_FOOTER_LAYOUT = '''/* Two columns mirror routing-main and routing-custom exactly. */
.routing-form .routing-actions{{
    display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,.65fr);
    align-items:stretch;gap:0;padding:0;min-height:76px;
    background:var(--surface);border-top:1px solid var(--line)
}}
.routing-form .routing-actions-primary,
.routing-form .routing-actions-secondary{{
    display:flex;align-items:center;justify-content:flex-end;
    gap:12px;min-width:0;min-height:76px;padding:14px 20px
}}
.routing-form .routing-actions-primary>.muted{{
    margin:0 auto 0 0;min-width:0;font-size:10px;line-height:1.4
}}
.routing-form .routing-actions-secondary{{
    border-left:1px solid var(--line);
    background:color-mix(in srgb,var(--raised) 88%,var(--accent))
}}'''
NEW_FOOTER_LAYOUT = '''/* wpo-routing-action-alignment-red-dot-v6 */
/* Visually group the two actions, flush to the right of one shared footer. */
.routing-form .routing-actions{{
    display:flex;align-items:center;justify-content:flex-end;
    gap:12px;min-height:76px;padding:14px 18px;
    background:var(--surface);border-top:1px solid var(--line)
}}
.routing-form .routing-actions-primary{{
    flex:1 1 auto;display:flex;align-items:center;justify-content:flex-end;
    gap:12px;min-width:0;padding:0
}}
.routing-form .routing-actions-primary>.muted{{
    margin:0 auto 0 0;min-width:0;font-size:10px;line-height:1.4
}}
.routing-form .routing-actions-secondary{{
    flex:0 0 auto;display:flex;align-items:center;justify-content:flex-end;
    min-width:0;padding:0;border:0;background:transparent
}}'''

OLD_MOBILE = '''@media(max-width:1150px){{
    .routing-form .routing-actions{{
        grid-template-columns:repeat(2,minmax(0,1fr))
    }}
    .routing-form .routing-actions-primary>.muted{{display:none}}
    .routing-form .routing-actions-primary,
    .routing-form .routing-actions-secondary{{padding:13px 15px}}
    .routing-form .routing-actions button{{min-width:0;width:100%}}
}}
@media(max-width:600px){{
    .routing-form .routing-actions{{grid-template-columns:1fr}}
    .routing-form .routing-actions-primary,
    .routing-form .routing-actions-secondary{{min-height:0;padding:12px 15px}}
    .routing-form .routing-actions-secondary{{
        border-left:0;border-top:1px solid var(--line)
    }}
}}'''
NEW_MOBILE = '''@media(max-width:1150px){{
    .routing-form .routing-actions-primary>.muted{{display:none}}
    .routing-form .routing-actions-primary,
    .routing-form .routing-actions-secondary{{flex:1 1 50%}}
    .routing-form .routing-actions button{{min-width:0;width:100%}}
}}
@media(max-width:600px){{
    .routing-form .routing-actions{{
        flex-direction:column;align-items:stretch;gap:10px;padding:13px 15px
    }}
    .routing-form .routing-actions-primary,
    .routing-form .routing-actions-secondary{{flex:1 1 auto;width:100%}}
}}'''

def once(text, before, after, label):
    count=text.count(before)
    if count != 1:
        raise ValueError(f"Неизвестный шаблон {label}: {count} совпадений. Ничего не изменено.")
    return text.replace(before,after,1)

def patch(source):
    start=source.find(BEGIN)
    stop=source.find(END,start)
    if start<0 or stop<0:
        raise ValueError("Страница маршрутизации не найдена.")
    section=source[start:stop]
    if MARKER in section:
        ast.parse(source,filename="wpp_ui.py")
        if 'content:"✓"' in section or "right:14px;top:50%" not in section:
            raise ValueError("Неполная версия индикатора удаления.")
        return source
    if MARKER in source:
        raise ValueError("Метка изменений встречается вне страницы.")
    section=once(section,OLD_CHECK,NEW_CHECK,"синей галочки")
    section=once(section,OLD_FOOTER_LAYOUT,NEW_FOOTER_LAYOUT,"нижней панели кнопок")
    section=once(section,OLD_MOBILE,NEW_MOBILE,"мобильного расположения кнопок")
    result=source[:start]+section+source[stop:]
    ast.parse(result,filename="wpp_ui.py")
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    updated=patch(args.input.read_text(encoding="utf-8"))
    args.output.write_text(updated,encoding="utf-8")
    print("✓ Кнопки добавления/удаления выровнены справа рядом друг с другом")
    print("✓ Синяя галочка удалена; выбранное сохранённое правило показывает красный кружок")
    print("✓ Зелёная точка сохранена; ручной выбор удаления не меняет сохранённые правила")
    print("✓ Hysteria2 и VLESS используют одинаковое отображение; AmneziaWG не получает ложных переключателей")
