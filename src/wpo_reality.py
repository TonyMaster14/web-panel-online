"""REALITY node profile, server inbound and client URI. Private key stays on server."""
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import tempfile
from urllib.parse import quote, urlencode
ROOT = Path('/etc/web-proxy-panel/reality')
PUBLIC = ROOT / 'profile.json'
PRIVATE = ROOT / 'private.key'
PORT = 19444
# NVIDIA is the verified default for fresh panel and remote-node REALITY.
# Microsoft is not offered as a target; existing profile files are preserved.
PRESETS = {'nvidia': ('NVIDIA', 'www.nvidia.com'), 'apple': ('Apple', 'www.apple.com'),
           'yahoo': ('Yahoo', 'www.yahoo.com'), 'amazon': ('Amazon', 'www.amazon.com')}
DEFAULT = {'preset': 'nvidia', 'sni': 'www.nvidia.com', 'fingerprint': 'firefox', 'port': 443}

def normalize(value):
    result = dict(DEFAULT, **value)
    if result['preset'] in PRESETS: result['sni'] = PRESETS[result['preset']][1]
    elif result['preset'] != 'custom': raise ValueError('Неизвестный пресет REALITY')
    host = str(result['sni']).strip().lower().rstrip('.')
    if not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', host):
        raise ValueError('Укажите корректный SNI REALITY')
    if result['fingerprint'] not in ('firefox', 'edge'): raise ValueError('Выберите Mozilla Firefox или Edge')
    return {'preset': result['preset'], 'sni': host, 'fingerprint': result['fingerprint'], 'port': 443}

def read_profile(): return json.loads(PUBLIC.read_text())

def atomic(path, content, mode=0o600):
    path = Path(path)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content); f.flush(); os.fsync(f.fileno())
        os.chmod(temp, mode); os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def check_target(sni):
    addresses = socket.getaddrinfo(sni, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Цель REALITY должна иметь публичный IP')
    if PUBLIC.exists() and read_profile().get('address') in {a[4][0] for a in addresses}:
        raise ValueError('SNI должен вести на внешний сайт, а не на эту ноду')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.set_alpn_protocols(['h2'])
    with socket.create_connection((addresses[0][4][0], 443), timeout=8) as raw:
        with context.wrap_socket(raw, server_hostname=sni) as conn:
            if conn.selected_alpn_protocol() != 'h2': raise ValueError('Цель REALITY не поддерживает HTTP/2')
    return True

def initialize(xray, address):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o755)
    if PUBLIC.exists() and PRIVATE.exists(): return read_profile()
    output = subprocess.check_output([xray, 'x25519'], text=True, timeout=10)
    fields = dict(line.split(':', 1) for line in output.splitlines() if ':' in line)
    private = fields.get('PrivateKey', fields.get('Private key', '')).strip()
    public = fields.get('Password (PublicKey)', fields.get('Password', fields.get('PublicKey', fields.get('Public key', '')))).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', private) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', public):
        raise RuntimeError('Xray не вернул ключи X25519')
    profile = dict(DEFAULT, address=address, public_key=public, short_id=secrets.token_hex(8))
    check_target(profile['sni'])
    atomic(PRIVATE, private)
    atomic(PUBLIC, json.dumps(profile), 0o644)
    return profile

def inbound(clients, profile=None):
    profile = profile or read_profile()
    return {'tag': 'vless-reality', 'listen': '127.0.0.1', 'port': PORT,
            'protocol': 'vless', 'settings': {'decryption': 'none', 'clients': clients},
            'streamSettings': {'network': 'tcp', 'security': 'reality',
                'realitySettings': {'show': False, 'target': profile['sni'] + ':443',
                    'serverNames': [profile['sni']], 'privateKey': PRIVATE.read_text().strip(),
                    'shortIds': [profile['short_id']]}},
            'sniffing': {'enabled': True, 'destOverride': ['http','tls','quic'], 'routeOnly': True}}

def link(secret, name, profile=None):
    p = profile or read_profile()
    address = p['address']
    if ':' in address: address = '[' + address + ']'
    query = urlencode({'encryption': 'none', 'security': 'reality', 'type': 'tcp',
                       'flow': 'xtls-rprx-vision', 'sni': p['sni'], 'fp': p['fingerprint'],
                       'pbk': p['public_key'], 'sid': p['short_id']})
    return 'vless://' + quote(secret, safe='-') + '@' + address + ':443?' + query + '#' + quote(name + ' · REALITY', safe='')

