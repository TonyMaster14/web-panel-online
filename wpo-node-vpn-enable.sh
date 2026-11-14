#!/usr/bin/env bash
# Enable real VPN service on an existing WPO Node Agent 0.2 VPS.
# Site and site-template settings are preserved. Test branch only.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run as root on an ADDITIONAL node VPS' >&2; exit 1; }
AGENT=/opt/wpp-node-agent/agent.py
[[ -s "$AGENT" && -s /etc/wpp-node-agent/config.json && -s /etc/caddy/Caddyfile ]] || {
    echo 'Node Agent 0.2 must be installed first.' >&2; exit 2; }
REF="\${WPO_NODE_VPN_REF:-test/wpo-smooth-progress-v1}"
[[ "$REF" =~ ^[A-Za-z0-9._/-]{1,120}$ ]] || exit 2
DOMAIN="$(python3 -c 'import json;print(json.load(open("/etc/wpp-node-agent/config.json"))["domain"])')"
[[ "$DOMAIN" =~ ^([a-z0-9-]+\.)+[a-z]{2,63}$ ]] || exit 2
echo "Activating test VPN on node $DOMAIN"
TEMP="$(mktemp -d /tmp/wpo-vpn-test.XXXXXXXX)"
trap 'rm -rf -- "$TEMP"' EXIT
if ! command -v unzip >/dev/null; then
    apt-get -o DPkg::Lock::Timeout=600 update
    apt-get -o DPkg::Lock::Timeout=600 install -y --no-install-recommends unzip
fi
command -v openssl >/dev/null || { echo 'openssl is required' >&2; exit 2; }
if ! getent group xray >/dev/null; then groupadd --system xray; fi
if ! id xray >/dev/null 2>&1; then
    useradd --system --gid xray --home-dir /var/lib/wpo-node-xray \
        --create-home --shell /usr/sbin/nologin xray
fi
install -d -o root -g xray -m 0750 /etc/wpp-node-vpn /etc/wpp-node-vpn/tls
install -d -m 0755 /opt/web-panel-proxy/xray
VPN_PY=/opt/wpp-node-agent/wpo_node_vpn.py
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
    --connect-timeout 15 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/wpo_node_vpn.py" \
    -o "$TEMP/wpo_node_vpn.py"
python3 -m py_compile "$TEMP/wpo_node_vpn.py"
XRAY=/opt/web-panel-proxy/xray/xray
if [[ ! -x "$XRAY" ]] || ! "$XRAY" version >/dev/null 2>&1; then
    curl -fSL --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --retry 3 --retry-all-errors --connect-timeout 20 --max-time 180 \
        -o "$TEMP/xray.zip" \
        'https://github.com/XTLS/Xray-core/releases/download/v26.7.28/Xray-linux-64.zip'
    echo "8195d909f1109b8f3d99eefe401a3c451d7bf4af71f24d3815420f77e5dd2a40  $TEMP/xray.zip" |
        sha256sum -c - >/dev/null || { echo 'Xray checksum mismatch' >&2; exit 3; }
    unzip -q "$TEMP/xray.zip" xray -d "$TEMP"
    install -m 0755 "$TEMP/xray" "$XRAY"
fi
BACKUP="/etc/wpp-node-vpn/backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/agent.py"
cp -a /etc/caddy/Caddyfile "$BACKUP/Caddyfile"
[[ ! -e "$VPN_PY" ]] || cp -a "$VPN_PY" "$BACKUP/wpo_node_vpn.py"
install -m 0700 "$TEMP/wpo_node_vpn.py" "$VPN_PY"
python3 - "$DOMAIN" <<'PY_SETTINGS'
import json,os,re,secrets,sys,tempfile
from pathlib import Path
domain=sys.argv[1];path=Path('/etc/wpp-node-vpn/settings.json')
if path.exists():
    value=json.loads(path.read_text())
    if value.get('domain')!=domain: raise SystemExit('Node VPN domain mismatch')
    if not re.fullmatch('/wpo-xhttp-[a-f0-9]{24}',str(value.get('xhttp_path',''))):
        raise SystemExit('Invalid existing XHTTP path')
