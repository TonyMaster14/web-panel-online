#!/usr/bin/env bash
# Test-only compact WPO node cards. Updates one UI helper, not VPN services.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запускай через sudo на тестовом контроллере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpo_user_v28.py"
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
   echo 'Нужна основная WPO (контроллер), не дополнительная VPN-нода.' >&2
   exit 2
}
exec 9>/run/lock/wpo-v28-picker-ui.lock
flock -n 9 || { echo 'Другое изменение интерфейса уже выполняется.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-v28-ui.XXXXXXXX)"
BACKUP=""
NEEDS_ROLLBACK=0
cleanup(){
    code=$?
    trap - EXIT
    if [[ "$NEEDS_ROLLBACK" == 1 ]]; then
        echo 'Проверка панели не пройдена; возвращаю прежний интерфейс.' >&2
        cp -a "$BACKUP" "$UI" || true
        rm -f "$APP"/__pycache__/wpo_user_v28.*.pyc
        systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
    fi
    rm -rf -- "$WORK"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
REV=9b9a8aa45ef1240ddacd74d586dc7967a111bc67
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
  --connect-timeout 12 --max-time 90 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/wpo-node-picker-compact-patch.py" \
  -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
python3 "$WORK/patch.py" --input "$UI" --output "$WORK/new.py"
python3 -m py_compile "$WORK/new.py"
if cmp -s "$UI" "$WORK/new.py"; then
    echo '✓ Новый вид нод уже установлен, ничего менять не нужно.'
    exit 0
fi
BACKUP_DIR=/var/lib/tproxy-panel/v28-picker-ui-backups
install -d -m 0700 -o root -g root "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/wpo_user_v28-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
NEEDS_ROLLBACK=1
install -o root -g root -m 0644 "$WORK/new.py" "$UI"
rm -f "$APP"/__pycache__/wpo_user_v28.*.pyc
systemctl restart tproxy-panel.service
PANEL_PATH="$(systemctl show -p Environment --value tproxy-panel.service |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
[[ "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]] || exit 4
READY=0
for n in {1..15}; do
    if systemctl is-active --quiet tproxy-panel.service &&
       [[ "$(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
              "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null)" == OK ]]; then
         READY=1
         break
    fi
    sleep 1
done
[[ "$READY" == 1 ]] || exit 4
NEEDS_ROLLBACK=0
echo '✓ Карточки нод обновлены: флаг и название в одной строке.'
echo '✓ Нидерланды отмечены звездой ★; надпись VPN готов удалена.'
echo '✓ Пользователи, подписки, ключи, Xray, Caddy и ноды не изменены.'
echo "Резервная копия: $BACKUP"
echo 'Обнови страницу WPO в браузере и открой «Новый пользователь».'