def haproxy_config(sni):
    sni = normalize({'preset':'custom', 'sni':sni})['sni']
    return '''global
    maxconn 4096
    user haproxy
    group haproxy
defaults
    mode tcp
    timeout connect 10s
    timeout client 1h
    timeout server 1h
frontend wpo_tls
    bind 0.0.0.0:443
    bind [::]:443 v6only
    tcp-request inspect-delay 5s
    tcp-request content accept if { req.ssl_hello_type 1 }
    use_backend reality if { req.ssl_sni -i ''' + sni + ''' }
    default_backend website
backend reality
    server reality 127.0.0.1:19444
backend website
    server caddy 127.0.0.1:19443
'''

def _caddy_block_end(text, start):
    """Find a block boundary without counting braces in strings or comments."""
    depth=0; quote=None; escaped=False; comment=False
    for index in range(start,len(text)):
        ch=text[index]
        if comment:
            if ch=='\n':comment=False
            continue
        if quote:
            if escaped:escaped=False
            elif ch=='\\' and quote=='"':escaped=True
            elif ch==quote:quote=None
            continue
        if ch=='#':comment=True
        elif ch in ('"','`'):quote=ch
        elif ch=='{':depth+=1
        elif ch=='}':
            depth-=1
            if depth==0:return index
    raise ValueError('Незакрытый блок Caddyfile')


def caddy_internal(text):
    text = re.sub(r'(?m)^([^\s{}][^{}\n]*\{)', lambda m: re.sub(r':443(?=[,\s{])', ':19443', m[0]), text)
    # Replace our previous fragment, including the legacy standalone servers
    # block. Preserve the rest of the existing global configuration.
    text=re.sub(r'\n[ \t]*# wpo-reality-front\n[ \t]*https_port 19443\n[ \t]*default_bind 127\.0\.0\.1\n(?:[ \t]*# wpo-reality-front-end\n|[ \t]*servers \{\n[ \t]*protocols h1 h2\n[ \t]*\}\n)','\n',text,count=1)
    match=re.match(r'(?:\s|#[^\n]*\n)*\{',text)
    if not match:
        text='{\n}\n'+text;start=0
    else:start=match.end()-1
    end=_caddy_block_end(text,start)
    body=text[start+1:end]
    # Respect existing servers options: adding a second catch-all servers
    # block is rejected by Caddy as duplicate listener addresses.
    server=re.search(r'(?m)^[ \t]*servers[ \t]*\{',body)
    if server:
        opening=server.end()-1;closing=_caddy_block_end(body,opening)
        content=body[opening+1:closing]
        content=re.sub(r'(?m)^[ \t]*protocols[ \t]+[^\n#]+','',content)
        content='\n        protocols h1 h2\n'+'\n'.join(line for line in content.splitlines() if line.strip())
        body=body[:opening+1]+content.rstrip('\n')+'\n    '+body[closing:]
    else:
        body+='    servers {\n        protocols h1 h2\n    }\n'
    body=re.sub(r'(?m)^[ \t]*(?:https_port|default_bind)[ \t]+[^\n]+\n?','',body)
    options='\n    # wpo-reality-front\n    https_port 19443\n    default_bind 127.0.0.1\n    # wpo-reality-front-end\n'
    return text[:start+1]+options+body.lstrip('\n')+text[end:]

