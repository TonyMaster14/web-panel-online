"""Opt-in real binary test. WPO_RUNTIME_DIR contains xray, caddy, haproxy.
Runs on loopback high ports; does not install services or access a public target.
"""
import copy
import hashlib
import ssl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import wpo_reality as reality
import wpo_xray_live as live
import wpp_routing as routing

runtime=Path(os.environ['WPO_RUNTIME_DIR'])
xray=str(runtime/'xray');caddy=str(runtime/'caddy');haproxy=str(runtime/'haproxy-source/haproxy')
root=Path(tempfile.mkdtemp(prefix='reality-integration-',dir=runtime));processes=[]
def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=30)
def start(*args):
    out=open(root/(str(len(processes))+'.log'),'w')
    proc=subprocess.Popen(args,stdout=out,stderr=out,env=dict(os.environ,XDG_CONFIG_HOME=str(root/'caddy-config'),XDG_DATA_HOME=str(root/'caddy-data')))
    processes.append((proc,out));return proc
try:
    reality.ROOT=root;reality.PRIVATE=root/'private.key';reality.PUBLIC=root/'profile.json'
    fields=dict(line.split(':',1) for line in run(xray,'x25519').stdout.splitlines() if ':' in line)
    reality.PRIVATE.write_text(fields['PrivateKey'].strip())
    profile=dict(reality.DEFAULT,address='127.0.0.1',sni='target.example.com',short_id='0123456789abcdef',public_key=fields['Password (PublicKey)'].strip())
    reality.PUBLIC.write_text(json.dumps(profile))
    run('openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'key.pem'),'-out',str(root/'cert.pem'),'-days','1','-subj','/CN=target.example.com','-addext','subjectAltName=DNS:target.example.com,DNS:node.example.com')
    start('openssl','s_server','-accept','19445','-key',str(root/'key.pem'),'-cert',str(root/'cert.pem'),'-www','-tls1_3','-alpn','h2,http/1.1')
    secret=str(uuid.uuid4())
    inbound=reality.inbound([{'id':secret,'email':'one@example.test','flow':'xtls-rprx-vision'}],profile)
    inbound['streamSettings']['realitySettings']['target']='127.0.0.1:19445'
    # Local target allowance is ONLY for this isolated integration fixture.
    server={'api':{'tag':'api','listen':'127.0.0.1:19449','services':['HandlerService']},
            'log':{'loglevel':'warning'},'inbounds':[inbound],
            'outbounds':[{'protocol':'freedom','settings':{'finalRules':[{'action':'allow','network':'tcp,udp'}]}}]}
    server['inbounds'].append({'tag':'xhttp','listen':'127.0.0.1','port':19450,'protocol':'vless',
        'settings':{'decryption':'none','clients':[{'id':secret,'email':'xhttp@test'}]},
        'streamSettings':{'network':'xhttp','xhttpSettings':{'path':'/wpo-test'}}})
    config=root/'server.json';config.write_text(json.dumps(server));run(xray,'run','-test','-config',str(config))
    server_proc=start(xray,'run','-config',str(config))
    website='{\n admin off\n auto_https disable_redirects\n servers {\n protocols h1 h2 h3\n max_header_size 2MB\n }\n}\nhttps://node.example.com {\n tls '+str(root/'cert.pem')+' '+str(root/'key.pem')+'\n handle /wpo-test/* {\n reverse_proxy h2c://127.0.0.1:19450\n }\n handle {\n respond "WPO website OK"\n }\n}\n'
    (root/'Caddyfile').write_text(reality.caddy_internal(website));run(caddy,'validate','--config',str(root/'Caddyfile'),'--adapter','caddyfile');start(caddy,'run','--config',str(root/'Caddyfile'),'--adapter','caddyfile')
    front=reality.haproxy_config(profile['sni']).replace('    user haproxy\n','').replace('    group haproxy\n','').replace('0.0.0.0:443','127.0.0.1:19446').replace('    bind [::]:443 v6only\n','')
    (root/'haproxy.cfg').write_text(front);run(haproxy,'-c','-f',str(root/'haproxy.cfg'));start(haproxy,'-db','-f',str(root/'haproxy.cfg'))
    # Add a second identity through the actual HandlerService, without restarting.
    time.sleep(.6)
    secret2=str(uuid.uuid4());candidate=copy.deepcopy(server)
    candidate['inbounds'][0]['settings']['clients'].append({'id':secret2,'email':'two@example.test','flow':'xtls-rprx-vision'})
    real_run=subprocess.run
    def commands(args,**kwargs):
        if args[0]=='systemctl':return subprocess.CompletedProcess(args,0)
        return real_run(args,**kwargs)
    with patch.object(live.subprocess,'run',side_effect=commands):
        assert live.try_apply(candidate,config,xray,'test','127.0.0.1:19449')
    assert server_proc.poll() is None
    outbound=routing._vless_outbound(reality.link(secret2,'live',profile));outbound['settings']['vnext'][0]['port']=19446
    client={'log':{'loglevel':'warning'},'inbounds':[{'listen':'127.0.0.1','port':19447,'protocol':'socks','settings':{'auth':'noauth'}}],'outbounds':[outbound]}
    (root/'client.json').write_text(json.dumps(client));run(xray,'run','-test','-config',str(root/'client.json'));start(xray,'run','-config',str(root/'client.json'))
    (root/'probe.txt').write_text('WPO REALITY authenticated tunnel OK')
    start(sys.executable,'-m','http.server','19448','--bind','127.0.0.1','--directory',str(root));time.sleep(.5)
    web=run('curl','--noproxy','*','-kfsS','--max-time','10','--resolve','node.example.com:19446:127.0.0.1','https://node.example.com:19446/').stdout
    tunnel=run('curl','--noproxy','','-fsS','--max-time','20','--socks5-hostname','127.0.0.1:19447','http://127.0.0.1:19448/probe.txt').stdout
    xhttp={'tag':'xhttp','protocol':'vless','settings':{'vnext':[{'address':'127.0.0.1','port':19446,
        'users':[{'id':secret,'encryption':'none'}]}]},'streamSettings':{'network':'xhttp','security':'tls',
        'tlsSettings':{'serverName':'node.example.com','pinnedPeerCertSha256':hashlib.sha256(ssl.PEM_cert_to_DER_cert((root/'cert.pem').read_text())).hexdigest()},'xhttpSettings':{'path':'/wpo-test','mode':'auto'}}}
    xclient=copy.deepcopy(client);xclient['inbounds'][0]['port']=19451;xclient['outbounds']=[xhttp]
    (root/'xclient.json').write_text(json.dumps(xclient));start(xray,'run','-config',str(root/'xclient.json'));time.sleep(.4)
    xtunnel=run('curl','--noproxy','','-fsS','--max-time','20','--socks5-hostname','127.0.0.1:19451','http://127.0.0.1:19448/probe.txt').stdout
    assert xtunnel==tunnel,xtunnel
    assert web=='WPO website OK',web
    assert tunnel=='WPO REALITY authenticated tunnel OK',tunnel
    print('PASS: Firefox REALITY Vision traffic + XHTTP + HTTPS through one SNI listener; live user addition without restart')
except Exception:
    print('Integration logs:',root)
    for p in root.glob('*.log'):print(p.name,p.read_text()[-1800:])
    raise
finally:
    for proc,out in processes:proc.terminate()
    for proc,out in processes:
        try:proc.wait(timeout=3)
        except subprocess.TimeoutExpired:proc.kill()
        out.close()
