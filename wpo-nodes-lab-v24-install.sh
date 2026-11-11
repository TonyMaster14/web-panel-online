#!/usr/bin/env bash
# Nodes Lab v24 — center spinner/error ring within installation flag tile.
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба $SERVICE"; exit 1; }
grep -Fq '/* wpo-node-pending-row-v22 */' "$UI" || { echo 'Нужен Nodes Lab v22 или новее.'; exit 1; }

if grep -Fq '/* wpo-node-indicator-center-v24 */' "$UI"; then
    echo 'Nodes Lab v24 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v24-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
anchor="'''\n    js=r'''(()=>{const path=__PATH__"
if src.count(anchor)!=1:
    raise RuntimeError('Не найдено единственное место для стилей нод; интерфейс не изменён.')
if src.count('/* wpo-node-pending-row-v22 */')!=1:
    raise RuntimeError('Не найден базовый стиль v22; интерфейс не изменён.')

css=r"""
/* wpo-node-indicator-center-v24 */
/* Keep the tile size untouched: only center the circular spinner / error icon. */
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag {
    display:grid;
    place-items:center;
    align-items:center;
    justify-items:center;
    padding:0;
    line-height:0;
    position:relative;
    box-sizing:border-box;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag::after {
    display:grid;
    place-items:center;
    justify-self:center;
    align-self:center;
    width:20px;
    height:20px;
    box-sizing:border-box;
    margin:0;
    flex:none;
    border-radius:50%;
    transform-origin:50% 50%;
}
.wpo-nodes-page .wpo-pending-node:has(.wpo-node-status.error) .wpo-node-flag::after {
    display:grid;
    place-items:center;
    font:700 12px/1 system-ui,sans-serif;
    text-align:center;
    animation:none;
}
"""
updated=src.replace(anchor, css+"\n"+anchor, 1)
compile(updated,str(p),'exec')
tmp=p.with_suffix('.py.nodes24tmp')
tmp.write_text(updated,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Индикатор установки и красный значок ошибки выровнены по центру квадрата.')
PY_PATCH
then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    echo 'Ошибка правки, исходный интерфейс восстановлен.'
    exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    echo 'Ошибка проверки или запуска. Исходный интерфейс восстановлен.'
    exit 1
fi
echo 'Nodes Lab v24 установлен. Кружочки строго по центру; размеры карточек не менялись.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main и установщик Node Agent не изменены.'
