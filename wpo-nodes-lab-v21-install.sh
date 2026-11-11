#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-server-icon-v19' "$UI" || { echo 'Нужен Nodes Lab v19 или новее. Изменений нет.'; exit 1; }
if grep -Fq '/* wpo-node-heading-v21 */' "$UI"; then
    echo 'Nodes Lab v21 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v21-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')
def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: ожидается 1 совпадение, найдено {n}; файл не изменён.')
    src=src.replace(old,new,1)

# Earlier live UI edits may already have removed the subtitle; in that case
# v21 must still apply the final spacing and alignment.
heading='<h2>⚙️ Управление нодами</h2>'
if src.count(heading)!=1 or 'def nodes_ui(' not in src:
    raise RuntimeError('Заголовок нод не найден однозначно. Файл не изменён.')
import re
subtitle_re=r'<p(?:\s[^>]*)?>\s*Подключённые серверы и состояние установок\s*</p>'
# Keep any other page or help text untouched: this is restricted to nodes_ui.
start=src.index('def nodes_ui(')
end=src.index('\n\nCSS +=',start)
section=src[start:end]
section,removed=re.subn(subtitle_re,'',section)
if removed>1:
    raise RuntimeError('У подписи найдено более одного совпадения; файл не изменён.')
src=src[:start]+section+src[end:]
print('Подпись раздела:', 'удалена' if removed else 'уже отсутствовала')

css="""
/* wpo-node-heading-v21: start on left edge of first stats tile */
.wpo-nodes-page .wpo-nodes-toolbar > div:first-child{
    margin-left:0;
    padding-left:0;
    min-width:0;
}
.wpo-nodes-page .wpo-nodes-toolbar .eyebrow{margin-bottom:0}
.wpo-nodes-page .wpo-nodes-toolbar h2{
    margin:10px 0 0;
    line-height:1.3;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Отступ и левое выравнивание заголовка')

compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes21tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Подпись удалена; заголовок ниже и выровнен по левому краю блока «В сети».')
PY_PATCH
then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    echo 'Ошибка правки. Исходный файл восстановлен.'
    exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    echo 'Ошибка проверки или запуска. Выполнен откат.'
    exit 1
fi
echo 'Nodes Lab v21: подпись удалена, заголовок выровнен.'
echo "Резервная копия: $BACKUP"
echo 'Работа нод и ветка GitHub main не изменены.'
