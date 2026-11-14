#!/usr/bin/env bash
# WPO Node Agent 0.4: install *all eight* server-side protocol engines.
# Run automatically by the node installer, before registration.
# This is for additional VPS nodes; NEVER runs the full main-panel installer.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Node engine installer requires root' >&2; exit 2; }
[[ -s /etc/wpp-node-agent/config.json &&
   -s /etc/wpp-node-vpn/settings.json &&
   -s /opt/wpp-node-agent/wpo_node_vpn.py ]] || {
    echo 'WPO XHTTP/Hysteria node must be installed first' >&2; exit 2; }
[[ "$(uname -m)" == "x86_64" ]] || {
    echo 'Eight-protocol node installer currently supports x86_64 only' >&2; exit 2; }
REF="${WPO_NODE_VPN_REF:-test/wpo-smooth-progress-v1}"
[[ "$REF" =~ ^[A-Za-z0-9._/-]{1,120}$ ]] || exit 2
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF"
TEMP="$(mktemp -d /tmp/wpo-node-eight.XXXXXXXX)"
trap 'rm -rf -- "$TEMP"' EXIT
download(){
    local item="$1" destination="$2" sha="$3"
    curl -4fLsS --proto '=https' --proto-redir '=https' --retry 3 \
        --connect-timeout 20 --max-time 240 -o "$destination" "$BASE/$item"
    echo "$sha  $destination" | sha256sum -c - >/dev/null
}
echo '[WPO node] Installing all eight protocol engines'
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::ForceIPv4=true -o DPkg::Lock::Timeout=600 update
apt-get -o Acquire::ForceIPv4=true -o DPkg::Lock::Timeout=600 install -y \
    --no-install-recommends ca-certificates curl git build-essential libssl-dev \
    zlib1g-dev util-linux xz-utils tar nftables iproute2 wireguard-tools \
    python3 openssl procps
install -d -m 0755 /opt/web-panel-proxy
# NaiveProxy (caddy) and Mieru (mita) must traverse the shared parent.
# AWG credentials remain locked inside the root-only awg subdirectory.
install -d -o root -g root -m 0755 /etc/web-proxy-panel
install -d -o root -g root -m 0700 /etc/web-proxy-panel/awg
install -d -o root -g root -m 0755 /etc/web-proxy-panel/extra-protocols
install -d -m 0755 /opt/wpp-node-agent

# Original Telegram MTProxy at the exact pinned source and archive checksum.
if [[ ! -x /opt/MTProxy/objs/bin/mtproto-proxy ]]; then
    curl -4fLsS --proto '=https' --proto-redir '=https' --retry 3 \
        --connect-timeout 20 --max-time 240 \
        'https://github.com/TelegramMessenger/MTProxy/archive/f36d8af769ffaeac36978d38c2c0f6d1104c2137.tar.gz' \
        -o "$TEMP/mtproxy.tar.gz"
    echo "919795c416b870670841a21d1930ad97a24c7b84b9eb8c6f9e3de32f2fdf4655  $TEMP/mtproxy.tar.gz" |
        sha256sum -c - >/dev/null
    install -d -m 0755 "$TEMP/mtproxy-build"
    tar -xzf "$TEMP/mtproxy.tar.gz" -C "$TEMP/mtproxy-build" --strip-components=1
    make -C "$TEMP/mtproxy-build" -j"$(nproc)"
    [[ -x "$TEMP/mtproxy-build/objs/bin/mtproto-proxy" ]] || exit 4
    install -d -m 0755 /opt/MTProxy/objs/bin
    install -m 0755 "$TEMP/mtproxy-build/objs/bin/mtproto-proxy" /opt/MTProxy/objs/bin/mtproto-proxy
fi
if ! getent group mtproxy >/dev/null 2>&1; then groupadd --system mtproxy; fi
if ! id mtproxy >/dev/null 2>&1; then
    useradd --system --gid mtproxy --home-dir /nonexistent --shell /usr/sbin/nologin mtproxy
