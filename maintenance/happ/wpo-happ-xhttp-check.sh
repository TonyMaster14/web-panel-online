#!/usr/bin/env bash
# Read-only WPO Happ/XHTTP checks. Outputs no keys, subscription URLs or domain names.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Нужен sudo на основном VPS WPO.' >&2; exit 1; }
python3 - <<'PY'
import json
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys

APP='/opt/tproxy-panel'
sys.path.insert(0,APP)
def read_json(path):
    try:
        obj=json.loads(Path(path).read_text(encoding='utf-8'))
        return obj if isinstance(obj,dict) else {}
    except (OSError,ValueError): return {}
def verdict(label,good):
    print(label+': '+('OK' if good else 'НЕ СОВПАДАЕТ'))
def validate(cmd):
    try:
        proc=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
        return proc.returncode==0
    except (OSError,subprocess.TimeoutExpired): return False

print('=== Дополнительная диагностика Happ / XHTTP, без изменений ===')
accounts=read_json('/etc/web-proxy-panel/users.json')
subs=accounts.get('subscriptions',[])
allusers=accounts.get('users',[])
subs=[s for s in subs if isinstance(s,dict)]
if not subs:
    print('Подписки: не найдены');raise SystemExit(2)
sub=max(subs,key=lambda s:int(s.get('created_at',0) or 0))
members=[u for u in allusers if isinstance(u,dict)
         and u.get('subscription_id')==sub.get('id') and u.get('enabled',True)]
print('Активных профилей последней подписки: '+str(len(members)))
print('Протоколы: '+', '.join(sorted(set(str(u.get('protocol','?')) for u in members))))
if not members:
    print('После импорта Happ должен сначала создать профиль пользователя.')
    raise SystemExit(0)
try:
    import wpp_connections as connections
    import wpp_cdn as cdn
except Exception:
    print('Модули подключений WPO: не загружаются')
    raise SystemExit(3)
conn=connections.load('/etc/web-proxy-panel/connections.json')
runtime=read_json('/etc/web-panel-proxy-xray/config.json')
try: caddy=Path('/etc/caddy/Caddyfile').read_text(encoding='utf-8')
except OSError: caddy=''
try: root=Path('/etc/web-proxy-panel/xray-path').read_text(encoding='utf-8').strip()
except OSError: root=''
for i,user in enumerate(members[:8],1):
    proto=user.get('protocol')
    print('— Профиль №'+str(i)+': '+str(proto))
    if proto not in ('vless','hysteria'):
        continue
    connection=connections.get(conn,str(user.get('connection_id','')))
    verdict('  Шаблон подключения найден',bool(connection))
    if not connection: continue
    tag=connections.inbound_tag(connection)
    inbounds=[x for x in runtime.get('inbounds',[]) if isinstance(x,dict) and x.get('tag')==tag]
    verdict('  Нужный Xray inbound присутствует',bool(inbounds))
    if not inbounds: continue
    inbound=inbounds[0]
    if proto=='vless':
        try:
            expected=connections.client_path(connection,root)
            actual=inbound.get('streamSettings',{}).get('xhttpSettings',{}).get('path')
            verdict('  XHTTP: путь клиента = путь Xray',bool(actual and
                    (expected==actual or expected.startswith(actual.rstrip('/')+'/'))))
        except Exception:
            print('  XHTTP: не удалось вычислить путь клиента')
            continue
        bucket=connections._xray_bucket(connection)
        route_name='web_panel_vless_'+str(bucket)
        pattern=r'(?m)^\s*@'+re.escape(route_name)+r'\s+path\s+([^\n]+)'
        found=re.search(pattern,caddy)
        routes=found.group(1).split() if found else []
        verdict('  Caddy: путь XHTTP маршрутизируется',bool(found and any(
            expected==r or (r.endswith('/*') and expected.startswith(r[:-1]))
            for r in routes)))
        section=re.search(r'handle\s+@'+re.escape(route_name)+r'\s*\{([\s\S]*?)\n\s*\}',caddy)
        port=int(inbound.get('port',0) or 0)
        verdict('  Caddy: маршрут ведёт на порт Xray',bool(section and
                re.search(r'reverse_proxy\s+127\.0\.0\.1:'+str(port)+r'\b',section.group(1))))
    else:
        print('  Hysteria2: проверка TLS и UDP требуется отдельно')
verdict('Проверка синтаксиса Caddyfile',validate(
    ['caddy','validate','--config','/etc/caddy/Caddyfile','--adapter','caddyfile']))
binary='/opt/web-panel-proxy/xray/xray'
if Path(binary).is_file():
    verdict('Проверка текущего конфига Xray',validate(
        [binary,'run','-test','-config','/etc/web-panel-proxy-xray/config.json']))
else:
    print('Проверка Xray: исполняемый файл не найден по стандартному пути')
service=Path('/etc/systemd/system/tproxy-panel.service')
domain=''
try:
    for line in service.read_text(encoding='utf-8').splitlines():
        if line.startswith('Environment=WEBPROXY_DOMAIN='):
            domain=line.split('=',2)[-1].strip().strip('"')
            break
except OSError: pass
if domain:
    try:
        context=ssl.create_default_context()
        with socket.create_connection(('127.0.0.1',443),timeout=6) as raw:
            with context.wrap_socket(raw,server_hostname=domain) as conn:
                verdict('Локальный TLS/SNI на Caddy',bool(conn.version()))
    except (OSError,ssl.SSLError,ValueError):
        verdict('Локальный TLS/SNI на Caddy',False)
else: print('Локальный TLS/SNI: домен не обнаружен в настройке службы')
print('=== Проверка завершена; ничего не изменено ===')
PY
