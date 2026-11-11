#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP_DIR=/opt/tproxy-panel
DATA_DIR=/var/lib/tproxy-panel
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите установщик от root.'; exit 1; }
for file in panel.py wpp_ui.py wpp-node-agent-install.sh; do
  [[ -s "$APP_DIR/$file" ]] || { echo "Не найден $APP_DIR/$file. Сначала установите базовый Nodes Lab."; exit 1; }
done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба $SERVICE."; exit 1; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$DATA_DIR/nodes-lab-ui-v2-backup-$STAMP"
install -d -m 0700 "$BACKUP"
for file in panel.py wpp_ui.py wpp-node-agent-install.sh; do cp -a "$APP_DIR/$file" "$BACKUP/$file"; done
echo "Резервная копия: $BACKUP"

rollback() {
  echo 'Ошибка. Восстанавливаю файлы из резервной копии.'
  for file in panel.py wpp_ui.py wpp-node-agent-install.sh; do
    [[ -s "$BACKUP/$file" ]] && cp -a "$BACKUP/$file" "$APP_DIR/$file"
  done
  systemctl restart "$SERVICE" >/dev/null 2>&1 || true
}
trap rollback ERR

python3 - "$APP_DIR" <<'PY_PATCH'
import os, re, sys
from pathlib import Path

app=Path(sys.argv[1])
ui_path=app/'wpp_ui.py'
panel_path=app/'panel.py'
ui=ui_path.read_text(encoding='utf-8')
panel=panel_path.read_text(encoding='utf-8')

def once(source, old, new, label):
    count=source.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: найдено {count} вхождений, ожидалось ровно одно. Ничего не изменено.')
    return source.replace(old,new,1)

# Larger, nearly square node tiles in a two-column layout (three rows for six nodes).
ui=once(ui,
".wpo-node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,340px));gap:9px;align-items:start}",
".wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(270px,390px));gap:16px;align-items:stretch;justify-content:start}",
"node grid")
ui=once(ui,
".wpo-node-card{margin:0;padding:11px;width:100%;max-width:340px;box-sizing:border-box;border:1px solid",
".wpo-node-card{margin:0;padding:20px;width:100%;max-width:390px;min-height:225px;aspect-ratio:1.32;box-sizing:border-box;display:flex;flex-direction:column;justify-content:space-between;border:1px solid",
"node card")
ui=once(ui,".wpo-node-flag{display:grid;place-items:center;flex:0 0 34px;height:34px;",".wpo-node-flag{display:grid;place-items:center;flex:0 0 50px;height:50px;","node flag")
ui=once(ui,".wpo-node-card-title strong{font-size:11px;",".wpo-node-card-title strong{font-size:16px;","node title")
ui=once(ui,".wpo-node-card-title small{font-size:9px;",".wpo-node-card-title small{font-size:11px;","node subtitle")
ui=once(ui,
".wpo-node-status{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;padding:4px 7px;border:1px solid var(--line);border-radius:20px;font-size:8px;",
".wpo-node-status{display:inline-flex;align-items:center;gap:7px;flex:0 0 auto;padding:7px 10px;border:1px solid var(--line);border-radius:20px;font-size:11px;",
"node status")
ui=once(ui,
".wpo-node-card-meta{display:flex;justify-content:space-between;gap:8px;margin-top:8px;padding-top:7px;border-top:1px solid var(--line);font-size:8px;",
".wpo-node-card-meta{display:flex;justify-content:space-between;gap:10px;margin-top:16px;padding-top:12px;border-top:1px solid var(--line);font-size:11px;",
"node metadata")
ui=once(ui,
".wpo-node-card-actions{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:5px}",
".wpo-node-card-actions{display:flex;justify-content:flex-end;align-items:center;gap:9px;margin-top:16px}",
"node actions")
ui=once(ui,
".wpo-pending-node{border-style:dashed}",
".wpo-pending-node{border-style:dashed}.wpo-node-domain{display:inline-flex;align-items:center;max-width:100%;margin-top:8px;padding:8px 11px;border:1px solid color-mix(in srgb,var(--accent) 24%,var(--line));border-radius:9px;background:color-mix(in srgb,var(--accent) 7%,var(--surface));font:600 12px ui-monospace,monospace;color:var(--text);text-decoration:none;overflow-wrap:anywhere}.wpo-node-domain:hover{border-color:var(--accent);color:var(--accent)}.wpo-node-grid .icon-btn,.wpo-node-dialog button{transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease,background .16s ease}.wpo-node-grid .icon-btn:hover,.wpo-node-dialog button:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:0 7px 22px color-mix(in srgb,var(--accent) 24%,transparent)}.wpo-node-grid .icon-btn:active,.wpo-node-dialog button:active{transform:translateY(0) scale(.96)}.wpo-node-dialog .primary:hover,.wpo-nodes-page .wpo-add-node:hover{box-shadow:0 8px 24px color-mix(in srgb,var(--accent) 34%,transparent)}.wpo-node-dialog-body select{width:100%;min-height:42px;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--input);color:var(--text);font:inherit}",
"node interactions")

