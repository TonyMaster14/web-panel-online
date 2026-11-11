#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-compact-v6' "$UI" || { echo 'Требуется установленный Nodes Lab v6. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v7-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-width-v7' in src:
    print('Ширина Nodes Lab v7 уже установлена.')
    raise SystemExit(0)

def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: найдено {n} совпадений вместо одного. Ничего не изменено.')
    src=src.replace(old,new,1)

# One node is as wide as a single "В сети" counter card. Keep two columns, their order,
# the height, padding, text, and node controls untouched.
once(
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,calc((100% - 36px)/5)));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    'Ширина ноды как у блока В сети')
# The five counters become three at tablet width, so keep matching their widths there.
once(
    '@media(max-width:850px){.wpo-node-stats{grid-template-columns:repeat(3,1fr)}}',
    '@media(max-width:850px){.wpo-node-stats{grid-template-columns:repeat(3,1fr)}.wpo-node-grid{grid-template-columns:repeat(2,minmax(0,calc((100% - 18px)/3)))}}',
    'Адаптация ширины нод на планшете')
# Existing mobile single-column layout is preserved.
once(
    '    # wpo-node-compact-v6\n    css=',
    '    # wpo-node-compact-v6\n    # wpo-node-width-v7\n    css=',
    'Метка v7')
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes7tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Изменена только ширина карточек нод. Высота и содержимое сохранены.')
PY_PATCH
then
    echo 'Проверка не пройдена. Восстанавливаю исходный файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Проверка или перезапуск не удались. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi

echo "Ширина нод обновлена. Резервная копия: $BACKUP"
echo 'Основная ветка main не изменена.'
