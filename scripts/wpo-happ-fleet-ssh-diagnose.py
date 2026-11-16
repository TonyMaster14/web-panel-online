#!/usr/bin/env python3
"""READ ONLY: Main WPO controller → registered nodes over SSH.

The operator types SSH passwords into their own terminal. No private keys,
passwords, UUIDs or subscription links are displayed in the report.
"""
import base64
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

APP=Path('/opt/tproxy-panel')
NODES=Path('/var/lib/tproxy-panel/nodes.json')
XRAY=Path('/opt/web-panel-proxy/xray/xray')
CHECK_URL='https://www.gstatic.com/generate_204'

REMOTE=r"""
import base64,json,re,sys,subprocess
from pathlib import Path
def read(path):
 try:return json.loads(Path(path).read_text())
 except (OSError,ValueError,TypeError):return {}
def up(service):
 try:
  return subprocess.run(['systemctl','is-active','--quiet',service],
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=4).returncode==0
 except (OSError,subprocess.TimeoutExpired):return False
try:
 ids=json.loads(base64.b64decode(sys.argv[1],validate=True))
 ids=list(dict.fromkeys(x for x in ids if isinstance(x,str) and re.fullmatch('[0-9a-f]{64}',x)))[:150]
 cfg=read('/etc/wpp-node-vpn/xray.json')
 state=read('/etc/wpp-node-vpn/profiles.json').get('profiles',{})
 settings=read('/etc/wpp-node-vpn/settings.json')
 profile=read('/etc/web-proxy-panel/reality/profile.json')
 sni=profile.get('sni','')
 matches=[x for x in cfg.get('inbounds',[]) if x.get('streamSettings',{}).get('security')=='reality' and sni in x.get('streamSettings',{}).get('realitySettings',{}).get('serverNames',[])]
 current=matches[0] if len(matches)==1 else {}
 settings_reality=current.get('streamSettings',{}).get('realitySettings',{})
 clients=current.get('settings',{}).get('clients',[])
 active={c.get('id') for c in clients if c.get('flow')=='xtls-rprx-vision' and isinstance(c.get('id'),str)}
 registered=configured=0
 sample=None
 for ext in ids:
  item=state.get(ext,{}) if isinstance(state,dict) else {}
  secret=item.get('secrets',{}).get('reality') if isinstance(item,dict) else None
  if isinstance(secret,str):
   registered+=1
   if secret in active:
    configured+=1
    if sample is None:sample=secret
 if sample is None and active:sample=sorted(active)[0]
 router_path=Path('/etc/web-proxy-panel/reality/haproxy.cfg')
 router=router_path.read_text() if router_path.is_file() else ''
 route_pat=r'(?im)^\s*use_backend\s+([a-zA-Z0-9_-]+)\s+if\s+\{\s*req\.ssl_sni\s+-i\s+'+re.escape(str(sni))+r'\s*\}'
 route=re.search(route_pat,router)
 matches_router=False
 if route:
  name=route.group(1)
  backend=re.search(r'(?ims)^backend\s+'+re.escape(name)+r'\s*\n(.*?)(?=^backend\s+|\Z)',router)
  if backend:
   port=re.search(r'127\.0\.0\.1:(\d+)',backend.group(1))
   matches_router=bool(port and int(port.group(1))==current.get('port'))
 print(json.dumps({
  'ok':True,'domain':settings.get('domain',''),'sni':sni,'fp':profile.get('fingerprint',''),
  'services':{s:up(s) for s in ('wpo-node-xray.service','wpo-node-vpn.service','wpo-tls-router.service')},
  'expected':len(ids),'registered':registered,'in_xray':configured,'xray_clients':len(active),
  'router_matches':matches_router,
  'short_id_matches':profile.get('short_id') in settings_reality.get('shortIds',[]),
  'target_matches':settings_reality.get('target',settings_reality.get('dest'))==str(sni)+':443',
  # Used only by a temporary Xray client on the controller; never printed.
  'client_secret':sample,'public_key':profile.get('public_key',''),
  'short_id':profile.get('short_id','')
 },separators=(',',':')))
except Exception as exc:
 print(json.dumps({'ok':False,'kind':type(exc).__name__}))
"""

def jobs():
 sys.path.insert(0,str(APP))
 import wpp_nodes
 from wpo_happ_preparer import tasks
 nodes=wpp_nodes.load_nodes(NODES)
 expected={str(n.get('id')):[] for n in nodes}
 try:
  for _digest,node,ext,_label,protocols in tasks():
   if 'reality' in protocols:
    expected.setdefault(str(node.get('id')),[]).append(ext)
  return nodes,expected,None
 except (OSError,ValueError,subprocess.SubprocessError,ImportError,KeyError) as exc:
  return nodes,expected,type(exc).__name__

def hostname(node):
 parsed=urlsplit(str(node.get('url','')))
 host=parsed.hostname
 if (parsed.scheme!='https' or not host or parsed.username or parsed.password
     or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]',host)):
  raise ValueError('Invalid WPO node hostname')
 return host

def ssh_check(host,ids):
 source=base64.b64encode(REMOTE.encode()).decode()
 payload=base64.b64encode(json.dumps(ids[:150]).encode()).decode()
 program='import base64;exec(base64.b64decode('+repr(source)+'))'
 cmd='python3 -c '+shlex.quote(program)+' '+shlex.quote(payload)
 argv=['ssh','-T','-o','ConnectTimeout=10','-o','ConnectionAttempts=1',
       '-o','StrictHostKeyChecking=ask','-o','NumberOfPasswordPrompts=2',
       '-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2',
       'root@'+host,cmd]
 print('  Подключаюсь по SSH (пароль вводится только в терминале)...',flush=True)
 try:
  result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=None,text=True,timeout=65)
 except (OSError,subprocess.TimeoutExpired):
  return {'ok':False,'kind':'SSH timeout'}
 if result.returncode:
  return {'ok':False,'kind':'SSH authentication or connection failed'}
 try:return json.loads(result.stdout.strip().splitlines()[-1])
 except (ValueError,IndexError):
  return {'ok':False,'kind':'Invalid remote response'}

