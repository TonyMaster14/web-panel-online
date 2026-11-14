#!/usr/bin/env bash
# wpo-node-agent-reinstall-v23: restart agent after key rotation and explain enrollment failures
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
TOKEN="$1"
[[ "$TOKEN" =~ ^[A-Za-z0-9_-]{40,60}$ ]] || { echo 'Одноразовый ключ не передан.'; exit 2; }
ENROLL_URL="__WPO_CONTROLLER_ENROLL_URL__"
STATUS_URL="__WPO_CONTROLLER_STATUS_URL__"
DOMAIN=""
EMAIL=""
report() {
  local current_domain="$DOMAIN"
  if [[ $# -ge 3 && -n "$3" ]]; then current_domain="$3"; fi
  python3 - "$TOKEN" "$1" "$2" "$current_domain" <<'PY_STATUS' | curl -fsS --max-time 8 -H 'Content-Type: application/json' --data-binary @- "$STATUS_URL" >/dev/null 2>&1 || true
import json,sys
print(json.dumps({'token':sys.argv[1],'status':sys.argv[2],'detail':sys.argv[3],'domain':sys.argv[4]}))
PY_STATUS
}
fail() {
  rc=$?
  trap - ERR
  report error "Установщик завершился с ошибкой (код $rc)."
  echo "Установка завершилась с ошибкой ($rc)."
  exit "$rc"
}
trap fail ERR
report installing 'Проверка VPS и домена.'
echo '=== WEB PANEL ONLINE — Node Agent 0.2 ==='
read -r -p 'Домен ноды (например, de.example.com): ' DOMAIN
DOMAIN=$(printf '%s' "$DOMAIN" | sed -E 's#^https?://##; s#/.*$##' | tr '[:upper:]' '[:lower:]')
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || { report error 'Некорректный домен.'; echo 'Некорректный домен.'; exit 2; }
# Email is required for Let's Encrypt. Fix accidental non-ASCII paste
# characters at the edges, but never silently modify the middle of an address.
for EMAIL_ATTEMPT in 1 2 3; do
  if ! IFS= read -r -p "Email для Let's Encrypt (латиница, EN): " EMAIL; then
    report error 'Email не введён.'
    echo 'Email не введён. Установка остановлена.'
    exit 2
  fi
  if VALIDATED_EMAIL="$(python3 - "$EMAIL" <<'PY_VALIDATE_EMAIL'
import re
import sys

original = sys.argv[1]
value = original.strip(" \t\r\n\ufeff\u200b\u2060")
while value and not value[0].isascii():
    value = value[1:]
while value and not value[-1].isascii():
    value = value[:-1]
local, sep, host = value.partition("@")
local_ok = (
    1 <= len(local) <= 64
    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*", local) is not None
    and not local.endswith(".")
    and ".." not in local
)
host_ok = re.fullmatch(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}",
    host,
) is not None
if value.isascii() and len(value) <= 254 and sep and local_ok and host_ok:
    if value != original:
        print("Убраны случайные символы по краям email.", file=sys.stderr)
    print(value)
else:
    print("Проверьте email: только латинские буквы, без лишних символов.", file=sys.stderr)
    sys.exit(1)
PY_VALIDATE_EMAIL
)"; then
    EMAIL="$VALIDATED_EMAIL"
    break
  fi
  if [[ "$EMAIL_ATTEMPT" == "3" ]]; then
    report error 'Email указан некорректно после трёх попыток.'
    echo 'Установка остановлена: неверный email.'
    exit 2
  fi
  echo 'Повторите ввод email в английской раскладке.'
done
. /etc/os-release
case "$ID" in
  ubuntu) dpkg --compare-versions "$VERSION_ID" ge 22.04 || { echo 'Требуется Ubuntu 22.04+.'; exit 2; } ;;
  debian) dpkg --compare-versions "$VERSION_ID" ge 12 || { echo 'Требуется Debian 12+.'; exit 2; } ;;
  *) echo 'Поддерживаются Ubuntu 22.04+ и Debian 12+.'; exit 2 ;;