fi
install -d -m 0750 -o root -g mtproxy /etc/mtproxy
# The same bootstrap files shipped with the tested WPO installer.
curl -4fLsS --proto '=https' --proto-redir '=https' --retry 3 \
    "$BASE/assets/mtproxy-bootstrap/proxy-secret" -o "$TEMP/proxy-secret"
curl -4fLsS --proto '=https' --proto-redir '=https' --retry 3 \
    "$BASE/assets/mtproxy-bootstrap/proxy-multi.conf" -o "$TEMP/proxy-multi.conf"
[[ "$(wc -c < "$TEMP/proxy-secret")" == 128 ]] || exit 4
grep -q '^default ' "$TEMP/proxy-multi.conf" || exit 4
grep -q '^proxy_for ' "$TEMP/proxy-multi.conf" || exit 4
install -o root -g mtproxy -m 0640 "$TEMP/proxy-secret" /etc/mtproxy/proxy-secret
install -o root -g mtproxy -m 0640 "$TEMP/proxy-multi.conf" /etc/mtproxy/proxy-multi.conf

# Pinned browser HTTPS transport relay for Telegram WEB Proxy and public site.
GO=/opt/go1.26.5/bin/go
if [[ ! -x "$GO" ]]; then
    curl -4fLsS --proto '=https' --proto-redir '=https' --retry 3 \
        --connect-timeout 20 --max-time 240 \
        'https://go.dev/dl/go1.26.5.linux-amd64.tar.gz' \
        -o "$TEMP/go.tar.gz"
    echo "5c2c3b16caefa1d968a94c1daca04a7ca301a496d9b086e17ad77bb81393f053  $TEMP/go.tar.gz" |
        sha256sum -c - >/dev/null
    install -d /opt/go1.26.5
    tar -xzf "$TEMP/go.tar.gz" -C "$TEMP"
    cp -a "$TEMP/go/." /opt/go1.26.5/
fi
if [[ ! -x /usr/local/bin/tproxy-server ]]; then
    mkdir -p "$TEMP/relay"
    git -C "$TEMP/relay" init -q
    git -C "$TEMP/relay" remote add origin https://github.com/telegramdesktop/tproxy-server.git
    git -C "$TEMP/relay" fetch -q --depth 1 origin 52a5feb7fac38f68da5afef9cedd9b3bfc8473ca
    git -C "$TEMP/relay" checkout -q --detach FETCH_HEAD
    [[ "$(git -C "$TEMP/relay" rev-parse HEAD)" == 52a5feb7fac38f68da5afef9cedd9b3bfc8473ca ]] || exit 4
    (cd "$TEMP/relay" && "$GO" test ./internal/config ./internal/server -run '^TestWPO' -count=1)
    (cd "$TEMP/relay" && "$GO" build -trimpath -ldflags='-s -w' \
        -o /usr/local/bin/tproxy-server ./cmd/tproxy-server)
fi
if ! id tproxy >/dev/null 2>&1; then
    useradd --system --home /var/lib/tproxy --create-home --shell /usr/sbin/nologin tproxy
fi
install -d -o root -g tproxy -m 0750 /etc/tproxy-server
install -d -m 0755 /var/www/wpp-node-site
cat >/etc/tproxy-server/config.json <<'RELAY_CFG'
{
 "public_hostname": "__DOMAIN__",
 "listen": "127.0.0.1:8080",
 "admin_listen": "127.0.0.1:8081",
 "public_dir": "/var/www/wpp-node-site",
 "profiles_file": "/run/credentials/wpo-node-relay.service/profiles.json"
}
RELAY_CFG
python3 - <<'PY_DOMAIN'
from pathlib import Path
import json
p=Path('/etc/tproxy-server/config.json')
domain=json.loads(Path('/etc/wpp-node-agent/config.json').read_text())['domain']
doc=json.loads(p.read_text())
doc['public_hostname']=domain
p.write_text(json.dumps(doc,indent=2)+'\n')
PY_DOMAIN
chown root:tproxy /etc/tproxy-server/config.json
chmod 0640 /etc/tproxy-server/config.json
# The upstream Go relay REJECTS an empty profile registry. Install a
# private, nonfunctional bootstrap profile (unknown random credential)
# until the first real WEB Proxy user is provisioned.
if [[ ! -s /etc/wpp-node-vpn/relay-bootstrap-secret ]]; then
    openssl rand -hex 16 > /etc/wpp-node-vpn/relay-bootstrap-secret
    chmod 0600 /etc/wpp-node-vpn/relay-bootstrap-secret
