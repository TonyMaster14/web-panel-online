#!/usr/bin/env python3
"""Read-only REALITY node diagnostics; isolated processes never alter services."""
import copy
import grp
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time

BINARY='/opt/web-panel-proxy/xray/xray'
SECRETS=[]


def safe(text):
    for value in SECRETS:
        if value:text=text.replace(str(value),'[redacted]')
    text=re.sub(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b','[UUID]',text)
    text=re.sub(r'\b[A-Za-z0-9_-]{43,}\b','[redacted]',text)
    return '\n'.join(line for line in text.splitlines()
                     if not any(word in line.lower() for word in ('authkey','privatekey','publickey','shortid','clienthello','sessionid')))


def run(args,timeout=15):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        return p.returncode,p.stdout+p.stderr
    except subprocess.TimeoutExpired:return 124,'TIMEOUT'
    except OSError as exc:return 127,type(exc).__name__


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def start(config,folder,name,processes,user=None):
    path=folder/(name+'.json');path.write_text(json.dumps(config));path.chmod(0o600)
    options={}
    if user:
        import pwd
        account=pwd.getpwnam(user)
        os.chown(folder,0,account.pw_gid);folder.chmod(0o750)
        os.chown(path,0,account.pw_gid);path.chmod(0o640)
        options=dict(user=account.pw_uid,group=account.pw_gid,extra_groups=[])
    log=(folder/(name+'.log')).open('w')
    try:
        proc=subprocess.Popen([BINARY,'run','-config',str(path)],stdout=log,stderr=log,**options)
    except Exception:
        log.close();raise
    processes.append((proc,log));time.sleep(.6)
    return proc


def probe(label,profile,client,destination,server=None,server_user=None):
    print('\nTEST:',label,flush=True)
    processes=[]
    with tempfile.TemporaryDirectory(prefix='wpo-diagnose-') as directory:
        folder=Path(directory)
        try:
            if server:
                server=copy.deepcopy(server);destination=port()
                server['inbounds'][0]['listen']='127.0.0.1'
                server['inbounds'][0]['port']=destination
                start(server,folder,'server',processes,server_user)
            socks=port()
            config={'log':{'loglevel':'debug'},'inbounds':[{'listen':'127.0.0.1','port':socks,
                'protocol':'socks','settings':{'auth':'noauth'}}],
                'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':'127.0.0.1',
                    'port':destination,'users':[{'id':client['id'],'encryption':'none','flow':'xtls-rprx-vision'}]}]},
                    'streamSettings':{'network':'tcp','security':'reality','realitySettings':{
                        'serverName':profile['sni'],'fingerprint':profile.get('fingerprint','firefox'),
                        'publicKey':profile['public_key'],'shortId':profile['short_id']}}}]}
            start(config,folder,'client',processes)
            code,output=run(['curl','--noproxy','','-sS','--socks5-hostname',f'127.0.0.1:{socks}',
                '--connect-timeout','4','--max-time','8','-o','/dev/null','-w',
                'HTTP=%{http_code} total=%{time_total}s\n','https://www.gstatic.com/generate_204'],11)
            print('curl exit:',code,safe(output),flush=True)
        finally:
            for proc,log in reversed(processes):
                if proc.poll() is None:proc.terminate()
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                log.close()
            for log in sorted(folder.glob('*.log')):
                text=safe(log.read_text(errors='replace'))
                lines=[line for line in text.splitlines() if not any(x in line for x in
                    ('dialing TCP','dialing to tcp','Logger started','creating stream worker','Reading config:'))]
                print(log.name+':\n'+'\n'.join(lines[-16:]),flush=True)


def main():
    print('WPO REALITY diagnostic v1 — no service/config changes',flush=True)
    root=Path('/etc/web-proxy-panel/reality')
    profile=json.loads((root/'profile.json').read_text())
    config=json.loads(Path('/etc/wpp-node-vpn/xray.json').read_text())
    inbound=next(x for x in config['inbounds'] if x.get('streamSettings',{}).get('security')=='reality')
    reality=inbound['streamSettings']['realitySettings'];clients=inbound['settings'].get('clients',[])
    SECRETS.extend([profile.get('public_key'),profile.get('short_id'),reality.get('privateKey')])
    SECRETS.extend(x.get('id') for x in clients)
    SECRETS.extend(x.get('email') for x in clients)
    print('Address:',profile.get('address'),'SNI:',profile.get('sni'),'users:',len(clients))
    for args in ([BINARY,'version'],['systemctl','show','wpo-node-xray','-p','User','-p','ExecMainStartTimestamp'],
                 ['systemctl','is-active','wpo-node-xray','wpo-tls-router','wpo-node-vpn','wpp-node-agent'],
                 ['ip','-6','route']):
        print(safe(run(args)[1]).strip(),flush=True)
    if not clients:raise RuntimeError('No REALITY clients')
    target=reality.get('target',reality.get('dest',''))
    host,target_port=target.rsplit(':',1)
    answers=socket.getaddrinfo(host.strip('[]'),int(target_port),type=socket.SOCK_STREAM)
    print('Target DNS:',sorted({a[4][0] for a in answers}),flush=True)
    for index,client in enumerate(clients[:2]):
        probe('active Xray / Firefox / user '+str(index+1),dict(profile,fingerprint='firefox'),client,19444)
    probe('active Xray / Edge',dict(profile,fingerprint='edge'),clients[0],19444)
    probe('active HAProxy / Firefox',dict(profile,fingerprint='firefox'),clients[0],443)
    isolated=copy.deepcopy(config);isolated.pop('api',None)
    isolated['inbounds']=[copy.deepcopy(inbound)];isolated['log']={'loglevel':'debug'}
    isolated['inbounds'][0]['streamSettings']['realitySettings']['show']=True
    _,user=run(['systemctl','show','wpo-node-xray','--property=User','--value'])
    user=user.strip() or 'root'
    probe('isolated server / original target / service user',profile,clients[0],0,isolated,user)
    ipv4=next((a[4][0] for a in answers if a[0]==socket.AF_INET),None)
    if ipv4:
        settings=isolated['inbounds'][0]['streamSettings']['realitySettings']
        settings.pop('dest',None);settings['target']=ipv4+':'+target_port
        probe('isolated server / IPv4 target / service user',profile,clients[0],0,isolated,user)
    print('\nDONE. Temporary clients and servers removed.',flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Diagnostic stopped:',type(exc).__name__,safe(str(exc)),flush=True)
        raise SystemExit(1)
