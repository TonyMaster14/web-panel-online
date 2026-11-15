#!/usr/bin/env bash
# WPO / Happ safe, read-only diagnostics. No keys, subscription tokens, or domains printed.
set -Eeuo pipefail
umask 077
[[ "${EUID}" -eq 0 ]] || { echo 'Запускайте через sudo на основном VPS WPO.' >&2; exit 1; }
echo '=== WPO / Happ: диагностика без изменения настроек ==='
python3 - <<'PY'
from pathlib import Path
import json
import subprocess
import sys

def read_json(path, fallback=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception: return fallback

def active(name):
    r=subprocess.run(['systemctl','is-active','--quiet',name],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return 'активна' if r.returncode==0 else 'НЕ АКТИВНА'

def socket_ports():
    results={}
    for mode,args in (('tcp',['ss','-H','-lnt']),('udp',['ss','-H','-lnu'])):
        try:
            result=subprocess.run(args,capture_output=True,text=True,timeout=5,check=False)
            lines=result.stdout.splitlines()
        except Exception: lines=[]
        for port in (443,8090,8443,10000,19000):
            results[(mode,port)] = any(
                line.split()[3].rsplit(':',1)[-1]==str(port)
                for line in lines if len(line.split())>=5)
    return results

for name in ['tproxy-panel.service','caddy.service','web-panel-proxy-xray.service']:
    print(f'Служба {name}: {active(name)}')
ports=socket_ports()
for mode,port in [('tcp',443),('tcp',8090),('tcp',10000),('udp',8443)]:
    print(f'Порт {mode.upper()}/{port}: {"слушает" if ports[mode,port] else "НЕ СЛУШАЕТ"}')

panel=Path('/opt/tproxy-panel/panel.py')
if not panel.is_file():
    print('Панель: файл не найден — это не основной VPS WPO.')
    raise SystemExit(2)
src=panel.read_text(encoding='utf-8')
print('Выдача Happ: '+('одиночный режим без авто' if
      'len(distinct_nodes)>1' in src else
      'старая схема или другой обработчик'))
print('Формат Happ: '+('Xray JSON для одного сервера' if
      '(happ and bool(xray_configs))' in src else
      'не подтверждён'))

data=read_json('/etc/web-proxy-panel/users.json',{})
if not isinstance(data,dict):
    print('Реестр пользователей: не удалось прочитать')
    data={}
subs=data.get('subscriptions',[]) if isinstance(data.get('subscriptions'),list) else []
users=data.get('users',[]) if isinstance(data.get('users'),list) else []
active_users=[u for u in users if isinstance(u,dict) and u.get('enabled',True)
              and u.get('protocol') in ('vless','hysteria')]
print(f'Подписки: {len(subs)}; активные VLESS/Hysteria профили: {len(active_users)}')
latest=sorted((s for s in subs if isinstance(s,dict)),
              key=lambda s:int(s.get('created_at',0) or 0),reverse=True)
if latest:
    sub=latest[0]
    sub_users=[u for u in active_users if u.get('subscription_id')==sub.get('id')]
    nodes=sub.get('node_ids')
    print('Последняя подписка: '+('включена' if sub.get('enabled',True) else 'ВЫКЛЮЧЕНА')+
          f'; профилей в реестре: {len(sub_users)}; выбранные ноды сохранены: '+
          (str(len(nodes)) if isinstance(nodes,list) else 'НЕТ'))
    print('Последняя подписка: автовыбор '+('включён' if sub.get('failover_enabled',True) else 'выключен'))
runtime=read_json('/etc/web-panel-proxy-xray/config.json',{})
if not isinstance(runtime,dict):
    print('Xray runtime: конфигурация не читается')
else:
    ids=set()
    for inbound in runtime.get('inbounds',[]):
        if not isinstance(inbound,dict): continue
        settings=inbound.get('settings',{})
        for client in settings.get('clients',[]) if isinstance(settings,dict) else []:
            if isinstance(client,dict):
                for field in ('id','auth'):
                    if client.get(field): ids.add(str(client[field]))
    not_found=[]
    for u in active_users:
        secrets=[u.get('secret')]
        if isinstance(u.get('device_secrets'),list): secrets+=u['device_secrets']
        if not any(str(value) in ids for value in secrets if value):
            not_found.append(u)
    print('Xray runtime: inbound='+str(len(runtime.get('inbounds',[])))+
          '; профилей без совпадения ключа в работающей конфигурации: '+str(len(not_found)))
    if latest:
        print('Последняя подписка: профилей без ключа в runtime: '+
              str(sum(1 for u in not_found if u.get('subscription_id')==latest[0].get('id'))))

try:
    sys.path.insert(0,'/opt/tproxy-panel')
    import wpp_nodes
    nodes=wpp_nodes.load_nodes('/var/lib/tproxy-panel/nodes.json')
except Exception:
    nodes=[]
    print('Ноды: не удалось прочитать реестр')
print('Дополнительных зарегистрированных нод: '+str(len(nodes)))
for i,node in enumerate(nodes[:12],1):
    if not isinstance(node,dict): continue
    try:
        status=wpp_nodes.request(node,'GET',wpp_nodes.API_PREFIX+'/status',timeout=5)
        caps=set(status.get('capabilities',[]) or [])
        verdict='API отвечает, VPN '+('готов' if {'federation','vless','hysteria'}.issubset(caps) else 'не все протоколы готовы')
    except Exception:
        verdict='API НЕДОСТУПНО'
    print(f'Дополнительная нода №{i}: {verdict}')
print('=== Конец. Скрипт ничего не менял и не выводил ключи. ===')
PY
