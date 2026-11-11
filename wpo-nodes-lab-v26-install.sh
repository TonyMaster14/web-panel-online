#!/usr/bin/env bash
# Nodes Lab v26 — center the yellow installation spinner and red error icon.
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Не найдена служба панели WPO.'; exit 1; }
grep -Fq '/* wpo-node-indicator-center-v24 */' "$UI" || {
    echo 'Сначала установите Nodes Lab v24 или новее.'; exit 1;
}
if grep -Fq '/* wpo-node-spinner-center-v26 */' "$UI"; then
    echo 'Nodes Lab v26 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v26-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')

# The actual issue: the old diamond glyph becomes an anonymous *first*
# CSS-grid item (even with font-size:0); ::after is laid out in a second row.
# Remove it entirely so the animated ring is the only item in the flag tile.
old='<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3></div>{status(uid,state)}</div>'
new='<div class="wpo-node-card-head"><span class="wpo-node-flag" aria-hidden="true"></span><div class="wpo-node-label"><h3>Установка</h3></div>{status(uid,state)}</div>'
if src.count(old)!=1:
    raise RuntimeError('Не найдена единственная карточка установки версии v22. Файл не изменён.')
src=src.replace(old,new,1)

# The spinner rotates using transform; using flex centering on the PARENT
# means transform rotation cannot override a translate-based centering.
css=r"""
/* wpo-node-spinner-center-v26 */
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag{
    display:flex;
    align-items:center;
    justify-content:center;
    padding:0;
    line-height:0;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag::after{
    position:static;
    display:block;
    flex:0 0 20px;
    width:20px;
    height:20px;
    margin:0;
    box-sizing:border-box;
    transform-origin:center center;
}
.wpo-nodes-page .wpo-pending-node:has(.wpo-node-status.error) .wpo-node-card-head > .wpo-node-flag::after{
    display:grid;
    place-items:center;
    font:700 12px/1 system-ui,sans-serif;
    animation:none;
}
"""
anchor="'''\n    js=r'''(()=>{const path=__PATH__"
if src.count(anchor)!=1:
    raise RuntimeError('Не найдено единственное место стилей карточек. Файл не изменён.')
src=src.replace(anchor,css+"\n"+anchor,1)
compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes26tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Кружок загрузки и ошибка точно по центру: лишний символ из карточки удалён.')
PY_PATCH
then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    echo 'Ошибка правки. Исходный интерфейс восстановлен.'
    exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    echo 'Ошибка проверки или перезапуска. Интерфейс восстановлен.'
    exit 1
fi
echo 'Nodes Lab v26 установлен: жёлтый и красный индикаторы по центру.'
echo "Резервная копия: $BACKUP"
echo 'Размеры карточек, ноды, шаблоны, VPN и ветка GitHub main не менялись.'