def tcp(host):
 start=time.monotonic()
 try:
  with socket.create_connection((host,443),timeout=4):pass
  return str(round((time.monotonic()-start)*1000))+'мс'
 except OSError:return 'FAIL'

def unused_port():
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0))
  return sock.getsockname()[1]

def actual_reality(host,p):
 if not XRAY.is_file() or not p.get('client_secret'):
  return 'нет Xray/зарегистрированного UUID'
 uuid=p.get('client_secret')
 if not isinstance(uuid,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',uuid):
  return 'нет корректного UUID'
 if not all(isinstance(p.get(k),str) for k in ('sni','fp','public_key','short_id')):
  return 'неполные параметры REALITY'
 port=unused_port()
 config={'log':{'loglevel':'error'},
  'inbounds':[{'listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth'}}],
  'outbounds':[{'protocol':'vless',
    'settings':{'vnext':[{'address':host,'port':443,
      'users':[{'id':uuid,'encryption':'none','flow':'xtls-rprx-vision'}]}]},
    'streamSettings':{'network':'tcp','security':'reality','realitySettings':{
       'serverName':p['sni'],'fingerprint':p['fp'],
       'publicKey':p['public_key'],'shortId':p['short_id']}}}]}
 with tempfile.TemporaryDirectory(prefix='wpo-ssh-diag-') as td:
  file=Path(td)/'client.json'
  file.write_text(json.dumps(config))
  file.chmod(0o600)
  process=None
  try:
   process=subprocess.Popen([str(XRAY),'run','-config',str(file)],
           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   time.sleep(.5)
   if process.poll() is not None:return 'Xray client failed'
   results=[]
   for _ in range(2):
    try:
     run=subprocess.run(['curl','-4','--noproxy','','-sS',
       '--socks5-hostname','127.0.0.1:'+str(port),
       '--connect-timeout','4','--max-time','9',
       '-o','/dev/null','-w','%{http_code} %{time_total}',CHECK_URL],
       stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=12)
     code,_,seconds=run.stdout.strip().partition(' ')
     results.append(str(round(float(seconds)*1000))+'мс'
                    if run.returncode==0 and code=='204' else 'FAIL')
    except (OSError,subprocess.TimeoutExpired,ValueError):
     results.append('FAIL')
   return '/'.join(results)
  finally:
   if process is not None:
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=2)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)

def main():
 if os.geteuid()!=0 or not NODES.is_file() or not (APP/'wpp_nodes.py').is_file():
  print('Запустите команду на основной панели WPO с sudo.',file=sys.stderr)
  return 2
 print('WPO / Happ · SSH-диагностика ВСЕХ нод (только чтение)',flush=True)
 print('Пароли, UUID, ключи и ссылки подписок НЕ выводятся.',flush=True)
 try:nodes,expected,warning=jobs()
 except (OSError,ValueError,ImportError) as exc:
  print('Не удалось прочитать реестр: '+type(exc).__name__,file=sys.stderr)
  return 2
 if warning:print('! Не удалось сверить подписки: '+warning,flush=True)
 for node in nodes:
  label=str(node.get('name') or node.get('country_name') or 'Нода')[:55]
  print('\n━━ '+label+' ━━',flush=True)
  if not node.get('enabled',True):
   print('  Выключена в WPO; пропускаю.',flush=True)
   continue
  try:host=hostname(node)
  except ValueError:
   print('  Некорректный адрес ноды в реестре.',flush=True)
   continue
  print('  Домен: '+host,flush=True)
  print('  TCP443 из основной панели: '+('/'.join(tcp(host) for _ in range(2))),flush=True)
  data=ssh_check(host,expected.get(str(node.get('id')),[]))
  if not data.get('ok'):
   print('  SSH: '+str(data.get('kind','ошибка'))[:60],flush=True)
   continue
  if str(data.get('domain','')).lower().rstrip('.')!=host:
   print('  ! ДОМЕН НОДЫ ОТЛИЧАЕТСЯ ОТ АДРЕСА В ПАНЕЛИ',flush=True)
  print('  Службы: '+', '.join(s.replace('.service','')+'='+('OK' if v else 'FAIL')
                                for s,v in data.get('services',{}).items()),flush=True)
  print('  REALITY: SNI='+str(data.get('sni','?'))[:80]+'; fp='+str(data.get('fp','?'))[:20],flush=True)
  print('  HAProxy→Xray='+('OK' if data.get('router_matches') else 'FAIL')
        +'; shortId='+('OK' if data.get('short_id_matches') else 'FAIL')
        +'; target='+('OK' if data.get('target_matches') else 'FAIL'),flush=True)
  if not warning:
   print('  REALITY подписок: ожидается '+str(data.get('expected',0))
        +'; на ноде '+str(data.get('registered',0))
        +'; в Xray '+str(data.get('in_xray',0)),flush=True)
  print('  Клиентов REALITY в Xray: '+str(data.get('xray_clients',0)),flush=True)
  print('  REALITY→HTTPS204 из основной панели: '+actual_reality(host,data),flush=True)
 print('\nЗавершено: ничего не изменено. Это не проверка из сети самого Happ.',flush=True)
 return 0

if __name__=='__main__':
 try:sys.exit(main())
 except KeyboardInterrupt:
  print('\nПроверка остановлена.',file=sys.stderr)
  sys.exit(130)
