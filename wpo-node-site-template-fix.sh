#!/usr/bin/env bash
# Restore live WPO site templates on Node Agent 0.4 while retaining WEB Proxy.
# Run ONLY on an additional node VPS, not on the main WPO panel.
set -Eeuo pipefail
umask 077
[[ "$(id -u)" == 0 ]] || { echo 'Run as root on a WPO additional node VPS.' >&2; exit 2; }
CADDY=/etc/caddy/Caddyfile
RELAY=/etc/tproxy-server/config.json
INDEX=/var/www/wpp-node-site/index.html
NODE=/etc/wpp-node-agent/config.json
[[ -s "$CADDY" && -s "$RELAY" && -s "$INDEX" && -s "$NODE" ]] || {
    echo 'WPO node Caddy, WEB relay or site files not found; leaving VPS unchanged.' >&2; exit 2;
}
command -v caddy >/dev/null 2>&1 || { echo 'Caddy missing.' >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo 'curl missing.' >&2; exit 2; }
systemctl is-active --quiet caddy.service || { echo 'Caddy must be running.' >&2; exit 2; }
# Keep the browser's WEB Proxy carrier root and /api/v1 handlers on relay.
grep -Eq '^[[:space:]]*reverse_proxy[[:space:]]+127\.0\.0\.1:8080' "$CADDY" || {
    echo 'This is not the expected WPO Node Agent 0.4 WEB relay configuration.' >&2; exit 2;
}
DOMAIN="$(python3 - <<'PY'
import json
print(json.load(open('/etc/wpp-node-agent/config.json'))['domain'])
PY
)"
WORK="$(mktemp -d /tmp/wpo-node-site-bridge.XXXXXXXX)"
cp -a "$CADDY" "$WORK/Caddyfile.old"
cp -a "$RELAY" "$WORK/relay.old"
CHANGED=0
COMMITTED=0
restore() {
    status=$?
    trap - EXIT
    if [[ "$CHANGED" == 1 && "$COMMITTED" != 1 ]]; then
        echo 'Site template fix did not pass health checks; restoring Caddy and WEB relay.' >&2
        cp -a "$WORK/Caddyfile.old" "$CADDY" || true
        chmod 0644 "$CADDY" || true
        cp -a "$WORK/relay.old" "$RELAY" || true
        systemctl reload-or-restart caddy.service >/dev/null 2>&1 || true
        systemctl restart wpo-node-relay.service >/dev/null 2>&1 || true
    fi
    rm -rf "$WORK"
    exit "$status"
}
trap restore EXIT

# The relay's "public_dir" embeds a static snapshot in RAM and sets a
# restrictive CSP, breaking inline template CSS and dynamic site updates.
# "public_upstream" is supported by the pinned relay and keeps transport
# endpoints and the capability handshake intact.
python3 - "$RELAY" "$NODE" "$WORK/relay.next" <<'PY'
import json,sys
from pathlib import Path
path,node,out=map(Path,sys.argv[1:])
doc=json.loads(path.read_text())
domain=json.loads(node.read_text())['domain']
if doc.get('public_hostname') != domain or doc.get('listen') != '127.0.0.1:8080':
    raise SystemExit('Node relay domain/port differs; refusing site change.')
if doc.get('public_dir') not in (None,'','/var/www/wpp-node-site'):
    raise SystemExit('Unexpected relay public_dir; refusing site change.')
if doc.get('public_upstream') not in (None,'','http://127.0.0.1:18082'):
    raise SystemExit('Unexpected relay public_upstream; refusing site change.')
doc.pop('public_dir',None)
doc['public_upstream']='http://127.0.0.1:18082'
out.write_text(json.dumps(doc,indent=2)+'\n')
PY

cp -a "$CADDY" "$WORK/Caddyfile.next"
if ! grep -Fq '# WPO NODE SITE BRIDGE BEGIN' "$WORK/Caddyfile.next"; then
    cat >> "$WORK/Caddyfile.next" <<'SITE_CADDY'

# WPO NODE SITE BRIDGE BEGIN
# Loopback-only real-time static files. Relay forwards public site requests here.
:18082 {
    bind 127.0.0.1
    root * /var/www/wpp-node-site
    try_files {path} /index.html
    file_server
}
# WPO NODE SITE BRIDGE END
SITE_CADDY
fi
chmod 0644 "$WORK/Caddyfile.next"
caddy validate --config "$WORK/Caddyfile.next" --adapter caddyfile >/dev/null || {
    echo 'Generated Caddyfile invalid; no changes made.' >&2; exit 4;
}
# First activate the private site listener while the old relay is still up.
CHANGED=1
install -o root -g root -m 0644 "$WORK/Caddyfile.next" "$CADDY"
systemctl reload caddy.service
SITE_READY=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 2 \
       -H "Host: $DOMAIN" http://127.0.0.1:18082/ | cmp -s - "$INDEX"; then
       SITE_READY=1; break
    fi
    sleep 0.2
done
if [[ "$SITE_READY" != 1 ]]; then
    echo 'Private Caddy site did not serve expected HTML.' >&2
    exit 4
fi

# Switch only the relay and verify that its actual output matches the on-disk
# template (not a stale snapshot). Do not restart Xray, Hysteria or Node Agent.
install -o root -g tproxy -m 0640 "$WORK/relay.next" "$RELAY"
systemctl restart wpo-node-relay.service
RELAY_READY=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if systemctl is-active --quiet wpo-node-relay.service &&
       curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 2 \
       -H "Host: $DOMAIN" http://127.0.0.1:8080/ | cmp -s - "$INDEX"; then
       RELAY_READY=1; break
    fi
    sleep 0.2
done
if [[ "$RELAY_READY" != 1 ]]; then
    echo 'WEB relay did not serve the selected site; check errors below.' >&2
    journalctl -u wpo-node-relay.service --no-pager -n 20 >&2 || true
    exit 4
fi
COMMITTED=1
echo '✓ WPO Node site templates are served live via loopback Caddy.'
echo '✓ WEB Proxy carrier remains routed via relay on 127.0.0.1:8080.'
echo '✓ No Xray, Hysteria, Node Agent or user credentials were changed.'
