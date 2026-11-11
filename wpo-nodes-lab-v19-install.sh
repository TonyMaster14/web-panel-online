#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-divider-v18' "$UI" || { echo 'Сначала установите Nodes Lab v18. Ничего не изменено.'; exit 1; }

if grep -Fq '# wpo-node-server-icon-v19' "$UI"; then
  echo 'Nodes Lab v19 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v19-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: найдено {count} совпадений вместо одного. Исходник не изменён.')
    src=src.replace(old,new,1)

# Reuse the panel's server-rack icon, which is already drawn in the same
# SVG style and size as the site-template/settings icon.
once(
    '<p class="wpo-node-template wpo-main-node-label">Основная нода</p>',
    '<p class="wpo-node-template wpo-main-node-label">{icon("nodes")} Основная нода</p>',
    'Значок сервера перед подписью основной ноды')

# Keep all card measurements untouched. Tint only this new icon.
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    '\n/* wpo-node-server-icon-v19 */\n'
    '.wpo-nodes-page .wpo-main-node-label .ico{color:#38bdf8}\n'
    "'''\n    js=r'''(()=>{const path=__PATH__",
    'Голубой значок сервера')

once(
    '    # wpo-node-divider-v18\n    # wpo-node-compact-v6',
    '    # wpo-node-divider-v18\n    # wpo-node-server-icon-v19\n    # wpo-node-compact-v6',
    'Маркер v19')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes19tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Значок сервера добавлен к надписи "Основная нода".')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Обновление не применено: исходный интерфейс восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Проверка или перезапуск не удались: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v19: у основной ноды появился голубой значок сервера.'
echo "Резервная копия: $BACKUP"
echo 'Размеры и функции нод не изменены. GitHub main не затронут.'
