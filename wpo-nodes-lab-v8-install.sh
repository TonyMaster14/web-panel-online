#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-width-v7' "$UI" || { echo 'Требуется установленный Nodes Lab v7. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v8-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
marker='/* wpo-node-spinner-v8 */'
if marker in src:
    print('Анимация v8 уже добавлена.')
    raise SystemExit(0)
anchor='.wpo-pending-node{border-style:dashed!important}'
if src.count(anchor)!=1:
    raise SystemExit('Не найдено ожидаемое оформление временной ноды. Файл не изменён.')

css="""/* wpo-node-spinner-v8 */
.wpo-pending-node .wpo-node-flag{font-size:0}
.wpo-pending-node .wpo-node-flag::after{content:"";display:block;width:21px;height:21px;box-sizing:border-box;border:2px solid color-mix(in srgb,var(--line) 70%,#eab308);border-top-color:#eab308;border-radius:50%;animation:wpo-node-turn .9s linear infinite}
.wpo-pending-node:has(.wpo-node-status.registration) .wpo-node-flag::after{border-color:color-mix(in srgb,var(--line) 70%,#38bdf8);border-top-color:#38bdf8}
.wpo-pending-node:has(.wpo-node-status.error) .wpo-node-flag::after{content:"!";display:grid;place-items:center;border-color:#ef4444;color:#ef4444;font:700 14px system-ui,sans-serif;animation:none}
.wpo-pending-node .wpo-node-status.installing i,.wpo-pending-node .wpo-node-status.registration i{animation:wpo-node-pulse 1.5s ease-in-out infinite}
@keyframes wpo-node-turn{to{transform:rotate(360deg)}}
@keyframes wpo-node-pulse{50%{opacity:.4;transform:scale(.8)}}
@media(prefers-reduced-motion:reduce){.wpo-pending-node .wpo-node-flag::after,.wpo-pending-node .wpo-node-status i{animation:none}}
"""
src=src.replace(anchor,anchor+'\n'+css,1)
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes8tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Добавлен кружок загрузки только для ноды в процессе установки.')
PY_PATCH
then
    echo 'Не удалось добавить анимацию; восстанавливаю файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Ошибка проверки или перезапуска; выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v8: анимация установки добавлена. Резервная копия: $BACKUP"
echo 'Основная ветка GitHub main не затронута.'
