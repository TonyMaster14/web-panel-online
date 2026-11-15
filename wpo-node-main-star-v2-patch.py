#!/usr/bin/env python3
"""WPO Nodes Lab: reliable yellow main-node star AFTER its name.

Handles already-upgraded and legacy v15-v26 pages, adds an explicit stylesheet
revision, validates the actual rendered card. No VPN/config/user modifications.
"""
import argparse
import ast
import re
from pathlib import Path

OLD_MARKUP = (
    '<span class="wpo-node-flag wpo-node-main-flag">{esc(node_flag(lc))}'
    '<span class="wpo-node-main-mark" title="Основная нода" aria-label="Основная нода">★</span>'
    '</span><div class="wpo-node-label"><h3>{esc(lname)}</h3>'
)
NEW_MARKUP = (
    '<span class="wpo-node-flag">{esc(node_flag(lc))}</span>'
    '<div class="wpo-node-label"><h3><span class="wpo-node-main-name">'
    '{esc(lname)}</span> <span class="wpo-node-main-star"'
    ' title="Основная нода" aria-label="Основная нода">★</span></h3>'
)
MARKER = "/* wpo-node-star-after-name-v2 */"
STYLE = """
/* wpo-node-star-after-name-v2 */
.wpo-nodes-page .wpo-node-card-head .wpo-node-flag .wpo-node-main-mark{
    display:none!important
}
.wpo-nodes-page .wpo-node-label h3:has(.wpo-node-main-star){
    display:flex!important;align-items:center!important;gap:6px!important;
    min-width:0
}
.wpo-nodes-page .wpo-node-label .wpo-node-main-name{
    min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap
}
.wpo-nodes-page .wpo-node-label .wpo-node-main-star{
    flex:0 0 auto;display:inline-flex;align-items:center;
    color:#facc15!important;font:750 15px/1 system-ui,sans-serif
}
"""


def patch(src):
    if src.count(MARKER) == 1 and src.count(NEW_MARKUP) == 1:
        ast.parse(src, filename="wpp_ui.py")
        return src
    start = src.find("def nodes_ui(")
    if start < 0:
        raise ValueError("Страница нод не найдена. Ничего не изменено.")
    stop = src.find("\n\nCSS +=", start)
    if stop < 0:
        raise ValueError("Не найдено завершение разметки нод.")
    main = src[start:stop]
    if main.count(NEW_MARKUP) == 1:
        pass
    elif main.count(OLD_MARKUP) == 1:
        main = main.replace(OLD_MARKUP, NEW_MARKUP, 1)
        src = src[:start] + main + src[stop:]
    else:
        raise ValueError("Неизвестная разметка основной ноды. Изменения не внесены.")
    if MARKER not in src:
        # Insert before final stylesheet hash to force a new CSS asset URL;
        # no reliance on an existing v15 style block matching byte-for-byte.
        anchors=list(re.finditer(
            r"(?m)^ASSET_REV\s*=\s*hashlib\.sha256\(\(CSS\s*\+\s*COMMON_JS\)",
            src))
        if not anchors:
            raise ValueError("Нельзя безопасно обновить версию CSS.")
        i=anchors[-1].start()
        src=src[:i]+"CSS += "+repr(STYLE)+"\n\n"+src[i:]
    if src.count(NEW_MARKUP) != 1 or src.count(MARKER) != 1:
        raise ValueError("Звезда или таблица стилей не установлена однозначно.")
    ast.parse(src, filename="wpp_ui.py")
    return src


def verify(source):
    """Render the real Nodes page without requiring credentials or HTTP."""
    import importlib.util
    import sys
    import tempfile
    with tempfile.TemporaryDirectory(prefix="wpo-star-verify-") as folder:
        p=Path(folder)/"wpp_ui.py"
        p.write_text(source,encoding="utf-8")
        spec=importlib.util.spec_from_file_location("wpo_star_verify",p)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        html=module.nodes_ui(
            [],{"country_name":"Нидерланды","country_code":"NL"},
            "example.test","/panel-demo","demo")
        if '<span class="wpo-node-main-star"' not in html:
            raise ValueError("Созданная страница не содержит звезду после названия.")
        head=html.split('class="wpo-node-card-head"',1)
        if len(head)<2:
            raise ValueError("Разметка карточки ноды отсутствует.")
        head=head[1].split('data-node-status="local"',1)[0]
        if not re.search(
            r'<span class="wpo-node-flag"[^>]*>[^<]+</span>'
            r'<div class="wpo-node-label"><h3><span class="wpo-node-main-name">'
            r'Нидерланды</span>\s*<span class="wpo-node-main-star"',
            head
        ):
            raise ValueError("Звезда всё ещё около флага или не в заголовке.")
        if ".wpo-node-main-star" not in module.CSS or "#facc15" not in module.CSS:
            raise ValueError("CSS для жёлтой звезды не применён.")
        return True


def main():
    arg=argparse.ArgumentParser()
    arg.add_argument("--input",type=Path,required=True)
    arg.add_argument("--output",type=Path,required=True)
    args=arg.parse_args()
    current=args.input.read_text(encoding="utf-8")
    upgraded=patch(current)
    verify(upgraded)
    args.output.write_text(upgraded,encoding="utf-8")
    print("✓ Проверено HTML: Нидерланды ★, звезда после названия")
    print("✓ Проверено CSS: жёлтая звезда #facc15, новая версия стилей")
    print("✓ Изменены только карточка и CSS, без изменения VPN или пользователей")


if __name__ == "__main__":
    main()
