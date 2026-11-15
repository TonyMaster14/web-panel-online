#!/usr/bin/env bash
# Existing ADDITIONAL WPO node: install a minimal secret-free failure trace.
# Doesn't modify Xray, Caddy, API keys, federation state or the main WPO.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запустите sudo на дополнительной ноде.' >&2; exit 2; }
ROOT=/opt/wpp-node-agent
MODULE="$ROOT/wpo_node_vpn.py"
[[ -s "$MODULE" && -s /etc/wpp-node-agent/config.json &&
    -s /etc/wpp-node-vpn/settings.json &&
    ! -e /opt/tproxy-panel/panel.py ]] || {
    echo 'Нужна дополнительная WPO-нода, а не основная панель. Изменений нет.' >&2
    exit 2
}
exec 9>/run/lock/wpo-fed-trace-update.lock
flock -n 9 || { echo 'Другое обновление диагностики уже выполняется.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-fed-stage.XXXXXXXX)"
BACKUP="/etc/wpp-node-vpn/wpo-node-vpn-before-stage-$(date -u +%Y%m%dT%H%M%SZ).py"
ROLLBACK=0
cleanup(){
    code=$?
    trap - EXIT
    if [[ "$ROLLBACK" == 1 ]]; then
        echo 'VPN API не прошёл проверку. Возвращаю исходный модуль.' >&2
        cp -a "$BACKUP" "$MODULE" || true
        rm -f "$ROOT"/__pycache__/wpo_node_vpn.*.pyc
        systemctl restart wpo-node-vpn.service >/dev/null 2>&1 || true
    fi
    rm -rf -- "$WORK"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
REV=1e296934d1a829ed41b690a00b4e56807fa2d101
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
    --connect-timeout 12 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/wpo-node-federation-error-stage-patch.py" \
    -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
python3 "$WORK/patch.py" --input "$MODULE" --output "$WORK/module.py"
python3 -m py_compile "$WORK/module.py"
grep -Fq '# wpo-federation-safe-failure-stage-v1' "$WORK/module.py"
if ! cmp -s "$WORK/module.py" "$MODULE"; then
    cp -a "$MODULE" "$BACKUP"
    ROLLBACK=1
    install -o root -g root -m 0700 "$WORK/module.py" "$MODULE"
    rm -f "$ROOT"/__pycache__/wpo_node_vpn.*.pyc
    systemctl restart wpo-node-vpn.service
    READY=0
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
        if systemctl is-active --quiet wpo-node-vpn.service &&
           curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 2 \
                http://127.0.0.1:9089/healthz 2>/dev/null |
           python3 -c 'import json,sys; d=json.load(sys.stdin);sys.exit(0 if d.get("ok") else 1)' 2>/dev/null; then
           READY=1
           break
        fi
        sleep 1
    done
    [[ "$READY" == 1 ]] || exit 4
    ROLLBACK=0
else
    echo '✓ Диагностика уже установлена.'
fi
echo '✓ VPN Federation отвечает. Настройки Xray и профили не менялись.'
echo '✓ После повторного POST с основной WPO смотри сообщения WPO_FED_*:'
echo 'sudo journalctl -u wpo-node-vpn.service --since "5 minutes ago" --no-pager -o cat | grep WPO_FED'
echo "Резервная копия: $BACKUP"
