#!/usr/bin/env bash
# Add REALITY to a provisioned eight-engine node; use one pinned source revision.
set -Eeuo pipefail
[[ $EUID == 0 ]] || exit 2
REF="${WPO_NODE_VPN_REF:?Pinned source revision required}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || exit 2
APP=/opt/wpp-node-agent
[[ -s "$APP/wpo_node_eight.py" ]] || { echo 'Install the base node engines first.' >&2; exit 2; }
TEMP="$(mktemp -d /tmp/wpo-node-reality.XXXXXXXX)"
BACKUP="$(mktemp -d /etc/wpp-node-vpn/reality-backup.XXXXXXXX)"
cp -a /etc/caddy/Caddyfile "$BACKUP/Caddyfile"
cp -a "$APP/wpo_node_vpn.py" "$APP/wpo_node_eight.py" "$BACKUP/"
cp -a /etc/wpp-node-vpn/xray.json "$BACKUP/xray.json"
if [[ -d /etc/web-proxy-panel/reality ]]; then cp -a /etc/web-proxy-panel/reality "$BACKUP/reality"; fi
ACTIVE=0
systemctl is-active --quiet wpo-tls-router && ACTIVE=1
cleanup(){
 rc=$?;trap - EXIT
 if (( rc ));then
  systemctl stop wpo-tls-router || true
        if [[ -d "$BACKUP/reality" ]]; then cp -a "$BACKUP/reality/." /etc/web-proxy-panel/reality/; fi
  cp -a "$BACKUP/Caddyfile" /etc/caddy/Caddyfile
  cp -a "$BACKUP/wpo_node_vpn.py" "$BACKUP/wpo_node_eight.py" "$APP/"
  cp -a "$BACKUP/xray.json" /etc/wpp-node-vpn/xray.json
  systemctl restart caddy wpo-node-xray wpo-node-vpn wpp-node-agent || true
  if (( ACTIVE ));then systemctl start wpo-tls-router || true;else systemctl disable wpo-tls-router || true;fi
 fi
 rm -rf "$TEMP";exit "$rc"
}
trap cleanup EXIT
for module in wpo_reality.py wpo_reality_probe.py wpo_xray_live.py wpo_node_vpn.py wpo_node_eight.py; do
 curl -4fsSL --retry 3 --connect-timeout 15 --max-time 90 \
 "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/src/$module" -o "$TEMP/$module"
 python3 -m py_compile "$TEMP/$module"
done
if ! command -v haproxy >/dev/null; then
 DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y --no-install-recommends haproxy
fi
install -m 0644 "$TEMP/"*.py "$APP/"
PYTHONPATH="$APP" python3 - <<'PY'
import json,socket,subprocess
from pathlib import Path
import wpo_reality as r
settings=json.loads(Path('/etc/wpp-node-vpn/settings.json').read_text())
address=socket.gethostbyname(settings['domain'])
p=r.initialize('/opt/web-panel-proxy/xray/xray',address)
r.atomic(r.ROOT/'haproxy.cfg',r.haproxy_config(p['sni']))
subprocess.run(['haproxy','-c','-f',str(r.ROOT/'haproxy.cfg')],check=True)
f=Path('/etc/caddy/Caddyfile');candidate=f.with_name('Caddyfile.reality-candidate')
candidate.write_text(r.caddy_internal(f.read_text()))
subprocess.run(['caddy','validate','--config',str(candidate),'--adapter','caddyfile'],check=True)
f.write_text(candidate.read_text());candidate.unlink()
import wpo_node_vpn as vpn
vpn.apply(vpn.read_json(vpn.STATE,{'profiles':{}})['profiles'])
PY
cat > /etc/systemd/system/wpo-tls-router.service <<'UNIT'
[Unit]
Description=WPO TLS router
After=network-online.target caddy.service
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
systemctl restart caddy
systemctl enable wpo-tls-router
systemctl restart wpo-tls-router wpo-node-vpn wpp-node-agent
for unit in caddy wpo-tls-router wpo-node-xray wpo-node-vpn wpp-node-agent; do systemctl is-active --quiet "$unit";done
echo 'REALITY node ready'