else:
    value={'domain':domain,'xhttp_path':'/wpo-xhttp-'+secrets.token_hex(12)}
fd,tmp=tempfile.mkstemp(dir=str(path.parent))
with os.fdopen(fd,'w') as f: json.dump(value,f);f.write('\n')
os.chmod(tmp,0o600);os.replace(tmp,path)
PY_SETTINGS
python3 - "$AGENT" <<'PY_PATCH_AGENT'
import sys
from pathlib import Path
p=Path(sys.argv[1]);s=p.read_text(encoding='utf-8')
old="'capabilities':['node-agent','site-template']"
new="'capabilities':['node-agent','site-template']+(['federation','vless','hysteria'] if vpn_ready() else [])"
marker='# wpo-node-federation-status-v27'
if marker not in s:
    if s.count(old)!=1: raise SystemExit('Unexpected Node Agent version; no changes made')
    anchor='class H(BaseHTTPRequestHandler):'
    if s.count(anchor)!=1: raise SystemExit('Node Agent handler missing')
    addition="""# wpo-node-federation-status-v27
def vpn_ready():
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:9089/healthz',timeout=2) as r:
            return bool(__import__('json').loads(r.read(4096)).get('ok'))
    except Exception:
        return False

"""
    s=s.replace(anchor,addition+anchor)
    s=s.replace(old,new)
elif new not in s:
    raise SystemExit('Inconsistent existing VPN capability patch')
compile(s,str(p),'exec')
p.write_text(s,encoding='utf-8')
PY_PATCH_AGENT
python3 - <<'PY_PATCH_CADDY'
from pathlib import Path
import json,re
p=Path('/etc/caddy/Caddyfile')
conf=json.loads(Path('/etc/wpp-node-vpn/settings.json').read_text())
s=p.read_text(encoding='utf-8')
s=re.sub(r'(?ms)^[ \t]*# WPO NODE VPN BEGIN\n.*?^[ \t]*# WPO NODE VPN END\n?','',s)
anchor='    handle /wpp-api/* {'
if s.count(anchor)!=1: raise SystemExit('Unexpected Node Agent Caddyfile, refusing to overwrite')
path=conf['xhttp_path']
addon=(
 '    # WPO NODE VPN BEGIN\n'
 '    handle /wpp-api/v1/federation/* {\n'
 '        reverse_proxy 127.0.0.1:9089\n'
 '    }\n'
 f'    @wpo_node_xhttp path {path} {path}/*\n'
 '    handle @wpo_node_xhttp {\n'
 '        reverse_proxy 127.0.0.1:19000 {\n'
 '            transport http {\n'
 '                versions h2c\n'
 '            }\n'
 '            flush_interval -1\n'
 '        }\n'
 '    }\n'
 '    # WPO NODE VPN END\n'
)
s=s.replace(anchor,addon+anchor,1)
p.with_suffix('.vpn-test').write_text(s,encoding='utf-8')
PY_PATCH_CADDY
caddy validate --config /etc/caddy/Caddyfile.vpn-test --adapter caddyfile >/dev/null ||
    { rm -f /etc/caddy/Caddyfile.vpn-test; echo 'Caddy validation failed' >&2; exit 3; }
