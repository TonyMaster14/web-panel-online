"""Exercise REAL WPO Happ HTTP handler with delayed verified node provisioning.

First GET must complete while both remote APIs are still slow; subsequent GET
must contain the original local VLESS plus 2 VERIFIED remote links and auto.
"""
import ast
import base64
import importlib.util
import json
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote
import unittest
from unittest import mock

import wpo_node_selection_v2 as exact
import wpo_happ_async_feed as remote
from test_subscription_happ_http import HappSubscription, panel as exact_panel

ROOT=Path(__file__).resolve().parents[1]
def from_file(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"maintenance/happ"/(name.replace("_","-")+".py"))
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

parallel=from_file("wpo_multinode_feed_fix")
async_patch=from_file("wpo_happ_async_panel_patch")
PANEL=async_patch.patch(parallel.patch(exact_panel))
ast.parse(PANEL)
tree=ast.parse(PANEL)
handler=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=="Handler")
methods=[x for x in handler.body if isinstance(x,ast.FunctionDef)
         and x.name in ("serve_subscription","send_data","send_html")]
klass=ast.fix_missing_locations(ast.ClassDef(name="Handler",
    bases=[ast.Name(id="BaseHTTPRequestHandler",ctx=ast.Load())],
    keywords=[],body=methods,decorator_list=[]))
module=ast.fix_missing_locations(ast.Module(body=[klass],type_ignores=[]))


class AsyncFeedHTTP(HappSubscription):
    def setUp(self):
        super().setUp()
        self.remote_case=self._testMethodName.startswith("test_async_")
        if not self.remote_case:
            return
        for cache in (remote.CACHE,remote.PENDING,remote.FAILURES):
            with remote.LOCK:
                cache.clear()
        self.namespace["wpo_happ_async_feed"]=remote
        exec(compile(module,"happ-fast-test.py","exec"),self.namespace)
        cls=self.namespace["Handler"]
        cls.log_message=lambda *args: None
        cls.do_GET=lambda h:h.serve_subscription(h.path.split("/wpp-sub/",1)[-1].split("?",1)[0])
        self.server.RequestHandlerClass=cls
        self.sub["node_ids"]=["local","a"*16,"b"*16]
        self.nodes=[
            {"id":"a"*16,"url":"https://pl.example.net","enabled":True,"token":"SECRET1"},
            {"id":"b"*16,"url":"https://se.example.net","enabled":True,"token":"SECRET2"},
        ]
        self.namespace["node_api"].load_nodes=lambda path:self.nodes
        self.namespace["node_api"].API_PREFIX="/wpp-api/v1"
        self.namespace["node_api"].NodeError=type("NodeError",(ValueError,),{})
        self.release=threading.Event()
        self.called=threading.Event()
        self.calls=[]
        self.mutex=threading.Lock()
        def request(node,method,path,data,timeout):
            self.assertEqual(timeout,90)
            self.assertEqual(method,"POST")
            self.assertEqual(path,"/wpp-api/v1/federation/sync")
            with self.mutex:
                self.calls.append(node["url"])
                if len(self.calls)>=2:
                    self.called.set()
            self.release.wait(4)
            host=node["url"].split("//",1)[1]
            return {"ok":True,"profiles":[{
                "protocol":"vless",
                "link":"vless://11111111-1111-4111-8111-111111111111@"
                       +host+":443?encryption=none&security=tls&type=xhttp#"+quote("VPN")}]}
        self.namespace["node_api"].request=request
        self.addCleanup(self.release.set)

    def test_async_http_returns_local_before_slow_post_finishes(self):
        t0=time.monotonic()
        status,headers,body=self.fetch()
        elapsed=time.monotonic()-t0
        self.assertEqual(status,200,body)
        self.assertLess(elapsed,1.0,"Happ GET waited on remote restart")
        self.assertIn("vpn.example",base64.b64decode(body).decode())
        self.assertNotIn("pl.example",base64.b64decode(body).decode())
        self.assertEqual(headers.get("profile-update-interval"),"1")
        self.assertTrue(self.called.wait(3))
        self.assertEqual(len(self.calls),2)
        self.release.set()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            with remote.LOCK:
                if len(remote.CACHE)>=2:
                    break
            time.sleep(.02)
        status,headers,body=self.fetch()
        self.assertEqual(status,200,body)
        configs=json.loads(body)
        self.assertEqual(len(configs),4) # auto, local, PL, SE
        serialized=json.dumps(configs)
        for host in ("vpn.example","pl.example.net","se.example.net"):
            self.assertIn(host,serialized)
        self.assertEqual(self.calls.count("https://pl.example.net"),1)
        self.assertEqual(self.calls.count("https://se.example.net"),1)
        self.assertNotIn("SECRET",serialized)

    def test_async_three_servers_two_protocols_produce_six_real_profiles(self):
        # One physical host appears twice: VLESS + Hysteria2. That does not
        # count as two separate nodes for the auto-balancer.
        second=dict(self.user, id="h"*16, protocol="hysteria",
                    connection_id="hysteria-primary", backend_port=8443,
                    secret="fedcba987654")
        self.manager["users"]=[dict(self.user), second]
        def request(node,method,path,data,timeout):
            self.assertEqual(method,"POST")
            self.assertEqual(path,"/wpp-api/v1/federation/sync")
            self.assertEqual(set(data["protocols"]),{"vless","hysteria"})
            host=node["url"].split("//",1)[1]
            return {"ok":True,"profiles":[
                {"protocol":"vless",
                 "link":"vless://11111111-1111-4111-8111-111111111111@"
                        +host+":443?encryption=none&security=tls&type=xhttp#VPN"},
                {"protocol":"hysteria",
                 "link":"hysteria2://node-secret@"+host+":8443/?sni="+host+"#VPN"},
            ]}
        self.namespace["node_api"].request=request
        self.release.set()
        self.fetch()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            with remote.LOCK:
                if len(remote.CACHE)>=2:break
            time.sleep(.02)
        status,_,body=self.fetch()
        self.assertEqual(status,200,body)
        configs=json.loads(body)
        self.assertEqual(len(configs),7,"auto + 2 NL + 2 PL + 2 SE")
        self.assertIn("Автовыбор",configs[0]["remarks"])
        for host in ("vpn.example","pl.example.net","se.example.net"):
            self.assertEqual(sum(host in json.dumps(c) for c in configs[1:]),2,host)

    def test_async_remote_only_without_verified_links_remains_explicit_pending(self):
        self.sub["node_ids"]=["a"*16,"b"*16]
        status,_,body=self.fetch()
        self.assertEqual(status,503)
        self.assertIn("подготавливаются",body.decode())
        self.release.set()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            with remote.LOCK:
                if len(remote.CACHE)>=2:break
            time.sleep(.02)
        status,_,body=self.fetch()
        self.assertEqual(status,200,body)
        self.assertEqual(len(json.loads(body)),3)

    def test_async_patch_idempotent_and_preserves_selection_safety(self):
        self.assertEqual(async_patch.patch(PANEL),PANEL)
        self.assertIn('local_count=len(result["users"]) if local_selected else 0',PANEL)
        self.assertIn("wpo_happ_async_feed.enqueue",PANEL)
        self.assertIn("if not lines:",PANEL)
        self.assertIn('len(distinct_nodes)>1',PANEL)

if __name__=="__main__":
    unittest.main()
