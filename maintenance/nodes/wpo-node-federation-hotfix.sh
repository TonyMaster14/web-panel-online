#!/usr/bin/env bash
# Fix already installed WPO additional nodes, preserving all VPN user profiles.
# Must run locally as root ON AN ADDITIONAL NODE (not on the main panel).
# Does not reinstall protocols, SSH into another machine, rotate credentials,
# modify site templates or restart Xray/Caddy/WEB relay.
set -Eeuo pipefail
umask 077

ROOT=/opt/wpp-node-agent
MODULE="$ROOT/wpo_node_eight.py"
CONFIG=/etc/wpp-node-agent/config.json
STATE=/etc/wpp-node-vpn/profiles.json
SERVICE=wpo-node-vpn.service
DROPIN=/etc/systemd/system/wpo-node-vpn.service.d/10-wpo-native-writes.conf
[[ "$EUID" == 0 ]] || { echo 'Нужны права root на ДОПОЛНИТЕЛЬНОЙ ноде.' >&2; exit 2; }
[[ -s "$MODULE" && -s "$CONFIG" && -s "$STATE" &&
   -s /etc/wpp-node-vpn/settings.json && ! -e /opt/tproxy-panel/panel.py ]] || {
    echo 'Это исправление предназначено для уже установленной дополнительной WPO-ноды.' >&2
    exit 2
}
command -v flock >/dev/null
exec 9>/run/lock/wpo-node-federation-hotfix.lock
flock -n 9 || { echo 'Уже выполняется обновление ноды.' >&2; exit 2; }
# Do not overwrite an in-progress federation sync. That operation locks
# this file while mutating the real Xray subscriber registry.
exec 8>/etc/wpp-node-vpn/.federation.lock
flock -w 40 8 || { echo 'Нода создаёт VPN-профиль. Изменения не применены.' >&2; exit 3; }

TMP="$(mktemp -d /tmp/wpo-node-federation.XXXXXXXX)"
BACKUP="/etc/wpp-node-vpn/federation-module-backup-$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK=0
DROPIN_WAS_PRESENT=0
cleanup() {
    code=$?
    trap - EXIT
    if [[ "$ROLLBACK" == 1 ]]; then
        echo 'Проверка службы не прошла. Возвращаю старый код Node Agent.' >&2
        cp -a "$BACKUP/wpo_node_eight.py" "$MODULE" || true
        if [[ "$DROPIN_WAS_PRESENT" == 1 ]]; then
            cp -a "$BACKUP/native-writes.conf" "$DROPIN" || true
        else
            rm -f "$DROPIN"
        fi
        rm -f "$ROOT"/__pycache__/wpo_node_eight.*.pyc
        systemctl daemon-reload || true
        systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$TMP"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

[[ "$(systemctl is-active "$SERVICE")" == active ]] || {
    echo 'VPN Federation до обновления не запущена. Останавливаюсь, ничего не изменено.' >&2
    exit 3
}
[[ "$(systemctl is-active wpo-node-xray.service)" == active ]] || {
    echo 'Xray до обновления не запущен. Останавливаюсь, ничего не изменено.' >&2
    exit 3
}
# An immutable commit. No branch switches or moving HEAD during update.
REV=5f497290fe041149521b7d6006a1dd5b2e833885
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 10 --max-time 60 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/wpo_node_eight.py" \
  -o "$TMP/wpo_node_eight.py"
python3 -m py_compile "$TMP/wpo_node_eight.py"
grep -Fq 'native_changed = assemble(old) != assemble(new)' "$TMP/wpo_node_eight.py"
grep -Fq 'if native_changed:' "$TMP/wpo_node_eight.py"
grep -Fq 'xray.apply(new)' "$TMP/wpo_node_eight.py"
if cmp -s "$TMP/wpo_node_eight.py" "$MODULE" &&
   [[ -f "$DROPIN" ]] &&
   grep -Fq 'ReadWritePaths=-/etc/systemd/system -/etc/tproxy-server -/etc/web-proxy-panel' "$DROPIN"; then
    echo '✓ На этой ноде уже исправлены модуль федерации и права native-сервисов.'
    exit 0
fi

mkdir -m 0700 "$BACKUP"
cp -a "$MODULE" "$BACKUP/wpo_node_eight.py"
if [[ -f "$DROPIN" ]]; then
    DROPIN_WAS_PRESENT=1
    cp -a "$DROPIN" "$BACKUP/native-writes.conf"
fi
ROLLBACK=1
install -d -o root -g root -m 0755 /etc/systemd/system/wpo-node-vpn.service.d
cat >"$DROPIN" <<'DROPIN_UNIT'
[Service]
# Keep strict service isolation, but permit authenticated native backends
# to update their actual configuration files on selected protocol changes.
ReadWritePaths=-/etc/systemd/system -/etc/tproxy-server -/etc/web-proxy-panel
DROPIN_UNIT
chmod 0644 "$DROPIN"
systemctl daemon-reload
install -o root -g root -m 0644 "$TMP/wpo_node_eight.py" "$MODULE"
rm -f "$ROOT"/__pycache__/wpo_node_eight.*.pyc
# The Python federation server caches imported modules between requests.
# Restart ONLY its API service, not Xray, WEB relay, site, Caddy or user VPNs.
systemctl restart "$SERVICE"
ready=0
for i in 1 2 3 4 5 6 7 8 9 10; do
    if systemctl is-active --quiet "$SERVICE" &&
       curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 2 \
           http://127.0.0.1:9089/healthz 2>/dev/null |
           python3 -c 'import json,sys; v=json.load(sys.stdin); sys.exit(0 if v.get("ok") is True else 1)' 2>/dev/null; then
        ready=1
        break
    fi
    sleep 1
done
[[ "$ready" == 1 ]] || {
    echo 'VPN Federation после обновления не отвечает — откат.' >&2
    exit 4
}
ROLLBACK=0
echo '✓ WPO Node: модуль создания VPN-профилей исправлен.'
echo '✓ VLESS/Hysteria не перезапускают WEB Proxy, MTProto, AWG, Naive и Mieru.'
echo '✓ Исправлена песочница VPN Federation для выбранных native-протоколов.'
echo '✓ Подписки и ключи на диске сохранены.'
echo '✓ Xray, Caddy, WEB Proxy и шаблоны сайтов не перезапускались.'
echo "Резервная копия: $BACKUP"