esac
report installing 'Установка Caddy и подготовка сайта ноды.'
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates gnupg python3
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y --no-install-recommends caddy
fi
PUBLIC_IP="$(curl -4fsS --max-time 10 https://api.ipify.org)"
getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | grep -Fxq "$PUBLIC_IP" || { report error "DNS A-запись должна указывать на $PUBLIC_IP."; echo "DNS A-запись $DOMAIN должна указывать на $PUBLIC_IP."; exit 3; }
install -d -m 0755 /opt/wpp-node-agent /var/www/wpp-node-site
install -d -m 0700 /etc/wpp-node-agent
API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 - "$DOMAIN" "$EMAIL" "$API_KEY" <<'PY_CFG'
import json,os,sys,tempfile
p='/etc/wpp-node-agent/config.json'
d={'domain':sys.argv[1],'email':sys.argv[2],'api_key':sys.argv[3],'version':'0.2.0'}
fd,t=tempfile.mkstemp(dir=os.path.dirname(p))
with os.fdopen(fd,'w',encoding='utf-8') as f:
    json.dump(d,f); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.chmod(t,0o600); os.replace(t,p)
PY_CFG
cat > /opt/wpp-node-agent/agent.py <<'PY_AGENT'
#!/usr/bin/env python3
import base64
import binascii
import hmac
import json
import os
import re
import tempfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
CONFIG='/etc/wpp-node-agent/config.json'
SITE='/var/www/wpp-node-site'
C=json.load(open(CONFIG,encoding='utf-8'))
KEY=C['api_key']
DOMAIN=C['domain']
DEFAULT_HTML='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0c111b"><title>Сервер работает</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 80% 10%,#24304b,#0c111b 52%);color:#eef3ff;font:15px system-ui,sans-serif}.box{width:min(520px,calc(100% - 36px));padding:36px;border:1px solid #ffffff1c;border-radius:24px;background:#111a2bcc;box-shadow:0 25px 80px #0007}.dot{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:50%;background:#36d399;box-shadow:0 0 18px #36d399}h1{margin:18px 0 8px;font-size:30px}p{margin:0;color:#aab7ce;line-height:1.65}.tag{color:#8fa4c6;font-size:11px;letter-spacing:.14em;text-transform:uppercase}</style></head><body><main class="box"><span class="dot"></span><span class="tag">Node Agent online</span><h1>Сервер работает</h1><p>Подключение ноды активно. Владелец панели может назначить этой ноде шаблон сайта.</p></main></body></html>'''
ASSET_RE=re.compile(r'^preset-[A-Za-z0-9_.-]{1,110}\.webp$',re.I)
def location():
    try:
        import urllib.request
        with urllib.request.urlopen('https://ipapi.co/json/',timeout=4) as r:
            d=json.loads(r.read(65536))
        code=str(d.get('country_code','UN')).upper()
        if not re.fullmatch(r'[A-Z]{2}',code): code='UN'
        return {'country_code':code,'country_name':str(d.get('country_name') or 'Сервер')[:80],'name':str(d.get('country_name') or 'Сервер')[:80]}
    except Exception:
        return {'country_code':'UN','country_name':'Сервер','name':'Сервер'}