ui=once(ui,
"def nodes_ui(nodes, local, connection_token, path, csrf, pending_nodes=None):",
"def nodes_ui(nodes, local, connection_token, path, csrf, pending_nodes=None, templates=None):",
"nodes UI signature")
ui=once(ui,
"    pending_nodes=pending_nodes if isinstance(pending_nodes,list) else []\n    labels=",
"""    pending_nodes=pending_nodes if isinstance(pending_nodes,list) else []
    templates=templates if isinstance(templates,list) else []
    template_names={}
    template_options=['<option value="">Без шаблона сайта</option>']
    for item in templates:
        if not isinstance(item,dict): continue
        tid=str(item.get('id','')).strip()
        title=str(item.get('name','')).strip()
        if not tid or not title or tid in template_names: continue
        template_names[tid]=title
        template_options.append(f'<option value="{esc(tid)}">{esc(title)}</option>')
    template_options=''.join(template_options)
    labels=""",
"node templates setup")
ui=once(ui,
"        code=str(n.get('country_code','UN')).upper()\n        caps=",
"""        code=str(n.get('country_code','UN')).upper()
        endpoint=str(n.get('url','')).strip()
        domain=urlsplit(endpoint).hostname or endpoint
        template_id=str(n.get('site_template_id',''))
        template_label=template_names.get(template_id,'Без шаблона сайта')
        caps=""",
"node domain and selected template")
ui=once(ui,
"data-node-name=\"{esc(name)}\" title=\"Переименовать\"",
"data-node-name=\"{esc(name)}\" data-node-template=\"{esc(template_id)}\" title=\"Изменить ноду\"",
"node edit template attribute")
ui=once(ui,
"<small>{esc(n.get(\"country_name\",\"Страна не определена\"))} · {esc(n.get(\"url\",\"\"))}</small>",
"<small>{esc(n.get(\"country_name\",\"Страна не определена\"))}</small><a class=\"wpo-node-domain\" href=\"https://{esc(domain)}\" target=\"_blank\" rel=\"noopener noreferrer\">https://{esc(domain)}</a>",
"node visible domain")
ui=once(ui,
"<span>{esc(cap)}</span></div><div class=\"wpo-node-card-actions\">{edit}{delete}</div>",
"<span>{esc(cap)} · {esc(template_label)}</span></div><div class=\"wpo-node-card-actions\">{edit}{delete}</div>",
"node template label")
ui=once(ui,
"<div class=\"wpo-node-card-meta\"><span>Установщик</span><span>{esc(p.get(\"detail\",\"Ожидает установки\"))}</span></div></article>')",
"<div class=\"wpo-node-card-meta\"><span>Установщик</span><span>{esc(p.get(\"detail\",\"Ожидает установки\"))}</span></div><div class=\"wpo-node-card-actions\"><form method=\"post\" action=\"{esc(path)}/node-action\" data-confirm=\"Убрать незавершённую установку из списка?\">{hidden(csrf,operation=\"delete-pending\",id=uid)}<button class=\"icon-btn danger\" type=\"submit\" title=\"Удалить запись установки\" aria-label=\"Удалить запись установки\">{icon(\"trash\")}</button></form></div></article>')",
"pending card delete")
ui=once(ui,
"<label>Название<input name=\"name\" maxlength=\"80\" required></label><div class=\"actions\">",
"<label>Название ноды<input name=\"name\" maxlength=\"80\" required></label><label>Шаблон сайта<select name=\"template_id\">{template_options}</select></label><div class=\"actions\">",
"node edit template select")
ui=once(ui,
"f.elements.name.value=b.dataset.nodeName||'';document.getElementById('wpoRenameError').hidden=true;",
"f.elements.name.value=b.dataset.nodeName||'';f.elements.template_id.value=b.dataset.nodeTemplate||'';document.getElementById('wpoRenameError').hidden=true;",
"node edit initializes template")
ui=once(ui,
"if(!el){location.reload();return;}",
"if(!el){if(document.querySelector('dialog:modal'))return;location.reload();return;}",
"keep node wizard open")