fi
python3 - <<'PY_RELAY'
from pathlib import Path
import json
p=Path('/etc/tproxy-server/profiles.json')
if p.exists():
    try:
        data=json.loads(p.read_text())
    except (ValueError,OSError):
        data={}
    if isinstance(data,dict) and isinstance(data.get('profiles'),list) and data['profiles']:
        raise SystemExit(0)
secret=Path('/etc/wpp-node-vpn/relay-bootstrap-secret').read_text().strip()
p.write_text(json.dumps({'profiles':[{
    'name':'node-bootstrap','secret':secret,
    'backend':'127.0.0.1:2398','carrier_mode':'https'
}]})+'\\n')
PY_RELAY
chown root:tproxy /etc/tproxy-server/profiles.json
chmod 0400 /etc/tproxy-server/profiles.json
cat > /etc/systemd/system/wpo-node-relay.service <<'UNIT'
[Unit]
Description=WPO Node HTTPS WEB Proxy and site relay
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=tproxy
Group=tproxy
LoadCredential=profiles.json:/etc/tproxy-server/profiles.json
ExecStart=/usr/local/bin/tproxy-server -config /etc/tproxy-server/config.json
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadOnlyPaths=/var/www/wpp-node-site
[Install]
WantedBy=multi-user.target
UNIT

# Install pinned WPO AWG 2.0/3.1 userspace stack and official CLI.
download assets/amneziawg-go-linux-amd64 "$TEMP/amneziawg-go" \
  9b8912d203ba7142c1957913047bb9efd6e02c173c1f3bf852c652b16aada60f
download assets/awg-linux-amd64 "$TEMP/awg" \
  23d29323258166183eeeb288c1f9f08b879f3707e54591b1bfb2402413f6d8d8
download assets/awg-quick-linux-amd64 "$TEMP/awg-quick" \
  f4bb0f5d63665ade87f0cb9f2185c43515cff09868637eb311f98f65a318722c
install -m 0755 "$TEMP/amneziawg-go" /usr/local/bin/amneziawg-go
install -m 0755 "$TEMP/awg" /usr/local/bin/awg
install -m 0755 "$TEMP/awg-quick" /usr/local/bin/awg-quick
/usr/local/bin/awg --version >/dev/null

# AWG unit helpers match the main WPO's tested userspace structure.
cat > /usr/local/sbin/web-panel-proxy-awg-run <<'PY_RUN'
#!/usr/bin/env python3
import json,os,re,sys
uid=sys.argv[1] if len(sys.argv)>1 else ''
if not re.fullmatch(r'[a-f0-9]{16}',uid): raise SystemExit('Invalid AWG ID')
with open('/etc/web-proxy-panel/awg/'+uid+'.json') as f: iface=json.load(f)['interface']
if not re.fullmatch(r'wa[a-f0-9]{11}',iface): raise SystemExit('Invalid AWG interface')
os.execv('/usr/local/bin/amneziawg-go',['amneziawg-go','-f',iface])
PY_RUN
cat > /usr/local/sbin/web-panel-proxy-awg-up <<'PY_UP'
#!/usr/bin/env python3
import json,os,re,subprocess,sys,time
uid=sys.argv[1] if len(sys.argv)>1 else ''
if not re.fullmatch(r'[a-f0-9]{16}',uid): raise SystemExit('Invalid AWG ID')
base='/etc/web-proxy-panel/awg/'+uid
with open(base+'.json') as f: meta=json.load(f)
iface=str(meta['interface']); address=str(meta['address']); mtu=int(meta['mtu'])
if not re.fullmatch(r'wa[a-f0-9]{11}',iface) or not 1024 <= mtu <= 1420:
    raise SystemExit('Invalid AWG network interface')
