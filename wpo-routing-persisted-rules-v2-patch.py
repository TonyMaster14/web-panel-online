#!/usr/bin/env python3
"""Visual-only WPO Routing V2.

Saved routing rules retain blue card borders and green dot after POST/reload.
Pending checkbox selections remain independent (old backend semantics).
The red alert has a uniform thin border; routing hero is dark/consistent.
No configuration, user, keys or routing persistence changes.
"""
import argparse
import ast
from pathlib import Path

MARKER = "/* wpo-routing-persisted-rules-v2 */"
ANCHOR = """</style>{chooser}<select id="routingConnection" hidden"""
CSS = """
/* wpo-routing-persisted-rules-v2 */
/* Equal red border on all four sides; do not draw the prior thick left bar. */
.routing-form .routing-client-notice{
    border:1px solid color-mix(in srgb,var(--red) 52%,var(--line));
    border-radius:13px;
    box-shadow:none;
}
/* The red alert flows into the dark heading, without the blue hero wash. */
.routing-form{background:var(--surface)}
.routing-form .routing-hero{background:var(--surface)}
/* Saved routing rules (.is-active) keep the SAME blue/green selected visuals
   as a pending checkbox. The checkbox stays a delta control for add/remove. */
.routing-form .routing-switches label.routing-toggle.is-active,
.routing-form .routing-switches label.routing-toggle:has(input:checked){
    border-color:#3b82f6;
    background:color-mix(in srgb,#3b82f6 15%,var(--input));
    box-shadow:inset 0 0 0 1px color-mix(in srgb,#3b82f6 45%,transparent);
}
.routing-form .routing-switches label.routing-toggle.is-active .routing-rule-dot,
.routing-form .routing-switches label.routing-toggle:has(input:checked) .routing-rule-dot{
    border-color:#22c55e;
    background:color-mix(in srgb,#22c55e 10%,transparent);
}
.routing-form .routing-switches label.routing-toggle.is-active .routing-rule-dot i,
.routing-form .routing-switches label.routing-toggle:has(input:checked) .routing-rule-dot i{
    background:#22c55e;
}
"""

def patch(source):
    begin=source.find("def routing_ui(")
    if begin<0:
        raise ValueError("Не найден раздел маршрутизации.")
    end=source.find("\n\ndef connections_ui(",begin)
    if end<0:
        raise ValueError("Не найден конец раздела маршрутизации.")
    segment=source[begin:end]
    if segment.count(MARKER)==1:
        ast.parse(source,filename="wpp_ui.py")
        return source
    if MARKER in source:
        raise ValueError("Неоднозначная версия стилей маршрутизации.")
    if segment.count(ANCHOR)!=1 or "class=\"routing-toggle{active(" not in segment:
        raise ValueError("Неизвестная версия UI маршрутизации. Ничего не изменено.")
    escaped=CSS.replace("{","{{").replace("}","}}")
    segment=segment.replace(ANCHOR,escaped+ANCHOR,1)
    result=source[:begin]+segment+source[end:]
    ast.parse(result,filename="wpp_ui.py")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    updated=patch(args.input.read_text(encoding="utf-8"))
    args.output.write_text(updated,encoding="utf-8")
    print("✓ Сохранённые маршруты: синий контур и зелёная точка после добавления")
    print("✓ Красное предупреждение: ровная рамка без толстой полосы слева")
    print("✓ Под предупреждением и заголовком: ровный тёмный фон")
    print("✓ API, ключи, применённые маршруты, добавление и удаление не изменены")

if __name__=="__main__":
    main()