def atomic_write(path,data,mode=0o644):
    fd,tmp=tempfile.mkstemp(prefix='.wpo-site-',dir=os.path.dirname(path))
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(tmp,mode); os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
def save_config():
    tmp=CONFIG+'.tmp'
    with open(tmp,'w',encoding='utf-8') as stream:
        json.dump(C,stream,ensure_ascii=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    os.chmod(tmp,0o600); os.replace(tmp,CONFIG)
class H(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def out(self,data,code=200):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def auth(self):
        h=self.headers.get('Authorization','')
        return h.startswith('Bearer ') and hmac.compare_digest(h[7:].strip(),KEY)
    def do_GET(self):
        if self.path=='/healthz':
            self.out({'ok':True}); return
        if not self.auth():
            self.out({'ok':False,'message':'Unauthorized'},401); return
        if self.path=='/wpp-api/v1/status':
            self.out({'ok':True,'api_version':1,'version':C['version'],'domain':DOMAIN,
                      'location':location(),'name':DOMAIN.split('.')[0],
                      'capabilities':['node-agent','site-template']}); return
        if self.path=='/wpp-api/v1/profiles':
            self.out({'ok':True,'profiles':[]}); return
        self.out({'ok':False,'message':'Not found'},404)
    def do_POST(self):
        if not self.auth():
            self.out({'ok':False,'message':'Unauthorized'},401); return
        if self.path=='/wpp-api/v1/site-template':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>12000000:
                    self.out({'ok':False,'message':'Размер шаблона превышает лимит 12 МБ.'},413); return
                data=json.loads(self.rfile.read(length).decode('utf-8'))
                template_id=str(data.get('template_id',''))
                if template_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',template_id):
                    self.out({'ok':False,'message':'Некорректный ID шаблона.'},400); return
                page=data.get('html','')
                if not isinstance(page,str) or len(page.encode('utf-8'))>2100000:
                    self.out({'ok':False,'message':'HTML шаблона слишком большой или некорректный.'},413); return
                assets=data.get('assets',[])
                if not isinstance(assets,list) or len(assets)>20:
                    self.out({'ok':False,'message':'Некорректный список ресурсов.'},400); return
                written=[]
                total=0
                for item in assets:
                    if not isinstance(item,dict): continue
                    name=str(item.get('name',''))
                    encoded=str(item.get('data',''))
                    if not ASSET_RE.fullmatch(name): continue
                    try: raw=base64.b64decode(encoded,validate=True)
                    except (binascii.Error,ValueError): continue
                    if len(raw)>2000000 or total+len(raw)>6500000:
                        self.out({'ok':False,'message':'Ресурсы шаблона превышают лимит 6.5 МБ.'},413); return
                    atomic_write(os.path.join(SITE,name),raw)
                    total+=len(raw); written.append(name)
                for name in os.listdir(SITE):
                    if name.startswith('preset-') and ASSET_RE.fullmatch(name) and name not in written:
                        try: os.unlink(os.path.join(SITE,name))
                        except OSError: pass
                if page:
                    atomic_write(os.path.join(SITE,'index.html'),page.encode('utf-8'))
                    C['site_template_id']=template_id
                else:
                    atomic_write(os.path.join(SITE,'index.html'),DEFAULT_HTML.encode('utf-8'))
                    C.pop('site_template_id',None)
                save_config()
                self.out({'ok':True,'template_id':template_id,'assets':len(written)})
            except (ValueError,TypeError,UnicodeError,OSError,json.JSONDecodeError):
                self.out({'ok':False,'message':'Не удалось сохранить шаблон сайта на ноде.'},400)
            return
        if self.path.endswith('/federation/purge'):
            self.out({'ok':True,'deleted':0}); return
        if self.path.endswith('/federation/delete'):
            self.out({'ok':True,'deleted':False}); return
        if self.path.endswith('/federation/sync'):
            self.out({'ok':False,'message':'VPN services are not installed in Node Agent Lab.'},501); return
        self.out({'ok':False,'message':'Not found'},404)
os.makedirs(SITE,mode=0o755,exist_ok=True)
if not os.path.exists(os.path.join(SITE,'index.html')):
    atomic_write(os.path.join(SITE,'index.html'),DEFAULT_HTML.encode('utf-8'))
ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()
PY_AGENT
chmod 0755 /opt/wpp-node-agent/agent.py
cat > /etc/systemd/system/wpp-node-agent.service <<'UNIT'
[Unit]
Description=WPO lightweight Node Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
Group=root
UMask=0077
ExecStart=/usr/bin/python3 /opt/wpp-node-agent/agent.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/log /var/www/wpp-node-site /etc/wpp-node-agent
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    tls $EMAIL
    encode zstd gzip
    handle /wpp-api/* {
        reverse_proxy 127.0.0.1:9088
    }
    handle /healthz {
        reverse_proxy 127.0.0.1:9088
    }
    handle {
        root * /var/www/wpp-node-site
        try_files {path} /index.html
        file_server
    }
}
CADDY
chmod 0644 /etc/caddy/Caddyfile
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then
  ufw allow 80/tcp >/dev/null || true
  ufw allow 443/tcp >/dev/null || true
fi
systemctl daemon-reload
# A reinstall rotates the API key. --now alone leaves an already running agent
# with the OLD key in memory; restart ensures the current config is loaded.
systemctl enable wpp-node-agent.service
systemctl restart wpp-node-agent.service
systemctl is-active --quiet wpp-node-agent.service || { echo 'Не удалось перезапустить Node Agent.'; exit 4; }
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy
report installing 'Ожидание HTTPS-сертификата.'
TLS_OK=0
for i in $(seq 1 60); do
  if curl -fsS --connect-timeout 3 --max-time 5 "https://$DOMAIN/healthz" >/dev/null 2>&1; then TLS_OK=1; break; fi
  sleep 5
done
[[ "$TLS_OK" == "1" ]] || { report error 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; echo 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; exit 4; }
# Check the AUTHENTICATED agent status, not just public /healthz.
# This catches a stale agent key before controller registration.
if ! curl -4fsS --connect-timeout 4 --max-time 12 \
    -H "Authorization: Bearer $API_KEY" \
    "https://$DOMAIN/wpp-api/v1/status" >/dev/null; then
  report error 'Node Agent не принимает новый ключ API. Проверьте перезапуск службы.'
  echo 'Node Agent не принимает новый ключ API (проверьте systemctl status wpp-node-agent.service).'
  exit 4
fi
# Test-only VPN capability is installed before enrollment. Registration
# is blocked on failure: controller must never see a "ready" VPN node without
# working local Xray and authenticated federation API.
report installing 'Активация VPN ноды: VLESS XHTTP и Hysteria2.'
VPN_SETUP="$(mktemp /tmp/wpo-node-vpn-enable.XXXXXXXX.sh)"
trap fail ERR
trap 'rm -f -- "$VPN_SETUP"' EXIT
curl -4fsSL --proto '=https' --proto-redir '=https' \
    --retry 3 --connect-timeout 15 --max-time 90 \
    'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/test/wpo-smooth-progress-v1/wpo-node-vpn-enable.sh' \
    -o "$VPN_SETUP"
bash -n "$VPN_SETUP"
WPO_NODE_VPN_REF='test/wpo-smooth-progress-v1' bash "$VPN_SETUP"
rm -f -- "$VPN_SETUP"
trap fail ERR
report registration 'VPN и HTTPS готовы. Регистрация в основной панели.'
if ENROLL_RESULT="$(python3 - "$ENROLL_URL" "$TOKEN" "$DOMAIN" "$API_KEY" <<'PY_ENROLL'
import json,sys,urllib.request,urllib.error
url,token,domain,key=sys.argv[1:]
body=json.dumps({'token':token,'url':'https://'+domain,'api_key':key,'name':domain.split('.')[0]}).encode()
request=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST')
try:
    with urllib.request.urlopen(request,timeout=20) as response:
        result=json.loads(response.read(32768))
except urllib.error.HTTPError as exc:
    raw=exc.read(8192)
    try:
        details=json.loads(raw.decode('utf-8','replace'))
        message=str(details.get('message') or 'Неизвестная ошибка')
    except (ValueError,AttributeError):
        message='Панель отклонила регистрацию'
    raise SystemExit('Регистрация: HTTP %d — %s' % (exc.code,message[:180]))
except (urllib.error.URLError,TimeoutError,OSError) as exc:
    raise SystemExit('Связь с панелью при регистрации недоступна: '+str(exc.reason if hasattr(exc,'reason') else exc)[:140])
except (ValueError,TypeError,UnicodeError):
    raise SystemExit('Панель вернула некорректный ответ при регистрации.')
if not isinstance(result,dict) or not result.get('ok'):
    raise SystemExit(str(result.get('message','Registration failed')) if isinstance(result,dict) else 'Registration failed')
print('Нода зарегистрирована:',result.get('node_id',''))
PY_ENROLL
)"; then
  printf '%s\n' "$ENROLL_RESULT"
else
  echo "$ENROLL_RESULT" >&2
  report error "$(printf '%s' "$ENROLL_RESULT" | head -c 160)"
  echo 'Ошибка регистрации. Если ключ установки истёк, удалите незавершённую установку в панели и создайте новый ключ.'
  exit 5
fi
trap - ERR
echo "Готово: Node Agent зарегистрирован на https://$DOMAIN"
