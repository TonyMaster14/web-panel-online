#!/usr/bin/env bash
# WPO short patch launcher. Run SAME sudo command on each VPS.
# This file belongs to the test branch; never edits GitHub main.
set -Eeuo pipefail
umask 077
if [[ "${EUID}" -ne 0 ]]; then
    echo "Ошибка: запустите команду через sudo." >&2
    exit 1
fi
REF="test/wpo-smooth-progress-v1"
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/${REF}"
controller=0; node=0
[[ ! -s /opt/tproxy-panel/panel.py ]] || controller=1
[[ ! -s /etc/wpp-node-agent/config.json ]] || node=1
if (( controller == 1 && node == 1 )); then
    echo "Ошибка: обнаружены одновременно контроллер и Node Agent. Нельзя безопасно выбрать роль." >&2
    exit 2
elif (( controller == 1 )); then
    target="wpo-node-controller-vpn.sh"
    echo "WPO: обнаружена основная панель. Устанавливаю тестовый патч VPN-нод."
elif (( node == 1 )); then
    target="wpo-node-vpn-enable.sh"
    echo "WPO: обнаружена дополнительная нода. Активирую тестовые VPN-службы."
else
    echo "WPO не найдена. Сначала установите основную панель или Node Agent." >&2
    exit 2
fi
TMP="$(mktemp /tmp/wpo-vpn-patch.XXXXXXXX.sh)"
trap 'rm -f -- "$TMP"' EXIT
curl -4fsSL --proto '=https' --proto-redir '=https' \
    --retry 3 --connect-timeout 15 --max-time 90 \
    "${BASE}/${target}" -o "$TMP" || {
        echo "Не удалось загрузить ${target}; сервер не изменён." >&2
        exit 3
    }
bash -n "$TMP" || { echo "Некорректный патч ${target}; сервер не изменён." >&2; exit 3; }
if (( node == 1 )); then
    WPO_NODE_VPN_REF="$REF" bash "$TMP"
else
    bash "$TMP"
fi
echo '✓ Тестовый VPN-патч WPO применён. GitHub main не изменялся.'
