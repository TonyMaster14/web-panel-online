#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-aligned-v9' "$UI" || { echo 'Требуется установленный Nodes Lab v9 или новее. Ничего не изменено.'; exit 1; }

if grep -Fq '# wpo-node-visual-v14' "$UI"; then
  echo 'Nodes Lab v14 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v14-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    hits=src.count(old)
    if hits!=1:
        raise RuntimeError(f'{label}: найдено {hits} совпадений вместо одного. Файл не изменён.')
    src=src.replace(old,new,1)

# Preserve both node columns and their existing widths; stretch each card in
# one grid row to the height of the taller card.
once(
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,calc((100% - 36px)/5)));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,calc((100% - 36px)/5)));gap:12px;align-items:stretch;justify-content:start;grid-auto-flow:row}',
    'Одинаковая высота Нидерландов и Чехии')

# On additional nodes, the status becomes the right-most control in the header.
# The primary node markup is intentionally left untouched.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div><div class="wpo-node-head-tools">{status(uid,state)}<div class="wpo-node-actions">{edit}{delete}</div></div></div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    'Статус дополнительной ноды справа')

# Restore the clean site-template line, remove version and dot separator,
# and put only edit/delete controls at the bottom-right of additional cards.
once(
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)} · Агент {esc(n.get("version","—"))}</p></div>',
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p></div><div class="wpo-node-card-bottom"><div class="wpo-node-actions">{edit}{delete}</div></div>',
    'Шаблон сайта по центру, кнопки снизу справа')

once(
    '.wpo-node-actions{display:flex;align-items:center;gap:3px}.wpo-node-actions form{margin:0}',
    '.wpo-node-actions{display:flex;align-items:center;gap:3px}.wpo-node-actions form{margin:0}\n'
    '/* wpo-node-visual-v14: only additional-node footers and template labels */\n'
    '.wpo-nodes-page .wpo-node-card-bottom{display:flex;align-items:center;justify-content:flex-end;min-height:29px;margin-top:auto;padding:5px 0 0;border:0;background:transparent}\n'
    '.wpo-nodes-page .wpo-node-card-bottom .wpo-node-actions{margin-left:auto;justify-content:flex-end}\n'
    '.wpo-nodes-page .wpo-node-template{text-align:center;margin:6px 0 0;line-height:1.35}\n'
    '.wpo-nodes-page .wpo-node-template .ico{vertical-align:-2px;margin-right:2px}',
    'Позиционирование действий и названия шаблона')

once(
    '    # wpo-node-aligned-v9\n    # wpo-node-compact-v6',
    '    # wpo-node-aligned-v9\n    # wpo-node-visual-v14\n    # wpo-node-compact-v6',
    'Маркер версии v14')

compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes14tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Готово: карточки одной высоты, статус справа, кнопки внизу, только название сайта.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Правка не применена: файл восстановлен из резервной копии.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Не пройдена проверка или запуск панели: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v14: визуальные правки карточек нод применены.'
echo "Резервная копия: $BACKUP"
echo 'Node Agent и подключения не изменены. GitHub main не затронута.'
