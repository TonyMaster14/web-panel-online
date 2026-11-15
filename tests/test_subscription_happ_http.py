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
import wpo_node_selection_v2 as exact_nodes

source=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
panel=source.split("cat > \"$APP_FILE\" <<'PY'\n",1)[1].split("\nPY\n",1)[0]
# Recreate the tested installed Nodes Lab controller without a real VPS.
panel=panel.replace('def traffic():','def selected_node_ids(form): return ["local"]\ndef traffic():',1)
panel=exact_nodes.patch_panel(panel)
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
        self.namespace=namespace
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
        self.assertEqual(h["profile-title"],"base64:"+base64.b64encode(b"Global VPN").decode())
        self.assertEqual(h["subscription-userinfo"],"upload=120; download=340; total=0; expire=0")
        # One VLESS node is a native Happ link: no extra JSON profile or balancer.
        decoded=base64.b64decode(body,validate=True).decode("utf-8").strip()
        self.assertTrue(decoded.startswith("vless://"),decoded)
        self.assertEqual(len(decoded.splitlines()),1)
        self.assertNotIn("Автовыбор",decoded)

    def test_two_protocols_on_one_node_never_generate_auto_balancer(self):
        second={**self.user,"id":"v"*16,"protocol":"hysteria",
                "connection_id":"hysteria-primary","backend_port":8443,
                "secret":"another-valid-hysteria-secret"}
        self.manager["users"]=[self.user.copy(),second]
        status,_,body=self.fetch()
        self.assertEqual(status,200)
        links=base64.b64decode(body,validate=True).decode("utf-8").strip().splitlines()
        self.assertEqual(len(links),2)
        self.assertTrue(links[0].startswith("vless://"))
        self.assertTrue(links[1].startswith("hysteria2://"))
        self.assertFalse(any("Автовыбор" in link for link in links))

    def remote_node(self):
        remote_link=("vless://11111111-1111-4111-8111-111111111111"
                     "@node2.example:443?encryption=none&security=tls"
                     "&sni=node2.example&type=xhttp"
                     "&path=%2Fvless-test%2Fstream&mode=auto#"
                     +quote("🇸🇪 Швеция",safe=""))
        self.namespace["node_api"].load_nodes=lambda path:[
            {"id":"a"*16,"enabled":True,"url":"https://node2.example"}
        ]
        self.namespace["node_api"].sync_profile=lambda *args,**kwargs:{
            "ok":True,"profiles":[{"protocol":"vless","link":remote_link}]
        }

    def test_multi_node_subscription_keeps_auto_balancer(self):
        self.sub["node_ids"]=["local","a"*16]
        self.remote_node()
        status,_,body=self.fetch()
        self.assertEqual(status,200)
        configs=json.loads(body)
        self.assertEqual(len(configs),3)
        self.assertEqual(configs[0]["remarks"],"🇪🇺 Автовыбор")
        self.assertEqual(configs[1]["remarks"],"🇳🇱 Нидерланды")
        self.assertEqual(configs[2]["remarks"],"🇸🇪 Швеция")
        self.assertTrue(configs[0]["routing"]["balancers"])

    def test_disabling_failover_keeps_only_node_profiles(self):
        self.sub["failover_enabled"]=False
        self.sub["node_ids"]=["local","a"*16]
        self.remote_node()
        status,_,body=self.fetch()
        self.assertEqual(status,200)
        links=base64.b64decode(body,validate=True).decode("utf-8").strip().splitlines()
        self.assertEqual(len(links),2)
        self.assertFalse(any("Автовыбор" in link for link in links))

    def test_remote_registered_but_not_selected_is_not_synced(self):
        self.sub["node_ids"]=["local"]
        self.remote_node()
        calls=[]
        self.namespace["node_api"].sync_profile=lambda *args,**kw:calls.append(args)
        status,_,body=self.fetch()
        self.assertEqual(status,200)
        self.assertEqual(calls,[])
        self.assertEqual(len(base64.b64decode(body).decode().splitlines()),1)

    def test_remote_only_publishes_no_local_node(self):
        self.sub["node_ids"]=["a"*16]
        self.remote_node()
        status,_,body=self.fetch()
        self.assertEqual(status,200)
        lines=base64.b64decode(body).decode().strip().splitlines()
        self.assertEqual(len(lines),1)
        self.assertIn("node2.example",lines[0])
        self.assertNotIn("vpn.example",lines[0])

    def test_failed_remote_is_not_silently_dropped(self):
        self.sub["node_ids"]=["local","a"*16]
        self.remote_node()
        def failed(*args,**kw):
            raise self.namespace["node_api"].NodeError("Node unreachable")
        self.namespace["node_api"].NodeError=type("NodeError",(ValueError,),{})
        self.namespace["node_api"].sync_profile=failed
        status,_,body=self.fetch()
        self.assertEqual(status,503)
        self.assertIn("не обновлена",body.decode())

    def test_wrong_node_host_is_rejected(self):
        self.sub["node_ids"]=["local","a"*16]
        self.remote_node()
        self.namespace["node_api"].NodeError=type("NodeError",(ValueError,),{})
        self.namespace["node_api"].sync_profile=lambda *args,**kw:{
            "ok":True,"profiles":[{"protocol":"vless",
                                  "link":"vless://uuid@wrong.example:443?type=xhttp"}]
        }
        status,_,body=self.fetch()
        self.assertEqual(status,503)
        self.assertIn("не обновлена",body.decode())

    def test_removed_node_is_an_explicit_error(self):
        self.sub["node_ids"]=["a"*16]
        status,_,body=self.fetch()
        self.assertEqual(status,409)
        self.assertIn("удалена",body.decode())

    def test_legacy_subscription_stays_on_main_node(self):
        self.sub.pop("node_ids",None)
        self.remote_node()
        calls=[]
        self.namespace["node_api"].sync_profile=lambda *args,**kw:calls.append(args)
        status,_,body=self.fetch()
        self.assertEqual(status,200)
        self.assertEqual(calls,[])
        self.assertIn("vpn.example",base64.b64decode(body).decode())

    def test_explicit_xray_format_still_returns_single_node_json(self):
        status,h,body=self.fetch("?format=xray")
        self.assertEqual(status,200)
        self.assertIn("application/json",h["Content-Type"])
        configs=json.loads(body)
        self.assertEqual(len(configs),1)
        self.assertEqual(configs[0]["remarks"],"🇳🇱 Нидерланды")
        self.assertTrue(any(o["protocol"]=="vless" for o in configs[0]["outbounds"]))
        self.assertFalse(configs[0].get("routing",{}).get("balancers"))

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
