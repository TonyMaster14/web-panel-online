#!/usr/bin/env python3
"""Remove WPO's lingering «Проверяем…» UI text while keeping real checks."""
import argparse
import ast
from pathlib import Path

MARKER="# wpo-quiet-checking-label-v1"
REPLACEMENTS=(
    ("Применяем «'+name+'» и проверяем опубликованный сайт…",
     "Применяем «'+name+'»…"),
    ("Сайт загружен на сервер. Проверяем домен через HTTPS…",
     "Сайт загружен на сервер…"),
    ("Проверяем опубликованные релизы…",""),
    ("Проверяем версии компонентов…",""),
)

def patch(source):
    if MARKER in source:
        ast.parse(source,filename="wpp_ui.py")
        return source
    changes=0
    for old,new in REPLACEMENTS:
        count=source.count(old)
        if count>1:
            raise ValueError("Duplicate WPO status text; no changes made")
        if count:
            source=source.replace(old,new,1)
            changes+=1
    if not changes:
        # Don't change unrelated or newer UI releases.
        ast.parse(source,filename="wpp_ui.py")
        return source
    anchor="VERSION = '3.0.0'"
    if anchor in source:
        source=source.replace(anchor,anchor+"\n"+MARKER,1)
    ast.parse(source,filename="wpp_ui.py")
    return source

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    original=args.input.read_text(encoding="utf-8")
    result=patch(original)
    args.output.write_text(result,encoding="utf-8")
    print("✓ Убраны лишние надписи «Проверяем…»; реальные проверки сохранены" if result!=original else
          "✓ Лишних надписей «Проверяем…» в поддерживаемом интерфейсе нет")