for _ in range(80):
    if os.path.exists('/var/run/amneziawg/'+iface+'.sock') or os.path.exists('/sys/class/net/'+iface): break
    time.sleep(.1)
else: raise SystemExit('AWG interface never appeared')
subprocess.run(['/usr/local/bin/awg','setconf',iface,base+'.conf'],check=True)
subprocess.run(['/usr/sbin/ip','address','replace',address,'dev',iface],check=True)
subprocess.run(['/usr/sbin/ip','link','set','mtu',str(mtu),'up','dev',iface],check=True)
PY_UP
cat > /usr/local/sbin/web-panel-proxy-awg-down <<'PY_DOWN'
#!/usr/bin/env python3
import json,re,subprocess,sys
uid=sys.argv[1] if len(sys.argv)>1 else ''
if not re.fullmatch(r'[a-f0-9]{16}',uid): raise SystemExit(0)
try:
    with open('/etc/web-proxy-panel/awg/'+uid+'.json') as f: iface=json.load(f)['interface']
except Exception: iface='wa'+uid[:11]
if re.fullmatch(r'wa[a-f0-9]{11}',iface):
    subprocess.run(['/usr/sbin/ip','link','delete',iface],
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
PY_DOWN
chmod 0755 /usr/local/sbin/web-panel-proxy-awg-{run,up,down}
cat > /etc/systemd/system/web-panel-proxy-awg@.service <<'UNIT'
[Unit]
Description=WPO Node independent AmneziaWG profile %i
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
Group=root
UMask=0077
Environment=WG_PROCESS_FOREGROUND=1
Environment=LOG_LEVEL=error
ExecStartPre=-/usr/local/sbin/web-panel-proxy-awg-down %i
ExecStart=/usr/local/sbin/web-panel-proxy-awg-run %i
ExecStartPost=/usr/local/sbin/web-panel-proxy-awg-up %i
ExecStopPost=-/usr/local/sbin/web-panel-proxy-awg-down %i
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/sysctl.d/90-wpo-node-awg.conf <<'SYSCTL'
net.ipv4.ip_forward=1
SYSCTL
sysctl -p /etc/sysctl.d/90-wpo-node-awg.conf >/dev/null

# AWG peers are isolated per /30 in 10.80–83.x.x, like the base WPO.
cat >/usr/local/sbin/wpo-node-awg-nat <<'NAT'
#!/usr/bin/env bash
set -Eeuo pipefail
nft list table ip wpo_node_awg_nat >/dev/null 2>&1 && nft delete table ip wpo_node_awg_nat
nft add table ip wpo_node_awg_nat
nft 'add chain ip wpo_node_awg_nat postrouting { type nat hook postrouting priority srcnat; policy accept; }'
nft add rule ip wpo_node_awg_nat postrouting ip saddr 10.80.0.0/14 oifname != "lo" masquerade
NAT
chmod 0755 /usr/local/sbin/wpo-node-awg-nat
cat >/etc/systemd/system/wpo-node-awg-nat.service <<'UNIT'
[Unit]
Description=WPO Node NAT for isolated AmneziaWG peers
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/wpo-node-awg-nat
RemainAfterExit=true
[Install]
WantedBy=multi-user.target
UNIT

# Existing full WPO NaiveProxy and Mieru engines with pinned checksums.
download assets/caddy-forwardproxy-naive-v2.11.7-naive2.tar.xz "$TEMP/naive.tar.xz" \
  c273dc07dd79c5919f97639cbdcb559d40ce90475dbd8aac80641b0a8c8065ff
download assets/mita-v3.39.0-linux-amd64.tar.gz "$TEMP/mita.tar.gz" \
  ea35fdef84bef1378f32b74a2d5a883d508a49dd4e64dba9a3a8363beed5798c
tar -xJf "$TEMP/naive.tar.xz" -C "$TEMP"
tar -xzf "$TEMP/mita.tar.gz" -C "$TEMP"
install -m 0755 "$TEMP/caddy-forwardproxy-naive/caddy" /usr/local/bin/caddy-naive
install -m 0755 "$TEMP/mita" /usr/local/bin/mita-wpp
if ! getent group mita >/dev/null 2>&1; then groupadd --system mita; fi
if ! id mita >/dev/null 2>&1; then
    useradd --system --gid mita --home-dir /var/lib/mita \
        --create-home --shell /usr/sbin/nologin mita
fi
install -d -o root -g root -m 0755 /etc/web-proxy-panel/extra-protocols
cat > /etc/systemd/system/web-panel-proxy-naive.service <<'UNIT'
[Unit]
Description=WPO Node NaiveProxy
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy-naive run --config /etc/web-proxy-panel/extra-protocols/Caddyfile.naive --adapter caddyfile
Restart=on-failure
RestartSec=2
LimitNOFILE=1048576
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/web-panel-proxy-mieru.service <<'UNIT'
[Unit]
Description=WPO Node Mieru
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=mita
Group=mita
Environment=MITA_CONFIG_JSON_FILE=/etc/web-proxy-panel/extra-protocols/mieru-server.json
Environment=MITA_UDS_PATH=/run/mita-wpp/mita.sock
Environment=MITA_LOG_NO_TIMESTAMP=true
RuntimeDirectory=mita-wpp
RuntimeDirectoryMode=0750
ExecStart=/usr/local/bin/mita-wpp run
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
[Install]
WantedBy=multi-user.target
UNIT

# Deploy authoritative WPO server engines; save credentials only on node VPS.
for module in wpp_awg.py wpp_extra_protocols.py wpo_node_eight.py; do
    curl -4fLsS --proto '=https' --proto-redir '=https' --retry 3 \
        --connect-timeout 15 --max-time 90 \
        "$BASE/$module" -o "$TEMP/$module"
    python3 -m py_compile "$TEMP/$module"
    install -m 0700 "$TEMP/$module" "/opt/wpp-node-agent/$module"
done

# Run the public site through the same Go relay that Telegram WEB Proxy needs.
# Node API routes and the user's XHTTP path retain higher-priority Caddy rules.
python3 - <<'PY_CADDY'
from pathlib import Path
p=Path('/etc/caddy/Caddyfile')
s=p.read_text()
old='''    handle {
        root * /var/www/wpp-node-site
        try_files {path} /index.html
        file_server
    }'''
new='''    handle {
        reverse_proxy 127.0.0.1:8080 {
            transport http {
                response_header_timeout 40s
            }
        }
    }'''
if new not in s:
    if s.count(old)!=1: raise SystemExit('Node Caddy site changed; refusing to replace it.')
    p.with_suffix('.eight-caddy-test').write_text(s.replace(old,new))
else:
    p.with_suffix('.eight-caddy-test').write_text(s)
PY_CADDY
caddy validate --config /etc/caddy/Caddyfile.eight-caddy-test --adapter caddyfile >/dev/null || {
    echo 'Go relay Caddyfile is invalid; existing site left unchanged.' >&2
    exit 4
}

# The official MTProxy binary binds on all interfaces, even for WEB-only
# backends. Drop external WEB backends and both protocols' stats ports.
# Direct Telegram MTProto :25000-25949 remains reachable by design.
cat >/usr/local/sbin/wpo-node-mt-firewall <<'FIREWALL'
#!/usr/bin/env bash
set -Eeuo pipefail
nft list table inet wpo_node_mt_guard >/dev/null 2>&1 &&
    nft delete table inet wpo_node_mt_guard
nft add table inet wpo_node_mt_guard
nft 'add chain inet wpo_node_mt_guard input { type filter hook input priority -150; policy accept; }'
nft add rule inet wpo_node_mt_guard input iifname != "lo" tcp dport 24000-24949 drop
nft add rule inet wpo_node_mt_guard input iifname != "lo" tcp dport 27000-28949 drop
FIREWALL
chmod 0755 /usr/local/sbin/wpo-node-mt-firewall
cat >/etc/systemd/system/wpo-node-mt-firewall.service <<'UNIT'
[Unit]
Description=WPO restrict external MTProxy WEB and stats ports
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/wpo-node-mt-firewall
RemainAfterExit=true
[Install]
WantedBy=multi-user.target
UNIT

# Switch the localhost-only authenticated VPN API to the eight-engine backend
# after the verified binaries and services have been installed.
systemctl daemon-reload
systemctl enable --now wpo-node-mt-firewall.service
systemctl enable --now wpo-node-awg-nat.service
systemctl enable wpo-node-relay.service
systemctl restart wpo-node-relay.service
systemctl is-active --quiet wpo-node-relay.service || {
    echo 'Node WEB relay could not start; inspect journalctl -u wpo-node-relay' >&2
    exit 4
}
mv -f /etc/caddy/Caddyfile.eight-caddy-test /etc/caddy/Caddyfile
systemctl reload caddy.service
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
    ufw route allow from 10.80.0.0/14 to any >/dev/null
    ufw allow 25000:25949/tcp >/dev/null
    ufw allow 52000:52999/udp >/dev/null
    ufw allow 53000/tcp >/dev/null
    ufw allow 54000/tcp >/dev/null
fi
# Inform the API server to dynamically import the existing native backends.
systemctl restart wpo-node-vpn.service
systemctl restart wpp-node-agent.service
python3 - <<'PY_VERIFY'
import sys
sys.path.insert(0,'/opt/wpp-node-agent')
import wpo_node_eight
caps=wpo_node_eight.available()
missing=sorted(wpo_node_eight.KNOWN-set(caps))
if missing: raise SystemExit('Missing WPO node backends: '+', '.join(missing))
print('✓ Eight installed and available engine backends: '+', '.join(sorted(caps)))
PY_VERIFY
# Authenticate the real capability list through the existing node agent API.
# Never advertise all eight until the actual binaries/services pass checks.
python3 - <<'PY_AGENT'
from pathlib import Path
import json,os,tempfile
p=Path('/opt/wpp-node-agent/agent.py')
s=p.read_text()
old="['federation','vless','hysteria'] if vpn_ready() else []"
if "vpn_capabilities()" not in s:
    if s.count(old)!=1: raise SystemExit('Unexpected Node Agent status implementation')
    anchor='class H(BaseHTTPRequestHandler):'
    helper="""def vpn_capabilities():
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:9089/healthz',timeout=3) as result:
            data=__import__('json').loads(result.read(8192))
        if not data.get('ok'): return []
        caps=data.get('capabilities',[])
        if not isinstance(caps,list): return []
        return [str(v) for v in caps if isinstance(v,str)][:16]
    except Exception:
        return []

"""
    if s.count(anchor)!=1: raise SystemExit('Unexpected agent source; no change made')
    s=s.replace(anchor,helper+anchor).replace(old,"vpn_capabilities()")
    compile(s,str(p),'exec')
    p.write_text(s)
settings=Path('/etc/wpp-node-agent/config.json')
config=json.loads(settings.read_text())
config['version']='0.4.0'
fd,tmp=tempfile.mkstemp(dir=str(settings.parent))
with os.fdopen(fd,'w') as stream:
    json.dump(config,stream);stream.write('\n')
os.chmod(tmp,0o600);os.replace(tmp,settings)
PY_AGENT
systemctl restart wpp-node-agent.service
systemctl is-active --quiet wpp-node-agent.service || {
    echo 'Node Agent failed to advertise all eight working engines.' >&2
    exit 4
}
echo '✓ Node Agent 0.4: all eight engine capabilities available for registration.'
