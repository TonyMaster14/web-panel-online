#!/usr/bin/env bash
# Install the shared TCP/443 frontend after the existing panel is healthy.
set -Eeuo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -d "$BASE/src" ]] || BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULES="$BASE/src"
[[ -d "$MODULES" ]] || MODULES="$BASE"
APP=/opt/tproxy-panel
[[ $EUID == 0 && -s "$APP/panel.py" ]] || exit 2
if ! command -v haproxy >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y --no-install-recommends haproxy
fi
BACKUP="$(mktemp -d /etc/web-proxy-panel/reality-backup.XXXXXXXX)"
cp -a /etc/caddy/Caddyfile "$BACKUP/Caddyfile"
cp -a "$APP/panel.py" "$APP/wpp_ui.py" /usr/local/sbin/web-proxy-panelctl "$BACKUP/"
cp -a /etc/web-panel-proxy-xray/config.json "$BACKUP/xray.json"
if [[ -d /etc/web-proxy-panel/reality ]]; then cp -a /etc/web-proxy-panel/reality "$BACKUP/reality"; fi
WAS_ACTIVE=0
systemctl is-active --quiet wpo-tls-router && WAS_ACTIVE=1
rollback(){
    rc=$?
    trap - EXIT
    if (( rc != 0 )); then
        echo "REALITY: восстановление предыдущего входа 443; резервная копия $BACKUP" >&2
        systemctl stop wpo-tls-router || true
        if [[ -d "$BACKUP/reality" ]]; then cp -a "$BACKUP/reality/." /etc/web-proxy-panel/reality/; fi
        cp -a "$BACKUP/Caddyfile" /etc/caddy/Caddyfile
        cp -a "$BACKUP/panel.py" "$BACKUP/wpp_ui.py" "$APP/"
        cp -a "$BACKUP/web-proxy-panelctl" /usr/local/sbin/web-proxy-panelctl
        cp -a "$BACKUP/xray.json" /etc/web-panel-proxy-xray/config.json
        systemctl restart caddy web-panel-proxy-xray tproxy-panel || true
        if (( WAS_ACTIVE )); then systemctl start wpo-tls-router || true; else systemctl disable wpo-tls-router || true; fi
    fi
    exit "$rc"
}
trap rollback EXIT
install -m 0644 "$MODULES/wpo_reality.py" "$MODULES/wpo_reality_ui.py" "$APP/"
python3 "$MODULES/wpo_reality_apply.py" --app "$APP"
PYTHONPATH="$APP" python3 - <<'PY'
import ipaddress
from pathlib import Path
import subprocess
import wpo_reality as r
address=Path('/etc/web-proxy-panel/mtproto-host').read_text().strip()
try:
    if not ipaddress.ip_address(address).is_global: raise ValueError()
except ValueError:
    raise SystemExit('Не удалось определить публичный IP для REALITY')
p=r.initialize('/opt/web-panel-proxy/xray/xray',address)
r.atomic(r.ROOT/'haproxy.cfg',r.haproxy_config(p['sni']))
caddy=Path('/etc/caddy/Caddyfile')
candidate=caddy.with_name('Caddyfile.reality-candidate')
candidate.write_text(r.caddy_internal(caddy.read_text()))
subprocess.run(['caddy','validate','--config',str(candidate),'--adapter','caddyfile'],check=True)
subprocess.run(['haproxy','-c','-f',str(r.ROOT/'haproxy.cfg')],check=True)
# Preserve Caddyfile owner and mode.
caddy.write_text(candidate.read_text());candidate.unlink()
PY
cat > /etc/systemd/system/wpo-tls-router.service <<'UNIT'
[Unit]
Description=WPO TLS SNI router (website/XHTTP and REALITY)
After=network-online.target caddy.service
Wants=network-online.target
[Service]
Type=notify
ExecStart=/usr/sbin/haproxy -Ws -f /etc/web-proxy-panel/reality/haproxy.cfg -p /run/wpo-tls-router.pid
ExecReload=/usr/sbin/haproxy -c -f /etc/web-proxy-panel/reality/haproxy.cfg
ExecReload=/bin/kill -USR2 $MAINPID
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
/usr/local/sbin/web-proxy-panelctl sync
# Restart releases the original 443 listener before the router binds it.
systemctl restart caddy
systemctl enable wpo-tls-router
systemctl restart wpo-tls-router
systemctl restart tproxy-panel
for unit in caddy wpo-tls-router web-panel-proxy-xray tproxy-panel; do
    systemctl is-active --quiet "$unit"
done
trap - EXIT
echo 'REALITY: TCP/443, Firefox, ключи и маршрутизатор установлены.'
