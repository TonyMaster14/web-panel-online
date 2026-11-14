#!/usr/bin/env bash
# WPO test-branch UI patch for an existing controller (not additional nodes).
set -Eeuo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Запустите через sudo.' >&2; exit 1; }
APP=/opt/tproxy-panel
MANAGER=/usr/local/sbin/web-proxy-panelctl
SERVICE=tproxy-panel.service
REF=test/wpo-smooth-progress-v1
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/${REF}"
[[ -s "$APP/panel.py" && -s "$APP/wpp_ui.py" && -s "$APP/wpp_subscriptions.py" && -s "$MANAGER" ]] || {
    echo 'Не найдена основная WPO: скрипт не предназначен для VPS дополнительной ноды.' >&2
    exit 2
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'WPO сейчас обновляется; повторный запуск запрещён.' >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-v28.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/v28-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
ROLLBACK=0
cleanup() {
    local rc=$?
    trap - EXIT
    if (( rc != 0 && ROLLBACK == 1 )); then
        echo 'Ошибка обновления: восстанавливаю прежний код WPO...' >&2
        cp -a "$BACKUP/panel.py" "$APP/panel.py" || true
        cp -a "$BACKUP/wpp_ui.py" "$APP/wpp_ui.py" || true
        cp -a "$BACKUP/wpp_subscriptions.py" "$APP/wpp_subscriptions.py" || true
        cp -a "$BACKUP/web-proxy-panelctl" "$MANAGER" || true
        if [[ -f "$BACKUP/wpo_user_v28.py" ]]; then
            cp -a "$BACKUP/wpo_user_v28.py" "$APP/wpo_user_v28.py" || true
        else
            rm -f "$APP/wpo_user_v28.py"
        fi
        systemctl restart "$SERVICE" 2>/dev/null || true
    fi
    rm -rf -- "$TMP"
    exit "$rc"
}
trap cleanup EXIT
for name in wpo_v28_apply.py wpo_user_v28.py; do
    curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
        --connect-timeout 12 --max-time 60 "$BASE/$name" -o "$TMP/$name"
done
python3 -m py_compile "$TMP/wpo_v28_apply.py" "$TMP/wpo_user_v28.py"
for name in panel.py wpp_ui.py wpp_subscriptions.py; do
    cp -a "$APP/$name" "$BACKUP/$name"
done
cp -a "$MANAGER" "$BACKUP/web-proxy-panelctl"
[[ ! -e "$APP/wpo_user_v28.py" ]] || cp -a "$APP/wpo_user_v28.py" "$BACKUP/wpo_user_v28.py"
ROLLBACK=1
python3 "$TMP/wpo_v28_apply.py" --app "$APP" --manager "$MANAGER" --helper "$TMP/wpo_user_v28.py"
python3 -m py_compile "$APP/panel.py" "$APP/wpp_ui.py" "$APP/wpp_subscriptions.py" "$APP/wpo_user_v28.py" "$MANAGER"
systemctl restart "$SERVICE"
PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-z0-9-]{3,64}$ ]] || { echo 'Некорректный путь панели.' >&2; exit 3; }
HEALTHY=0
for try in 1 2 3 4 5 6 7 8 9 10; do
    if systemctl is-active --quiet "$SERVICE" &&
        curl -4fsS --max-time 3 "http://127.0.0.1:8090${PANEL_PATH}/__health" >/dev/null; then
        HEALTHY=1
        break
    fi
    sleep 1
done
(( HEALTHY )) || { echo 'Панель не ответила после обновления; выполняю откат.' >&2; exit 3; }
ROLLBACK=0
echo '✓ WPO: форма «Новый пользователь» обновлена. Существующие данные сохранены.'
echo '✓ Путь тестового обновления не изменяет ветку GitHub main.'
echo "Резервная копия: $BACKUP"