# Pass the installed site's real preset library into the node editor.
panel=once(panel,
"node_api.load_location(LOCATION_FILE),\"\",PANEL_PATH,self.csrf(),pending_rows)",
"node_api.load_location(LOCATION_FILE),\"\",PANEL_PATH,self.csrf(),pending_rows,all_presets())",
"pass site presets into node UI")

old="""                elif operation=="rename":
                    nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")
                    selected=next((n for n in nodes if n.get("id")==uid),None)
                    if selected is None: raise node_api.NodeError("Нода не найдена.")
                    selected["name"]=node_api.clean_text(form.get("name",""),"Название ноды",80)
                    node_api.save_nodes(NODES_FILE,nodes)
                    if self.headers.get("X-WPP-Async","")=="1": self.send_json({"ok":True}); return
                elif operation=="delete":"""
new="""                elif operation=="rename":
                    nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")
                    selected=next((n for n in nodes if n.get("id")==uid),None)
                    if selected is None: raise node_api.NodeError("Нода не найдена.")
                    selected["name"]=node_api.clean_text(form.get("name",""),"Название ноды",80)
                    next_template=str(form.get("template_id","")).strip()
                    current_template=str(selected.get("site_template_id",""))
                    if next_template != current_template:
                        if "site-template" not in selected.get("capabilities",[]):
                            raise node_api.NodeError("Эта нода не поддерживает шаблоны сайтов. Удалите её и подключите заново через новый установщик Node Agent.")
                        if next_template:
                            preset=next((x for x in all_presets() if isinstance(x,dict) and str(x.get("id",""))==next_template),None)
                            if not preset: raise node_api.NodeError("Выбранный шаблон не найден в библиотеке.")
                            page=str(preset.get("html",""))
                            if not page: raise node_api.NodeError("У выбранного шаблона отсутствует HTML.")
                            assets=[]
                            names=list(dict.fromkeys(re.findall(r'/(preset-[A-Za-z0-9_.-]+\.(?:webp|png|jpe?g|svg|woff2?))',page,re.I)))
                            total=0
                            for asset_name in names:
                                asset_path=os.path.join("/srv/tproxy-site",asset_name)
                                if not os.path.isfile(asset_path): continue
                                asset_size=os.path.getsize(asset_path)
                                if asset_size>900000 or total+asset_size>1800000: continue
                                with open(asset_path,"rb") as stream: encoded=base64.b64encode(stream.read()).decode("ascii")
                                assets.append({"name":asset_name,"data":encoded}); total+=asset_size
                            payload={"template_id":next_template,"html":page,"assets":assets}
                        else:
                            payload={"template_id":"","html":"","assets":[]}
                        node_api.request(selected,"POST",node_api.API_PREFIX+"/site-template",payload,timeout=30)
                        selected["site_template_id"]=next_template
                    node_api.save_nodes(NODES_FILE,nodes)
                    if self.headers.get("X-WPP-Async","")=="1": self.send_json({"ok":True}); return
                elif operation=="delete-pending":
                    uid=str(form.get("id",""))
                    if not re.fullmatch(r"p-[a-f0-9]{12}",uid): raise node_api.NodeError("Некорректная запись установки.")
                    pending=wpo_pending_load()
                    digest=next((key for key in pending if key.startswith(uid[2:])),None)
                    if not digest: raise node_api.NodeError("Запись установки уже удалена.")
                    pending.pop(digest,None); wpo_pending_save(pending)
                    if self.headers.get("X-WPP-Async","")=="1": self.send_json({"ok":True}); return
                elif operation=="delete":"""
panel=once(panel,old,new,"node actions for template and pending delete")

compile(ui,str(ui_path),"exec")
compile(panel,str(panel_path),"exec")
for path,source in ((ui_path,ui),(panel_path,panel)):
    tmp=path.with_suffix(path.suffix+'.nodesv2tmp')
    tmp.write_text(source,encoding='utf-8')
    tmp.chmod(path.stat().st_mode & 0o777)
    os.replace(tmp,path)
print("UI and controller patches applied; Python syntax checks passed.")
PY_PATCH

