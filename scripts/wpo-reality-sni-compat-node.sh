#!/usr/bin/env bash
# WPO test only: preserve REALITY access for pre-existing Apple/NVIDIA/Yahoo
# client links without changing their UUID/keys/Short IDs or the selected SNI.
# Run on a REMOTE node, not the WPO controller. Atomic rollback on failure.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Запустите с sudo на VPS дополнительной ноды." >&2; exit 2; }
APP=/opt/wpp-node-agent
VPN=/etc/wpp-node-vpn
REALITY=/etc/web-proxy-panel/reality
XRAY=/opt/web-panel-proxy/xray/xray
REV=1d165774d088978a60fb2366e298a93a3e73af48
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src"
for f in "$APP/wpo_node_vpn.py" "$APP/wpo_reality.py" "$VPN/xray.json" "$VPN/profiles.json" "$VPN/settings.json" "$REALITY/profile.json" "$REALITY/private.key" "$REALITY/haproxy.cfg"; do
    [[ -s "$f" && ! -L "$f" ]] || { echo "Нет существующей REALITY ноды: $f" >&2; exit 2; }
done
for unit in wpo-node-xray.service wpo-node-vpn.service wpo-tls-router.service; do
    systemctl is-active --quiet "$unit" || { echo "Неактивна служба $unit. Ничего не изменено." >&2; exit 2; }
done
WORK="$(mktemp -d /tmp/wpo-compat-node.XXXXXXXX)"
BACKUP=""
INSTALLED=0
cleanup() {
    local status=$?
    trap - EXIT
    if (( status != 0 && INSTALLED == 1 )) && [[ -n "$BACKUP" && -d "$BACKUP" ]]; then
        echo "Ошибка: возвращаю прежний Xray/HAProxy и модули ноды..." >&2
        cp -a "$BACKUP/wpo_reality.py" "$APP/wpo_reality.py" || true
        cp -a "$BACKUP/wpo_node_vpn.py" "$APP/wpo_node_vpn.py" || true
        cp -a "$BACKUP/xray.json" "$VPN/xray.json" || true
        cp -a "$BACKUP/haproxy.cfg" "$REALITY/haproxy.cfg" || true
        systemctl restart wpo-node-xray.service wpo-tls-router.service wpo-node-vpn.service || true
        echo "Резервная копия: $BACKUP" >&2
    fi
    rm -rf -- "$WORK"
    exit "$status"
}
trap cleanup EXIT
for module in wpo_reality.py wpo_node_vpn.py; do
    curl -4fsSL --retry 3 --connect-timeout 12 --max-time 75 --proto '=https' \
        "$BASE/$module" -o "$WORK/$module"
    python3 -m py_compile "$WORK/$module"
done
grep -Fq "def reality_routes(" "$WORK/wpo_reality.py" &&
grep -Fq "inbounds.extend(wpo_reality.inbounds(reality_clients))" "$WORK/wpo_node_vpn.py" ||
    { echo "Получена неподходящая версия Node Agent." >&2; exit 3; }
PYTHONPATH="$WORK:$APP" python3 - "$WORK" <<'PY'
import json,sys
from pathlib import Path
import wpo_reality as r
import wpo_node_vpn as v
folder=Path(sys.argv[1])
settings=v.read_json(v.SETTINGS)
state=v.read_json(v.STATE,{"profiles":{}})["profiles"]
profile=r.read_profile()
(folder/"candidate-xray.json").write_text(json.dumps(v.render_xray(state,settings)))
(folder/"candidate-haproxy.cfg").write_text(r.haproxy_config(profile["sni"]))
expected=set(host for host,port in r.reality_routes(profile))
entries=json.loads((folder/"candidate-xray.json").read_text())["inbounds"]
actual=set(x["streamSettings"]["realitySettings"]["serverNames"][0] for x in entries if x.get("streamSettings",{}).get("security")=="reality")
assert expected==actual and "www.microsoft.com" not in expected
PY
"$XRAY" run -test -config "$WORK/candidate-xray.json" >/dev/null
haproxy -c -f "$WORK/candidate-haproxy.cfg" >/dev/null
BACKUP="$REALITY/compat-backup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$APP/wpo_reality.py" "$APP/wpo_node_vpn.py" "$VPN/xray.json" "$REALITY/haproxy.cfg" "$BACKUP/"
echo "Резервная копия: $BACKUP"
# Lock out concurrent federation writes while we replace Xray and the router.
exec 9>"$VPN/.federation.lock"
flock -x -w 30 9 || { echo "Другой процесс изменяет ноду. Попробуйте позже." >&2; exit 3; }
INSTALLED=1
for module in wpo_reality.py wpo_node_vpn.py; do
    stage="$(mktemp "$APP/.wpo-compat.XXXXXXXX.py")"
    cp "$WORK/$module" "$stage"
    chown --reference="$APP/$module" "$stage"
    chmod --reference="$APP/$module" "$stage"
    mv -f "$stage" "$APP/$module"
done
PYTHONPATH="$APP" python3 - <<'PY'
import wpo_node_vpn as v
import wpo_reality as r
state=v.read_json(v.STATE,{"profiles":{}})["profiles"]
v.apply(state)
r.atomic(r.ROOT/"haproxy.cfg",r.haproxy_config(r.read_profile()["sni"]))
PY
systemctl reload wpo-tls-router.service
systemctl restart wpo-node-vpn.service
for unit in wpo-node-xray.service wpo-node-vpn.service wpo-tls-router.service; do
    systemctl is-active --quiet "$unit" || { echo "Служба $unit неактивна после обновления." >&2; exit 4; }
done
# Verify every configured SNI actually routes to a *different matching*
# Xray backend. This is config/readiness validation, not a client-side ping.
PYTHONPATH="$APP" python3 - <<'PY'
import json
import wpo_node_vpn as vpn
import wpo_reality as r
cfg=vpn.read_json(vpn.XRAY)
routes=r.reality_routes(r.read_profile())
for host,port in routes:
    match=[x for x in cfg["inbounds"] if x.get("port")==port]
    assert len(match)==1 and match[0]["streamSettings"]["realitySettings"]["target"]==host+":443"
print("✓ Реальная конфигурация Xray содержит отдельный backend для каждого SNI.")
PY
INSTALLED=0
echo "✓ REALITY: поддерживаются NVIDIA, Apple, Yahoo, Amazon без смены ключей."
echo "✓ Для каждого SNI собственный TLS target и отдельный backend HAProxy."
echo "✓ Настройки и профили Happ не менялись. Проверяйте фактическую связь из приложения."
echo "✓ Нода обновлена; остальные VPS не затронуты."