def install_manager(ns):
    original=ns['sync_xray']; activate=ns['activate_xray_config']
    def sync(data):
        clients=[]
        registry=ns['wpp_connections'].ensure(ns['CONNECTIONS'],data['users'],persist=False)
        enabled={c['id'] for c in registry['connections'] if c.get('enabled',True)}
        for user in data['users']:
            if user.get('protocol')=='reality' and user.get('enabled',True) and user.get('connection_id','reality-primary') in enabled:
                for index, secret in enumerate(ns['direct_secrets'](user),1):
                    clients.append({'id':secret,'flow':'xtls-rprx-vision','level':0,
                                    'email':'panel:'+user['id']+':'+str(index)})
        def with_reality(config, caddy_text=None, validation_inbounds=None):
            config=copy.deepcopy(config); config['inbounds'].append(inbound(clients))
            config.setdefault('api',{}).setdefault('services',[]).append('HandlerService')
            import wpo_xray_live
            old_caddy=Path(ns['CADDYFILE']).read_text()
            if (caddy_text is None or caddy_text==old_caddy) and not validation_inbounds:
                if wpo_xray_live.try_apply(config,ns['XRAY_CONFIG'],ns['XRAY_BIN'],ns['XRAY_SERVICE'],ns['XRAY_API']):
                    return
            return activate(config,caddy_text,validation_inbounds)
        ns['activate_xray_config']=with_reality
        try: return original(data)
        finally: ns['activate_xray_config']=activate
    ns['sync_xray']=sync

def install_panel(ns):
    original=ns['proxy_link']
    def proxy_link(protocol, secret, port, name='', username=''):
        if protocol=='reality': return link(secret, name or 'WPO')
        return original(protocol,secret,port,name,username)
    ns['proxy_link']=proxy_link

def configure(request, apply_xray):
    value=normalize(request)
    check_target(value['sni'])
    # End-to-end proof: TLS 1.3/HTTP2 success alone is not sufficient. Some
    # decoys (formerly Microsoft) return a >8192-byte certificate TLS record,
    # making REALITY fail despite apparently valid certificates.
    import wpo_reality_probe
    result=wpo_reality_probe.probe(value['sni'],value['fingerprint'],__import__(__name__))
    if request.get('check_only'): return result
    old=read_profile()
    new=dict(old, **value)
    config_path=ROOT/'haproxy.cfg'
    old_config=config_path.read_text()
    atomic(config_path,haproxy_config(new['sni']))
    try:
        subprocess.run(['haproxy','-c','-f',str(config_path)],check=True,capture_output=True)
        atomic(PUBLIC,json.dumps(new),0o644)
        apply_xray()
        subprocess.run(['systemctl','reload','wpo-tls-router'],check=True,capture_output=True)
    except Exception:
        atomic(PUBLIC,json.dumps(old),0o644);atomic(config_path,old_config)
        apply_xray()
        subprocess.run(['systemctl','reload','wpo-tls-router'],check=True,capture_output=True)
        raise
    return dict(result,message='REALITY сохранён. Обновите подписки на устройствах.')

def install_happ(ns):
    """Prepare the newly allocated device identities before the user imports Happ."""
    import concurrent.futures
    import threading
    import wpo_happ_async_feed as feed
    original=ns['ctl_subscription']
    def warm(sid):
        try:
            sub=next((s for s in ns['subscription_registry']() if s.get('id')==sid and s.get('enabled',True)),None)
            if not sub:return
            chosen=set(sub.get('node_ids',['local']))
            nodes=[n for n in ns['node_api'].load_nodes(ns['NODES_FILE']) if n.get('id') in chosen and n.get('enabled',True)]
            protocols=tuple(sub.get('protocols',[]))
            def node_job(node):
                for device in sub.get('devices',[]):
                    if device.get('revoked'):continue
                    ext=ns['federation_id'](sid,device['id'])
                    current=next((s for s in ns['subscription_registry']() if s.get('id')==sid and s.get('enabled',True)),None)
                    if not current:return
                    try:
                        feed.warm(ns['node_api'],node,ext,ns['node_api'].location_prefix(node),protocols)
                        current=next((s for s in ns['subscription_registry']() if s.get('id')==sid and s.get('enabled',True)),None)
                        if not current or not any(d.get('id')==device['id'] and not d.get('revoked') for d in current.get('devices',[])):
                            ns['node_api'].delete_profile(node,ext)
                            feed.invalidate_all()
                    except Exception:pass  # Fetch retries authenticated provisioning; no phantom profiles.
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(node_job,nodes))
        except Exception:pass
    def ctl(request):
        result=original(request)
        if result.get('ok') and request.get('operation')!='fetch':
            feed.invalidate_all()
            if request.get('operation') in ('create','update','rotate','allow'):
                sid=result.get('id') or request.get('id')
                threading.Thread(target=warm,args=(sid,),name='wpo-happ-prepare',daemon=True).start()
        return result
    ns['ctl_subscription']=ctl