cat > "$APP_DIR/wpp-node-agent-install.sh" <<'NODE_AGENT'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
TOKEN="$1"
[[ "$TOKEN" =~ ^[A-Za-z0-9_-]{40,60}$ ]] || { echo 'Одноразовый ключ не передан.'; exit 2; }
ENROLL_URL="__WPO_CONTROLLER_ENROLL_URL__"
STATUS_URL="__WPO_CONTROLLER_STATUS_URL__"
DOMAIN=""
EMAIL=""
API_KEY=""
report() {
  python3 - "$TOKEN" "$1" "$2" "$DOMAIN" <<'PY_STATUS' | curl -fsS --max-time 8 -H 'Content-Type: application/json' --data-binary @- "$STATUS_URL" >/dev/null 2>&1 || true
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
DOMAIN="$(printf '%s' "$DOMAIN" | sed -E 's#^https?://##;s#/.*$##' | tr '[:upper:]' '[:lower:]')"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || { report error 'Некорректный домен.'; echo 'Некорректный домен.'; exit 2; }
read -r -p "Email для Let's Encrypt: " EMAIL
[[ "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || { report error 'Некорректный email.'; echo 'Некорректный email.'; exit 2; }
. /etc/os-release
case "$ID" in
  ubuntu) dpkg --compare-versions "$VERSION_ID" ge 22.04 || { echo 'Требуется Ubuntu 22.04+.'; exit 2; } ;;
  debian) dpkg --compare-versions "$VERSION_ID" ge 12 || { echo 'Требуется Debian 12+.'; exit 2; } ;;
  *) echo 'Поддерживаются Ubuntu 22.04+ и Debian 12+.'; exit 2 ;;
esac
report installing 'Установка Caddy и подготовка сайта.'
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
import base64,binascii,hmac,json,os,re,tempfile,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
C=json.load(open('/etc/wpp-node-agent/config.json',encoding='utf-8'))
KEY=C['api_key']; DOMAIN=C['domain']; SITE='/var/www/wpp-node-site'
DEFAULT_HTML='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Node Agent online</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 80% 10%,#24304b,#0c111b 52%);color:#eef3ff;font:15px system-ui,sans-serif}.box{width:min(520px,calc(100% - 36px));padding:36px;border:1px solid #ffffff1c;border-radius:24px;background:#111a2bcc;box-shadow:0 25px 80px #0007}.dot{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:50%;background:#36d399;box-shadow:0 0 18px #36d399}h1{margin:18px 0 8px;font-size:30px}p{margin:0;color:#aab7ce;line-height:1.65}.tag{color:#8fa4c6;font-size:11px;letter-spacing:.14em;text-transform:uppercase}</style></head><body><main class="box"><span class="dot"></span><span class="tag">Node Agent online</span><h1>Сервер работает</h1><p>Подключение ноды активно. Владелец панели может назначить этой ноде шаблон сайта.</p></main></body></html>'''
ASSET_RE=re.compile(r'^preset-[A-Za-z0-9_.-]{1,100}\.(?:webp|png|jpe?g|svg|woff2?)$',re.I)
def loc():
    try:
        with urllib.request.urlopen('https://ipapi.co/json/',timeout=4) as r: d=json.loads(r.read(65536))
        code=str(d.get('country_code','UN')).upper()
        if not re.fullmatch(r'[A-Z]{2}',code): code='UN'
        name=str(d.get('country_name') or 'Сервер')[:80]
        return {'country_code':code,'country_name':name,'name':name}
    except Exception: return {'country_code':'UN','country_name':'Сервер','name':'Сервер'}
