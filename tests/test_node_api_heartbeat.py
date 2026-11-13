"""Test the actual WPO Node Agent 0.2 HTTPS API handler on a local test server.
Validates status auth and that VPN federation is *not* silently reported as ready.
No external VPS, DNS, Caddy, TLS certificate, installer or Internet is touched.
"""
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen,Request
from urllib.error import HTTPError
import json
import re
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
script=(ROOT/"wpo-node-agent-install-v2.sh").read_text(encoding="utf-8")
start="cat > /opt/wpp-node-agent/agent.py <<'PY_AGENT'\n"
assert script.count(start)==1
agent=script.split(start,1)[1].split("\nPY_AGENT",1)[0]
assert "ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()" in agent
assert "CONFIG='/etc/wpp-node-agent/config.json'" in agent
assert "SITE='/var/www/wpp-node-site'" in agent
installer=(ROOT/"node-install.sh").read_text(encoding="utf-8")
assert '"GET",node_api.API_PREFIX+"/status",timeout=3' in installer
assert 'node["status"]="online"' in installer
assert 'node["status"]="offline"' in installer
assert "setInterval(refresh,1000)" in installer, "Node cards must update every second"
assert "status_checked_at" in installer, "Node API checks must be cached"

class NodeAgent(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="wpo-agent-test-")
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        cfg=root/"config.json"
        cfg.write_text(json.dumps({"api_key":"TestNodeKey_123456789","domain":"node.example.test","version":"0.2.0"}),encoding="utf-8")
        site=root/"site"
        modified=agent.replace("CONFIG='/etc/wpp-node-agent/config.json'",f"CONFIG={str(cfg)!r}")
        modified=modified.replace("SITE='/var/www/wpp-node-site'",f"SITE={str(site)!r}")
        modified=modified.replace("ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()","")
        ns={}
        exec(compile(modified,"node-agent-test.py","exec"),ns)
        # Geolocation is outside the API authentication contract; keep tests offline.
        ns["location"]=lambda:{"country_code":"NL","country_name":"Нидерланды"}
        self.server=ThreadingHTTPServer(("127.0.0.1",0),ns["H"])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self,path,key=None,method="GET",body=None):
        headers={}
        if key is not None:headers["Authorization"]="Bearer "+key
        if body is not None:headers["Content-Type"]="application/json"
        req=Request(self.base+path,method=method,data=(json.dumps(body).encode() if body is not None else None),headers=headers)
        try: r=urlopen(req,timeout=4)
        except HTTPError as e:r=e
        with r:return r.status,json.loads(r.read())

    def test_healthz_is_public_but_status_requires_token(self):
        self.assertEqual(self.request("/healthz")[0],200)
        self.assertEqual(self.request("/wpp-api/v1/status")[0],401)
        self.assertEqual(self.request("/wpp-api/v1/status","wrong-key")[0],401)

    def test_authenticated_status_returns_online_metadata(self):
        code,data=self.request("/wpp-api/v1/status","TestNodeKey_123456789")
        self.assertEqual(code,200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["domain"],"node.example.test")
        self.assertIn("node-agent",data["capabilities"])
        self.assertIn("site-template",data["capabilities"])
        self.assertEqual(data["location"]["country_code"],"NL")

    def test_agent_truthfully_reports_no_vpn_federation(self):
        code,data=self.request("/wpp-api/v1/federation/sync","TestNodeKey_123456789",method="POST",body={"external_id":"abc"})
        self.assertEqual(code,501)
        self.assertFalse(data["ok"])

if __name__=="__main__":unittest.main()
