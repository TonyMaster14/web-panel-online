#!/usr/bin/env bash
# WPO main controller only: speed up first Happ HWID claim and account creation.
# No Xray/Caddy restart, no subscription/keys/node changes.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запустите через sudo на ОСНОВНОЙ WPO.' >&2; exit 2; }
MGR=/usr/local/sbin/web-proxy-panelctl
[[ -s /opt/tproxy-panel/panel.py && -s "$MGR" &&
   -s /etc/web-proxy-panel/users.json ]] || {
    echo 'Основная WPO не обнаружена. Ничего не изменено.' >&2; exit 2;
}
exec 9>/run/lock/wpo-subscription-fast-patch.lock
flock -n 9 || { echo 'Другое обновление WPO уже запущено.' >&2; exit 2; }
TEMP="$(mktemp -d /tmp/wpo-fast-sub.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup() {
    rc=$?
    trap - EXIT
    if (( rc != 0 && ROLLBACK == 1 )); then
        echo 'Ошибка проверки. Возвращаю предыдущий менеджер.' >&2
        cp -a "$BACKUP" "$MGR" || true
    fi
    rm -rf -- "$TEMP"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
REF=7309d2c69d573d2ad374f1c0d1e2e8edc3c41f5e
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
    --connect-timeout 12 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/wpo-fast-subscription-manager-patch.py" \
    -o "$TEMP/patch.py"
python3 -m py_compile "$TEMP/patch.py"
python3 "$TEMP/patch.py" --input "$MGR" --output "$TEMP/manager.new"
python3 -m py_compile "$TEMP/manager.new"
if cmp -s "$TEMP/manager.new" "$MGR"; then
    echo '✓ Ускорение уже установлено; повторно ничего не изменялось.'
    exit 0
fi
# Refuse a new live manager if its import-only read path is not working.
PYTHONPATH=/opt/tproxy-panel python3 "$TEMP/manager.new" users |
    python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d.get("users"),list)'
BACKUP_DIR=/var/lib/tproxy-panel/fast-subscription-backups
install -d -o root -g root -m 0700 "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/manager-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$MGR" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0755 "$TEMP/manager.new" "$MGR"
"$MGR" users | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d.get("users"),list)'
ROLLBACK=0
echo '✓ Новые Happ-устройства: без перезапуска Xray при изменении только названия.'
echo '✓ VLESS/Hysteria пользователи: без лишней пересборки firewall.'
echo '✓ Реальные новые ключи и порты по-прежнему применяются до ответа панели.'
echo '✓ Текущие пользователи, ключи, ноды и подписки не изменены.'
echo "Резервная копия менеджера: $BACKUP"
echo 'Внимание: скорость и реальная выдача шести нод проверяются на вашей WPO отдельно.'
