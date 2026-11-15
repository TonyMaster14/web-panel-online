#!/usr/bin/env python3
"""WPO Routing: make the Custom Exceptions sidebar an inset rounded card.

UI/CSS only. Keeps textarea names, all POST behavior, routing data,
protocol cards and footer button alignment intact.
"""
import argparse
import ast
from pathlib import Path

MARKER="/* wpo-routing-custom-inset-v8 */"
BEGIN="def routing_ui("
END="\n\ndef connections_ui("
ANCHOR="</style>{chooser}<select id=\"routingConnection\" hidden"
CSS="""
/* wpo-routing-custom-inset-v8 */
/* Mirror the 16px air around the rule cards; unlike the older full-height
   blue sidebar, this card has its own thin outline and rounded corners. */
.routing-form .routing-layout .routing-custom{
    align-self:stretch;min-width:0;
    margin:16px 16px 16px 0;
    padding:17px 16px;
    border:1px solid var(--line);
    border-radius:13px;
    background:color-mix(in srgb,var(--raised) 88%,var(--accent));
    box-shadow:0 5px 16px #00000016
}
.routing-form .routing-layout .routing-custom h2{
    margin-top:0;
}
.routing-form .routing-layout .routing-custom textarea{
    box-sizing:border-box;max-width:100%
}
@media(max-width:1150px){
    /* The layout stacks here, so inset both sides equally. */
    .routing-form .routing-layout .routing-custom{
        margin:0 16px 16px;
        border:1px solid var(--line);
    }
}
@media(max-width:650px){
    .routing-form .routing-layout .routing-custom{
        margin:0 12px 12px;padding:14px 13px;border-radius:12px
    }
}
"""

def patch(source):
    a=source.find(BEGIN)
    b=source.find(END,a)
    if a<0 or b<0:
        raise ValueError("Страница маршрутизации не найдена")
    part=source[a:b]
    if MARKER in part:
        if part.count(MARKER)!=1 or "margin:16px 16px 16px 0;" not in part:
            raise ValueError("Неполное обновление блока исключений")
        ast.parse(source,filename="wpp_ui.py")
        return source
    if MARKER in source or part.count(ANCHOR)!=1:
        raise ValueError("Неизвестная версия интерфейса: ничего не изменено")
    if '<aside class="routing-custom"><h2>Свои исключения</h2>' not in part:
        raise ValueError("Неизвестная разметка исключений")
    updated=source[:a]+part.replace(ANCHOR,CSS.replace("{","{{").replace("}","}}")+ANCHOR,1)+source[b:]
    ast.parse(updated,filename="wpp_ui.py")
    return updated

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    args.output.write_text(patch(args.input.read_text(encoding="utf-8")),encoding="utf-8")
    print("✓ Блок «Свои исключения» скруглён и уменьшен отступами с четырёх сторон")
    print("✓ Положение согласовано с карточками слева и кнопками снизу")
    print("✓ Домены, маршруты, кнопки и подключения не изменены")

if __name__=="__main__":
    main()
