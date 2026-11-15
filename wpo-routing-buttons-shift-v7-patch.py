#!/usr/bin/env python3
"""Nudge routing action buttons 6px right, preserving mobile layout and actions."""
import argparse
import ast
from pathlib import Path

OLD = "gap:12px;min-height:76px;padding:14px 18px;"
NEW = "gap:12px;min-height:76px;padding:14px 12px 14px 18px; /* wpo-routing-buttons-shift-v7 */"
MARKER = "/* wpo-routing-buttons-shift-v7 */"

def patch(source):
    start = source.find("def routing_ui(")
    end = source.find("\n\ndef connections_ui(",start)
    if start < 0 or end < 0:
        raise ValueError("WPO Routing UI function not found")
    section = source[start:end]
    if MARKER in section:
        if section.count(MARKER) != 1 or NEW not in section:
            raise ValueError("Incomplete previous v7 patch")
        ast.parse(source, filename="wpp_ui.py")
        return source
    if section.count(OLD) != 1 or "wpo-routing-action-alignment-red-dot-v6" not in section:
        raise ValueError("Unexpected routing buttons version; no changes made")
    updated = source[:start] + section.replace(OLD, NEW, 1) + source[end:]
    ast.parse(updated, filename="wpp_ui.py")
    return updated

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(patch(args.input.read_text(encoding="utf-8")), encoding="utf-8")
    print("✓ Обе кнопки маршрутизации сдвинуты на 6 px вправо")
    print("✓ Промежуток, анимация, цвет и работа маршрутизации сохранены")

if __name__ == "__main__":
    main()