def atomic(path,data):
    fd,tmp=tempfile.mkstemp(prefix='.wpo-',dir=os.path.dirname(path))
    try:
        with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp,0o644); os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def out(self,d,code=200):
        b=json.dumps(d,ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def auth(self):
        h=self.headers.get('Authorization','')
        return h.startswith('Bearer ') and hmac.compare_digest(h[7:].strip(),KEY)
    def do_GET(self):
        if self.path=='/healthz': self.out({'ok':True}); return
        if not self.auth(): self.out({'ok':False,'message':'Unauthorized'},401); return
        if self.path=='/wpp-api/v1/status':
            self.out({'ok':True,'api_version':1,'version':C['version'],'domain':DOMAIN,'location':loc(),'name':DOMAIN.split('.')[0],'capabilities':['node-agent','site-template']}); return
        if self.path=='/wpp-api/v1/profiles': self.out({'ok':True,'profiles':[]}); return
        self.out({'ok':False,'message':'Not found'},404)
    def do_POST(self):
        if not self.auth(): self.out({'ok':False,'message':'Unauthorized'},401); return
        if self.path=='/wpp-api/v1/site-template':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<1 or size>3*1024*1024: self.out({'ok':False,'message':'Некорректный размер запроса.'},413); return
                d=json.loads(self.rfile.read(size).decode('utf-8'))
                page=d.get('html','')
                if not isinstance(page,str) or len(page.encode('utf-8'))>2*1024*1024: self.out({'ok':False,'message':'HTML шаблона превышает 2 МБ.'},413); return
                assets=d.get('assets',[])
                if not isinstance(assets,list) or len(assets)>20: self.out({'ok':False,'message':'Некорректный список ресурсов.'},400); return
                names=[]; total=0
                for item in assets:
                    if not isinstance(item,dict): continue
                    name=str(item.get('name','')); encoded=str(item.get('data',''))
                    if not ASSET_RE.fullmatch(name): continue
                    try: raw=base64.b64decode(encoded,validate=True)
                    except (ValueError,binascii.Error): continue
                    if len(raw)>900000 or total+len(raw)>1800000: self.out({'ok':False,'message':'Ресурсы шаблона превышают лимит.'},413); return
                    atomic(os.path.join(SITE,name),raw); names.append(name); total+=len(raw)
                for name in os.listdir(SITE):
                    if name.startswith('preset-') and ASSET_RE.fullmatch(name) and name not in names:
                        try: os.unlink(os.path.join(SITE,name))
                        except OSError: pass
                if page: atomic(os.path.join(SITE,'index.html'),page.encode('utf-8'))
                else: atomic(os.path.join(SITE,'index.html'),DEFAULT_HTML.encode('utf-8'))
                self.out({'ok':True,'assets':len(names)}); return
            except (ValueError,TypeError,UnicodeError,OSError,json.JSONDecodeError):
                self.out({'ok':False,'message':'Не удалось сохранить шаблон сайта.'},400); return
        if self.path.endswith('/federation/purge'): self.out({'ok':True,'deleted':0}); return
        if self.path.endswith('/federation/delete'): self.out({'ok':True,'deleted':False}); return
        if self.path.endswith('/federation/sync'): self.out({'ok':False,'message':'VPN services are not installed in Node Agent Lab.'},501); return
        self.out({'ok':False,'message':'Not found'},404)
os.makedirs(SITE,mode=0o755,exist_ok=True)
if not os.path.exists(os.path.join(SITE,'index.html')): atomic(os.path.join(SITE,'index.html'),DEFAULT_HTML.encode('utf-8'))
ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()
PY_AGENT
chmod 0755 /opt/wpp-node-agent/agent.py
python3 -m py_compile /opt/wpp-node-agent/agent.py
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
ReadWritePaths=/var/log /var/www/wpp-node-site
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
systemctl enable --now wpp-node-agent.service
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy
report installing 'Ожидание HTTPS-сертификата.'
TLS_OK=0
for i in $(seq 1 60); do
  if curl -fsS --connect-timeout 3 --max-time 5 "https://$DOMAIN/healthz" >/dev/null 2>&1; then TLS_OK=1; break; fi
  sleep 5
done
[[ "$TLS_OK" == 1 ]] || { report error 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; echo 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; exit 4; }
report registration 'HTTPS готов. Регистрация в основной панели.'
python3 - "$ENROLL_URL" "$TOKEN" "$DOMAIN" "$API_KEY" <<'PY_ENROLL'
import json,sys,urllib.request
url,token,domain,key=sys.argv[1:]
body=json.dumps({'token':token,'url':'https://'+domain,'api_key':key,'name':domain.split('.')[0]}).encode()
req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(req,timeout=20) as response: result=json.loads(response.read(32768))
if not result.get('ok'): raise SystemExit(result.get('message','Registration failed'))
print('Нода зарегистрирована:',result.get('node_id',''))
PY_ENROLL
trap - ERR
echo "Готово: Node Agent зарегистрирован на https://$DOMAIN"
NODE_AGENT

chown root:root "$APP_DIR/panel.py" "$APP_DIR/wpp_ui.py" "$APP_DIR/wpp-node-agent-install.sh"
chmod 0644 "$APP_DIR/panel.py" "$APP_DIR/wpp_ui.py"
chmod 0700 "$APP_DIR/wpp-node-agent-install.sh"
bash -n "$APP_DIR/wpp-node-agent-install.sh"
python3 -m py_compile "$APP_DIR/panel.py" "$APP_DIR/wpp_ui.py"
systemctl restart "$SERVICE"
systemctl is-active --quiet "$SERVICE"
trap - ERR

echo
echo 'WPO Nodes Lab UI v2 установлен.'
echo 'Карточки: 2 столбца, увеличенный квадратный формат (до 3 рядов при 6 нодах).'
echo 'Добавлены: домен, выбор шаблона, удаление временной установки, эффекты кнопок.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main не изменялся.'
