"""Exercise the actual WPO public subscription handler over localhost HTTP.
No VPS, domain, VPN daemon, installed panel or external network is touched.
"""
import ast
import base64
import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import sys
import threading
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import quote, parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import wpp_routing as routing_store

source=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
panel=source.split("cat > \"$APP_FILE\" <<'PY'\n",1)[1].split("\nPY\n",1)[0]
tree=ast.parse(panel)
handler=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=="Handler")
methods=[node for node in handler.body if isinstance(node,ast.FunctionDef)
         and node.name in ("serve_subscription","send_data","send_html")]
assert len(methods)==3, [node.name for node in methods]
klass=ast.fix_missing_locations(ast.ClassDef(name="Handler", bases=[ast.Name(id="BaseHTTPRequestHandler",ctx=ast.Load())],
                                      keywords=[], body=methods, decorator_list=[]))
module=ast.fix_missing_locations(ast.Module(body=[klass],type_ignores=[]))

class HappSubscription(unittest.TestCase):
    def setUp(self):
        token="a"*64
        self.sub={"id":"s"*16,"enabled":True,"token":token,"name":"Global VPN",
                  "max_devices":0,"devices":[]}
        self.user={"id":"u"*16,"subscription_id":self.sub["id"],"device_id":"d"*16,
                   "connection_id":"vless-direct","enabled":True,
                   "protocol":"vless","backend_port":443,
                   "secret":"11111111-1111-4111-8111-111111111111","name":"iPhone"}
        self.manager={"ok":True,"name":"Global VPN","users":[self.user.copy()],"limited":False}
        def link(protocol,secret,port,name,username=""):
            frag=quote(name,safe="")
            if protocol=="vless":
                return ("vless://"+secret+"@vpn.example:443"
                        "?encryption=none&security=tls&sni=vpn.example&type=xhttp"
                        "&path=%2Fvless-test%2Fstream&mode=auto#"+frag)
            if protocol=="hysteria":
                return "hysteria2://"+secret+"@vpn.example:8443/?sni=vpn.example#"+frag
            raise AssertionError("unexpected protocol "+protocol)
        namespace=dict(
            BaseHTTPRequestHandler=BaseHTTPRequestHandler,
            json=json,base64=base64,re=re,secrets=secrets,sys=sys,
            parse_qs=parse_qs,urlparse=urlparse,
            SUB_PREFIX="/wpp-sub/",DOMAIN="vpn.example",LOGO="/not-found.svg",
            SUB_FETCH_SLOTS=threading.BoundedSemaphore(2),
            SUB_REQUESTS={},PANEL_PATH="/panel-test", ROUTING_FILE="/not-found-routing.json",
            NODES_FILE="/not-found-nodes.json",LOCATION_FILE="/not-found-location.json",
            node_api=SimpleNamespace(
                location_prefix=lambda location:"🇳🇱 Нидерланды",
                load_location=lambda path:{"country_code":"NL","country_name":"Нидерланды"},
                load_nodes=lambda path:[],
            ),
            routing_store=SimpleNamespace(
                load=lambda path:{"profiles":{}},
                RoutingError=routing_store.RoutingError,
                merge_profiles=routing_store.merge_profiles,
                subscription_xray_configs_by_link=routing_store.subscription_xray_configs_by_link,
                failover_xray_config=routing_store.failover_xray_config,
                hiddify_compatible_links=routing_store.hiddify_compatible_links
            ),
            users=lambda:copy.deepcopy([self.user]),
            subscription_registry=lambda:[self.sub],
            allow_subscription_request=lambda client:True,
            client_id=lambda handler:"127.0.0.1",
            ctl_subscription=lambda data:self.manager,
            subscription_device_name=lambda ua:"iPhone",
            proxy_link=link,
            proxy_connection_name=lambda user, fallback:fallback,
            federation_id=lambda a,b:"f"*64,
            traffic=lambda:{self.user["id"]:{"up":120,"down":340}}
        )
        helper=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=="happ_profile_title")
        exec(compile(ast.Module(body=[helper],type_ignores=[]),"title-helper.py","exec"),namespace)
        exec(compile(module,"subscription-http-test.py","exec"),namespace)
        cls=namespace["Handler"]
        cls.log_message=lambda *args: None
        # The HTTP test mounts only the public subscription route; do_GET in
        # production dispatches to this exact method after path parsing.
        cls.do_GET=lambda handler: handler.serve_subscription(handler.path.split("/wpp-sub/",1)[-1].split("?",1)[0])
        self.server=ThreadingHTTPServer(("127.0.0.1",0),cls)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self._close)
        self.root=f"http://127.0.0.1:{self.server.server_port}/wpp-sub/{token}"

    def _close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def fetch(self,suffix="",ua="Happ/4.0",accept="application/json"):
        req=Request(self.root+suffix,headers={"User-Agent":ua,"Accept":accept})
        try:
            response=urlopen(req,timeout=4)
        except HTTPError as error:
            response=error
        with response:
            return response.status,response.headers,response.read()

    def test_happ_receives_importable_xray_profiles_with_correct_title_and_node(self):
        status,h,body=self.fetch()
        self.assertEqual(status,200)
        self.assertIn("application/json",h["Content-Type"])
        self.assertEqual(h["profile-title"],"base64:"+base64.b64encode(b"Global VPN").decode())
        self.assertEqual(h["subscription-userinfo"],"upload=120; download=340; total=0; expire=0")
        result=json.loads(body)
        self.assertGreaterEqual(len(result),2)
        self.assertEqual(result[0]["remarks"],"🇪🇺 Автовыбор")
        self.assertEqual(result[1]["remarks"],"🇳🇱 Нидерланды")
        self.assertTrue(any(x["protocol"]=="vless" for x in result[1]["outbounds"]))

    def test_generic_client_receives_base64_vless_subscription(self):
        status,headers,body=self.fetch(ua="GenericVPN/1.0")
        self.assertEqual(status,200)
        decoded=base64.b64decode(body,validate=True).decode("utf-8")
        self.assertTrue(decoded.startswith("vless://"),decoded)
        self.assertIn("%F0%9F%87%B3%F0%9F%87%B1",decoded)

    def test_device_limit_is_reported_and_import_never_succeeds(self):
        self.manager={"ok":False,"code":"device_limit","message":"Лимит устройств","status":429}
        status,headers,body=self.fetch()
        self.assertEqual(status,429)
        self.assertEqual(headers.get("X-Hwid-Limit"),"true")
        self.assertIn("Лимит устройств",body.decode())

    def test_happ_empty_subscription_reports_no_vpn(self):
        self.manager={"ok":True,"name":"Global VPN","users":[],"limited":False}
        status,headers,body=self.fetch()
        self.assertEqual(status,409)
        self.assertIn("нет активных VLESS",body.decode())

if __name__=="__main__": unittest.main()
