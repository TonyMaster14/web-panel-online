#!/usr/bin/env bash
# Targeted controller patch; no VPN/node installation or registry replacement.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите команду через sudo.' >&2; exit 1; }
APP=/opt/tproxy-panel
MANAGER=/usr/local/sbin/web-proxy-panelctl
REF="${WPO_ACTIONS_REF:-test/wpo-smooth-progress-v1}"
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ && "$REF" != *..* ]] || exit 2
for file in "$APP/panel.py" "$APP/wpp_ui.py" "$MANAGER"; do
    [[ -s "$file" ]] || { echo "Не найден файл панели: $file" >&2; exit 1; }
done
exec 9>/run/lock/web-panel-proxy.lock
flock -w 15 9 || { echo 'Другое обновление уже работает.' >&2; exit 1; }
STAGE="$(mktemp -d /tmp/wpo-fast-actions.XXXXXXXX)"
TOUCHED=0
finish() {
    local rc=$?
    trap - EXIT
    if (( rc != 0 && TOUCHED )); then
        echo 'Ошибка обновления. Возвращаю предыдущие файлы панели.' >&2
        cp -a "$STAGE/backup/panel.py" "$STAGE/backup/wpp_ui.py" "$APP/"
        cp -a "$STAGE/backup/web-proxy-panelctl" "$MANAGER"
        if [[ -f "$STAGE/backup/wpo_fast_actions.py" ]]; then
            cp -a "$STAGE/backup/wpo_fast_actions.py" "$APP/"
        else
            rm -f "$APP/wpo_fast_actions.py"
        fi
        systemctl restart tproxy-panel.service || true
    fi
    rm -rf -- "$STAGE"
    exit "$rc"
}
trap finish EXIT
for file in wpo_fast_actions.py wpo_fast_actions_apply.py; do
    curl -4fsSL --retry 3 --connect-timeout 15 --max-time 90 \
        "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/src/$file" -o "$STAGE/$file"
done
# Validate every patched file before stopping the panel or modifying anything.
python3 - "$STAGE" "$APP" "$MANAGER" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import wpo_fast_actions_apply as patch
app=Path(sys.argv[2]);manager=Path(sys.argv[3])
patch.patch_manager(manager.read_text())
patch.patch_panel((app/'panel.py').read_text())
patch.patch_ui((app/'wpp_ui.py').read_text())
compile((Path(sys.argv[1])/'wpo_fast_actions.py').read_text(),'wpo_fast_actions.py','exec')
PY
mkdir "$STAGE/backup"
cp -a "$APP/panel.py" "$APP/wpp_ui.py" "$MANAGER" "$STAGE/backup/"
if [[ -f "$APP/wpo_fast_actions.py" ]]; then cp -a "$APP/wpo_fast_actions.py" "$STAGE/backup/"; fi
TOUCHED=1
systemctl stop tproxy-panel.service
exec 8>/etc/web-proxy-panel/manager.lock
flock -w 30 8 || { echo 'Менеджер занят. Повторите обновление позже.' >&2; exit 1; }
python3 "$STAGE/wpo_fast_actions_apply.py" --app "$APP" --manager "$MANAGER"
flock -u 8
systemctl start tproxy-panel.service
sleep 2
systemctl is-active --quiet tproxy-panel.service
TOUCHED=0
echo 'Готово: обновлены обработчики подключений, удаления пользователей и текст ожидания.'
echo 'Обновите страницу панели. Ноды обновлять не нужно.'
