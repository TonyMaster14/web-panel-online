"""Real Xray integration: set XRAY_TEST_BIN to run isolated XHTTP failover."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import wpp_routing

BIN=os.environ.get('XRAY_TEST_BIN')

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]

@unittest.skipUnless(BIN,'set XRAY_TEST_BIN to run real Xray')
class LiveFailover(unittest.TestCase):
    def test_xhttp_failure_and_recovery(self):
        self.exercise(False)

    def test_xhttp_to_hysteria_failure_and_recovery(self):
        self.exercise(True)

    def exercise(self, hysteria):
        with tempfile.TemporaryDirectory(prefix='wpo-failover-') as tmp:
            root=Path(tmp); processes=[]; logs=[]; targets=[]
            def target(label,delay):
                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        time.sleep(delay)
                        body=label.encode()
                        self.send_response(204 if self.path=='/probe' else 200)
                        self.send_header('Content-Length','0' if self.path=='/probe' else str(len(body)))
                        self.end_headers()
                        if self.path!='/probe':self.wfile.write(body)
                    def log_message(self,*args):pass
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                threading.Thread(target=server.serve_forever,daemon=True).start()
                targets.append(server)
                return server.server_port
            def start(name,config):
                path=root/(name+'.json');path.write_text(json.dumps(config))
                log=open(root/(name+'.log'),'a');logs.append(log)
                process=subprocess.Popen([BIN,'run','-config',str(path)],stdout=log,stderr=log)
                processes.append(process)
                return process
            uuid='11111111-1111-4111-8111-111111111111'
            ports=[port(),port()];configs=[]
            for i in range(2):
                dest=target('A' if i==0 else 'B', .01 if i==0 else .25)
                configs.append({'log':{'loglevel':'debug'},'inbounds':[{
                    'listen':'127.0.0.1','port':ports[i],'protocol':'vless',
                    'settings':{'clients':[{'id':uuid}],'decryption':'none'},
                    'streamSettings':{'network':'xhttp','security':'none',
                        'xhttpSettings':{'path':'/test','mode':'auto'}}}],
                    'outbounds':[{'protocol':'freedom','settings':{'redirect':f'127.0.0.1:{dest}',
                        'finalRules':[{'action':'allow','ip':['127.0.0.1/32']}]}}]})
            if hysteria:
                cert=root/'cert.pem';key=root/'key.pem'
                subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
                    '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost',
                    '-addext','subjectAltName=DNS:localhost'],check=True,capture_output=True)
                configs[1]['inbounds'][0].update({
                    'protocol':'hysteria',
                    'settings':{'version':2,'clients':[{'auth':uuid}]},
                    'streamSettings':{'network':'hysteria','security':'tls',
                        'tlsSettings':{'alpn':['h3'],'certificates':[{
                            'certificateFile':str(cert),'keyFile':str(key)}]},
                        'hysteriaSettings':{'version':2}}})
            try:
                a=start('a',configs[0]);b=start('b',configs[1])
                links=[f'vless://{uuid}@127.0.0.1:{p}?security=none&type=xhttp&mode=packet-up&path=%2Ftest' for p in ports]
                if hysteria:links[1]=f'hysteria2://{uuid}@127.0.0.1:{ports[1]}/?sni=localhost'
                config=wpp_routing.failover_xray_config(links)
                if hysteria:
                    # Only the isolated fixture uses a self-signed certificate.
                    config['outbounds'][1]['streamSettings']['tlsSettings']['certificates']=[{
                        'certificateFile':str(cert),'usage':'verify'}]
                config['log']['loglevel']='debug'
                # Test backends explicitly allow loopback destinations (Xray 26 defaults
                # to rejecting private IPs). Production node policy is unchanged.
                # Redirected only by test servers; no external requests.
                config['observatory']['probeUrl']='http://127.0.0.1:9/probe'
                config['inbounds'][0]['port']=port()
                http_port=port();config['inbounds'][1]['port']=http_port
                client=start('client',config)
                def request():
                    response=subprocess.run(['curl','-sS','--max-time','3','--noproxy','',
                        '--proxy',f'http://127.0.0.1:{http_port}',
                        'http://127.0.0.1:9/who'],capture_output=True,text=True)
                    return response.stdout.strip() if response.returncode==0 else ''
                def wait_for(expected,seconds=35):
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        if client.poll() is not None:break
                        if request()==expected:return
                        time.sleep(.5)
                    evidence='\n'.join(p.name+'\n'+p.read_text()[:9000] for p in root.glob('*.log'))
                    self.fail('No route '+expected+'\n'+evidence)
                wait_for('A');print('PASS: primary A selected',flush=True)
                a.terminate();a.wait(timeout=5)
                wait_for('B');print('PASS: primary stopped -> B',flush=True)
                a=start('a-recovered',configs[0])
                wait_for('A');print('PASS: A recovered -> A',flush=True)
                a.terminate();a.wait(timeout=5);b.terminate();b.wait(timeout=5)
                self.assertEqual(request(),'')
                print('PASS: both down -> no direct fallback',flush=True)
            finally:
                for p in processes:
                    if p.poll() is None:p.terminate()
                for p in processes:
                    try:p.wait(timeout=5)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
                for server in targets:server.shutdown();server.server_close()
                for log in logs:log.close()
