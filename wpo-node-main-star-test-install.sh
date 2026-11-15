#!/usr/bin/env bash
# WPO test branch: yellow ★ after primary node name, not over its flag.
# Only changes /opt/tproxy-panel/wpp_ui.py. No VPN or node service changes.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запустите sudo на контроллере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
    ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Нужна основная WPO-панель, а не дополнительный Node Agent. Ничего не изменено.' >&2
    exit 2
}
exec 9>/run/lock/wpo-nodes-main-star-ui.lock
flock -n 9 || { echo 'Уже выполняется обновление интерфейса.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-node-main-star.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup(){
    code=$?
    trap - EXIT
    if [[ "$ROLLBACK" == 1 ]]; then
        echo 'Проверка панели не пройдена. Возвращаю прежний интерфейс.' >&2
        cp -a "$BACKUP" "$UI" || true
        rm -f "$APP"/__pycache__/wpp_ui.*.pyc
        systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$WORK"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
REV=c2dd98b1ce1960d40d34ca40d14008e14022e273
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
    --connect-timeout 12 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/wpo-node-main-star-name-patch.py" \
    -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
python3 "$WORK/patch.py" --input "$UI" --output "$WORK/ui.py"
python3 -m py_compile "$WORK/ui.py"
if cmp -s "$WORK/ui.py" "$UI"; then
    echo '✓ Звезда уже находится после названия основной ноды.'
    exit 0
fi
BACKUP_DIR=/var/lib/tproxy-panel/nodes-main-star-backups
install -d -m 0700 -o root -g root "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/wpp_ui-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0644 "$WORK/ui.py" "$UI"
rm -f "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$SERVICE"
PANEL_PATH="$(systemctl show -p Environment --value "$SERVICE" |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n 1)"
[[ "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]] || exit 4
READY=0
for try in {1..15}; do
    if systemctl is-active --quiet "$SERVICE" &&
       [[ "$(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
             "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null)" == OK ]]; then
        READY=1
        break
    fi
    sleep 1
done
[[ "$READY" == 1 ]] || exit 4
ROLLBACK=0
echo '✓ Главная нода: флаг отдельно, название ★ с жёлтой звездой.'
echo '✓ Пользователи, ключи, подписки и VPN-ноды не изменены.'
echo "Резервная копия: $BACKUP"
echo 'Обновите страницу «Ноды» в браузере.'