mv -f /etc/caddy/Caddyfile.vpn-test /etc/caddy/Caddyfile
chmod 0644 /etc/caddy/Caddyfile
cat >/etc/systemd/system/wpo-node-xray.service <<'UNIT'
[Unit]
Description=WPO Node Xray - XHTTP and Hysteria2
After=network-online.target caddy.service
Wants=network-online.target
[Service]
Type=simple
User=xray
Group=xray
UMask=0027
ExecStart=/opt/web-panel-proxy/xray/xray run -config /etc/wpp-node-vpn/xray.json
Restart=on-failure
RestartSec=4
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/etc/wpp-node-vpn
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/wpo-node-vpn.service <<'UNIT'
[Unit]
Description=WPO Node VPN authenticated federation API
After=network-online.target wpo-node-xray.service
Wants=network-online.target
[Service]
Type=simple
User=root
Group=root
UMask=0077
ExecStart=/usr/bin/python3 /opt/wpp-node-agent/wpo_node_vpn.py --serve
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/etc/wpp-node-vpn
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/wpo-node-vpn-tls.service <<'UNIT'
[Unit]
Description=Synchronize WPO node Caddy TLS into Xray
After=caddy.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/wpp-node-agent/wpo_node_vpn.py --sync-tls
UNIT
cat >/etc/systemd/system/wpo-node-vpn-tls.timer <<'UNIT'
[Unit]
Description=WPO Node TLS renewal
[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now caddy.service
systemctl reload caddy.service || systemctl restart caddy.service
python3 "$VPN_PY" --sync-tls || {
    echo 'Caddy certificate missing. VPN not marked ready.' >&2
    exit 3
}
if [[ ! -s /etc/wpp-node-vpn/profiles.json ]]; then
    printf '{"profiles":{}}\n' > /etc/wpp-node-vpn/profiles.json
    chmod 0600 /etc/wpp-node-vpn/profiles.json
fi
python3 - <<'PY_INIT'
import grp,os,sys
sys.path.insert(0,'/opt/wpp-node-agent')
import wpo_node_vpn as vpn
state=vpn.read_json(vpn.STATE).get('profiles',{})
vpn.atomic_json(vpn.XRAY,vpn.render_xray(state,vpn.read_json(vpn.SETTINGS)))
os.chown(vpn.XRAY,0,grp.getgrnam('xray').gr_gid)
os.chmod(vpn.XRAY,0o640)
PY_INIT
"$XRAY" run -test -config /etc/wpp-node-vpn/xray.json >/dev/null ||
    { echo 'Xray configuration invalid' >&2; exit 3; }
systemctl enable wpo-node-xray.service
systemctl restart wpo-node-xray.service
systemctl is-active --quiet wpo-node-xray.service || {
    echo 'Xray did not start' >&2; exit 3; }
systemctl enable --now wpo-node-vpn.service wpo-node-vpn-tls.timer
systemctl restart wpp-node-agent.service
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
    ufw allow 8443/udp >/dev/null
fi
ok=0
for _ in 1 2 3 4 5 6; do
    if curl -4fsS --max-time 3 http://127.0.0.1:9089/healthz |
        grep -q '"ok": true'; then ok=1; break; fi
    sleep 1
done
(( ok == 1 )) || { echo 'VPN health check failed' >&2; exit 3; }
# Bump the advertised agent version only after both real VPN services work.
python3 - <<'PY_VERSION'
from pathlib import Path
import json,os,tempfile
p=Path('/etc/wpp-node-agent/config.json')
d=json.loads(p.read_text(encoding='utf-8'))
d['version']='0.3.0'
fd,temp=tempfile.mkstemp(dir=str(p.parent))
with os.fdopen(fd,'w',encoding='utf-8') as stream:
    json.dump(d,stream)
    stream.write('\\n')
os.chmod(temp,0o600)
os.replace(temp,p)
PY_VERSION
systemctl restart wpp-node-agent.service
systemctl is-active --quiet wpp-node-agent.service || {
    echo 'Node Agent status update failed' >&2; exit 3; }
echo '✓ VPN node ready: VLESS XHTTP (TCP 443), Hysteria2 (UDP 8443)'
echo '✓ The existing node website, templates and API key were preserved.'
echo 'Important: allow UDP 8443 in the VPS provider firewall if it is enabled.'
