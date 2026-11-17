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
import base64,json,re,sys,subprocess,socket,ipaddress
from pathlib import Path
def read(path):
 try:return json.loads(Path(path).read_text())
 except (OSError,ValueError,TypeError):return {}
def up(service):
 try:
  return subprocess.run(['systemctl','is-active','--quiet',service],
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=4).returncode==0
 except (OSError,subprocess.TimeoutExpired):return False

# READ-ONLY Linux policy routes + effective kernel route decisions.
def ip_json(*args):
 try:
  p=subprocess.run(['ip','-j','-4',*args],stdout=subprocess.PIPE,
      stderr=subprocess.DEVNULL,text=True,timeout=5)
  if p.returncode:return None
  obj=json.loads(p.stdout)
  return obj if isinstance(obj,list) else None
 except (OSError,ValueError,subprocess.TimeoutExpired):return None
def route_fields(record):
 if not isinstance(record,dict):return {}
 return {k:record[k] for k in ('dst','dev','gateway','table','metric','protocol','type','src','prefsrc')
         if k in record and isinstance(record[k],(str,int))}
def selected_route(host):
 arr=ip_json('route','get',host)
 return route_fields(arr[0]) if arr else {}
def policy_fields(record):
 if not isinstance(record,dict):return {}
 return {k:record[k] for k in ('priority','table','src','dst','fwmark','iif','oif','action')
         if k in record and isinstance(record[k],(str,int))}
def routes_snapshot(config):
 entries=ip_json('route','show','table','all')
 rules=ip_json('rule','show')
 defaults=[route_fields(x) for x in (entries or []) if x.get('dst')=='default'
           and x.get('table','main') in ('main',254,'254')]
 extra_rules=[policy_fields(x) for x in (rules or [])
              if x.get('priority') not in (0,32766,32767)
              and x.get('table') not in ('local','main','default')]
 # A static route is not the automatically generated kernel connected subnet.
 static=[route_fields(x) for x in (entries or [])
         if x.get('protocol') not in ('kernel','local')
         and x.get('dst') not in ('default',None)
         and x.get('type','unicast') not in ('local','broadcast')
         and (x.get('gateway') or x.get('table','main') not in ('main',254,'254')
              or x.get('protocol')=='static')]
 lookups={host:selected_route(host) for host in ('1.1.1.1','8.8.8.8')}
 dev=lookups.get('1.1.1.1',{}).get('dev')
 rp_filter=None
 if isinstance(dev,str) and re.fullmatch('[A-Za-z0-9_.:-]{1,15}',dev):
  try:rp_filter=int((Path('/proc/sys/net/ipv4/conf')/dev/'rp_filter').read_text().strip())
  except (OSError,ValueError):pass
 outbounds=[x.get('protocol','') for x in config.get('outbounds',[])
            if isinstance(x,dict)]
 mapping=config.get('routing',{}) if isinstance(config.get('routing'),dict) else {}
 def direct():
  try:
   p=subprocess.run(['curl','-4','--noproxy','*','-sS','--connect-timeout','4',
                     '--max-time','7','-o','/dev/null','-w','%{http_code} %{time_total}',
                     'https://www.gstatic.com/generate_204'],
      stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=10)
   code,_,duration=p.stdout.strip().partition(' ')
   if p.returncode==0 and code=='204':
    return str(round(float(duration)*1000))+'ms'
  except (OSError,ValueError,subprocess.TimeoutExpired):pass
  return 'FAIL'
 return {'available':entries is not None and rules is not None,
         'default':defaults[:4],
         'static_count':len(static),'static':static[:8],
         'policy_count':len(extra_rules),'policy':extra_rules[:6],
         'get':lookups,'rp_filter':rp_filter,
         'xray_direct':'freedom' in outbounds,
         'xray_outbound_kinds':sorted(set(str(x) for x in outbounds))[:10],
         'xray_rules_count':len(mapping.get('rules',[])) if isinstance(mapping.get('rules'),list) else 0,
         'direct_https204':direct()}

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
  'short_id':profile.get('short_id',''),
  'static_routes':routes_snapshot(cfg)
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
 if (parsed.scheme!='https' or not host or '.' not in host or parsed.username or parsed.password
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



def wpo_static_routing_view():
 """WPO's client-side split routing, separate from Linux kernel IP routes."""
 try:
  sys.path.insert(0,str(APP))
  import wpp_routing
  content=wpp_routing.load('/var/lib/tproxy-panel/routing.json')
  profiles=content.get('profiles',{})
  if not isinstance(profiles,dict):raise ValueError('Incorrect routing format')
 except (OSError,ValueError,ImportError,TypeError):
  print('  Не удалось прочитать настройки маршрутизации WPO.',flush=True)
  return
 print('\n━━ СТАТИЧЕСКИЕ МАРШРУТЫ WPO · правила подписок Happ ━━',flush=True)
 print('Это клиентские правила DIRECT/PROXY, отдельно от Linux-маршрутов VPS.',flush=True)
 if not profiles:
  print('  Дополнительных правил для подключений WPO не задано.',flush=True)
  return
 count=0
 for cid,profile in sorted(profiles.items()):
  if not isinstance(profile,dict):continue
  if count>=16:
   print('  ...остальные профили не показаны.',flush=True)
   break
  safe_id=cid if re.fullmatch('[A-Za-z0-9_-]{3,64}',str(cid)) else 'скрыто'
  enabled=bool(profile.get('enabled',True))
  flags=[key for key in ('ru_direct','private_direct','captive_direct',
            'push_proxy','youtube_proxy','split_dns','block_bittorrent')
         if profile.get(key)]
  direct=profile.get('direct_domains',[])
  proxy=profile.get('proxy_domains',[])
  print('  '+str(safe_id)+': '+('включено' if enabled else 'выключено')+
        '; flags='+(','.join(flags) if flags else 'нет')+
        '; домены DIRECT='+str(len(direct) if isinstance(direct,list) else '?')+
        '; PROXY='+str(len(proxy) if isinstance(proxy,list) else '?'),flush=True)
  count+=1
 print('Домены и другие приватные данные в отчёт не выводятся.',flush=True)

def controller_route(host):
 """Kernel's chosen route from controller toward each registered node."""
 try:
  address=socket.getaddrinfo(host,443,family=socket.AF_INET,type=socket.SOCK_STREAM)[0][4][0]
  result=subprocess.run(['ip','-j','-4','route','get',address],capture_output=True,
                        text=True,timeout=5)
  rows=json.loads(result.stdout) if result.returncode==0 else []
  if isinstance(rows,list) and rows:return describe_route(rows[0])
 except (OSError,ValueError,TypeError,IndexError,subprocess.TimeoutExpired):
  pass
 return 'недоступно'

def describe_route(record):
 if not isinstance(record,dict) or not record:return 'нет маршрута'
 fields=[]
 for key in ('dev','gateway','table','metric','src','type'):
  if key in record and isinstance(record[key],(str,int)):
   fields.append(key+'='+str(record[key]))
 return ', '.join(fields) if fields else 'маршрут не определён'

def static_routes_view(data):
 """Render separate static routing section with Poland as a reference."""
 info=data.get('static_routes',{})
 if not isinstance(info,dict) or not info.get('available'):
  print('  СТАТИЧЕСКИЕ МАРШРУТЫ: iproute2 не ответил на запрос таблиц/правил.',flush=True)
  return None
 print('  ┌─ Статические маршруты и правила ─────────────────',flush=True)
 defaults=info.get('default',[])
 print('  │ Основной default: '+('; '.join(describe_route(x) for x in defaults[:2])
       if defaults else 'НЕ НАЙДЕН'),flush=True)
 for target in ('1.1.1.1','8.8.8.8'):
  got=info.get('get',{}).get(target,{})
  print('  │ Ядро → '+target+': '+describe_route(got),flush=True)
 counts=(info.get('static_count',0),info.get('policy_count',0))
 print('  │ Статических маршрутов: '+str(counts[0])+
       '; дополнительных policy rules: '+str(counts[1]),flush=True)
 for x in info.get('static',[])[:6]:
  print('  │   route: '+describe_route(x)+' dst='+str(x.get('dst','?'))[:65],flush=True)
 for x in info.get('policy',[])[:4]:
  print('  │   rule: '+', '.join(k+'='+str(v) for k,v in x.items())[:150],flush=True)
 rp=info.get('rp_filter')
 print('  │ rp_filter на исходящем интерфейсе: '+
       ({0:'выкл',1:'строгий',2:'свободный'}.get(rp,'неизвестно')),flush=True)
 print('  │ Xray direct/freedom: '+('OK' if info.get('xray_direct') else 'FAIL')+
       '; правил маршрутизации Xray: '+str(info.get('xray_rules_count','?')),flush=True)
 print('  │ Прямой HTTPS 204 с этой VPS: '+str(info.get('direct_https204','?'))[:25],flush=True)
 print('  └─────────────────────────────────────────────────',flush=True)
 return {'dev':info.get('get',{}).get('1.1.1.1',{}).get('dev',''),
         'table':info.get('get',{}).get('1.1.1.1',{}).get('table','main'),
         'policy':counts[1],'static':counts[0],
         'rp_filter':rp,'direct':info.get('xray_direct'),
         'https':info.get('direct_https204')}

def routing_comparison(items):
 if not items:return
 print('\n━━ СРАВНЕНИЕ С ПОЛЬШЕЙ · СТАТИЧЕСКИЕ МАРШРУТЫ ━━',flush=True)
 baseline=next((v for n,v in items if v.get('country_code')=='PL' or 'польш' in n.lower() or 'poland' in n.lower()),None)
 if baseline is None:
  print('Польская нода не распознана по названию; показываю сравнение без эталона.',flush=True)
 for name,route in items:
  issues=[]
  if route.get('policy',0):issues.append('policy rules='+str(route['policy']))
  if route.get('rp_filter')==1:issues.append('строгий rp_filter')
  if route.get('direct') is False:issues.append('нет outbound freedom')
  if str(route.get('https','')).upper().startswith('FAIL'):issues.append('прямой HTTPS не прошёл')
  if baseline is not None and route is not baseline:
   if route.get('policy')!=baseline.get('policy'):issues.append('число policy rules отличается от Польши')
   if route.get('static')!=baseline.get('static'):issues.append('число static routes отличается от Польши')
   if route.get('rp_filter')!=baseline.get('rp_filter'):issues.append('rp_filter отличается от Польши')
  print('• '+name+': '+('; '.join(dict.fromkeys(issues)) if issues else 'явных аномалий не выявлено'),flush=True)
 print('Разные gateway/интерфейсы VPS обычно нормальны. Этот отчёт не проверяет путь от телефона до ноды.',flush=True)

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
 wpo_static_routing_view()
 inspected=[]
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
  print('  Маршрут основной панели → нода: '+controller_route(host),flush=True)
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
  summary=static_routes_view(data)
  if summary:
   summary['country_code']=str(node.get('country_code','')).upper()
   inspected.append((label,summary))
 routing_comparison(inspected)
 print('\nЗавершено: ничего не изменено. Это не проверка из сети самого Happ.',flush=True)
 return 0

if __name__=='__main__':
 try:sys.exit(main())
 except KeyboardInterrupt:
  print('\nПроверка остановлена.',file=sys.stderr)
  sys.exit(130)
