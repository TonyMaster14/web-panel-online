"""Actual local HTTP integration: three selected WPO nodes sync concurrently."""
import ast
import json
import threading
import time
import unittest
from types import SimpleNamespace

import wpo_node_selection_v2 as exact
import importlib.util
from pathlib import Path
_file=Path(__file__).resolve().parents[1]/"wpo-multinode-feed-fix.py"
_spec=importlib.util.spec_from_file_location("wpo_multinode_feed_fix",_file)
fast=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fast)
from test_subscription_happ_http import HappSubscription, panel as exact_panel
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

# Get the exact installed Handler class, not a mock implementation.
patched=fast.patch(exact_panel)
tree=ast.parse(patched)
raw=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=="Handler")
methods=[x for x in raw.body if isinstance(x,ast.FunctionDef)
         and x.name in ("serve_subscription","send_data","send_html")]
klass=ast.fix_missing_locations(ast.ClassDef(
    name="Handler",bases=[ast.Name(id="BaseHTTPRequestHandler",ctx=ast.Load())],
    keywords=[],body=methods,decorator_list=[]))
module=ast.fix_missing_locations(ast.Module(body=[klass],type_ignores=[]))


class ThreeNodeHapp(HappSubscription):
    def setUp(self):
        super().setUp()
        exec(compile(module,"three-nodes.py","exec"),self.namespace)
        cls=self.namespace["Handler"]
        cls.log_message=lambda *args: None
        cls.do_GET=lambda h: h.serve_subscription(
            h.path.split("/wpp-sub/",1)[-1].split("?",1)[0])
        self.server.RequestHandlerClass=cls
        self.namespace["node_api"].NodeError=type("NodeError",(ValueError,),{})
        self.sub["node_ids"]=["local","a"*16,"b"*16]
        self.namespace["node_api"].load_nodes=lambda path:[
            {"id":"a"*16,"enabled":True,"url":"https://pl.example.net"},
            {"id":"b"*16,"enabled":True,"url":"https://se.example.net"},
        ]

    def test_parallel_sync_returns_all_nodes_in_saved_order(self):
        rendezvous=threading.Barrier(2,timeout=2)
        calls=[]
        lock=threading.Lock()
        def sync(node,_eid,_name,protos):
            with lock:
                calls.append(node["url"])
            rendezvous.wait()
            host=node["url"].removeprefix("https://")
            return {"ok":True,"profiles":[{
                "protocol":"vless",
                "link":"vless://11111111-1111-4111-8111-111111111111@"
                       +host+":443?security=tls&type=xhttp#"
                       +quote("VPN",safe="")
            }]}
        self.namespace["node_api"].sync_profile=sync
        status,_,body=self.fetch()
        self.assertEqual(status,200,body)
        configurations=json.loads(body)
        self.assertEqual(len(configurations),4)  # auto, NL, PL, SE
        self.assertEqual(configurations[0]["remarks"],"🇪🇺 Автовыбор")
        self.assertEqual([x["remarks"] for x in configurations[1:]],
                         ["🇳🇱 Нидерланды"]*3)
        self.assertEqual(len(calls),2)
        urls=json.dumps(configurations)
        self.assertIn("pl.example.net",urls)
        self.assertIn("se.example.net",urls)
        self.assertIn("vpn.example",urls)

    def test_no_partial_subscription_when_one_remote_rejects_sync(self):
        def sync(node,*args):
            if "pl.example" in node["url"]:
                raise self.namespace["node_api"].NodeError("HTTP 503")
            return {"ok":True,"profiles":[{
                "protocol":"vless",
                "link":"vless://11111111-1111-4111-8111-111111111111@"
                       "se.example.net:443?security=tls&type=xhttp"}]}
        self.namespace["node_api"].sync_profile=sync
        status,_,body=self.fetch()
        self.assertEqual(status,503)
        self.assertIn("не обновлена",body.decode())
        self.assertNotIn("vless://",body.decode())

    def test_removed_selected_node_stays_explicit_409(self):
        self.namespace["node_api"].load_nodes=lambda path:[
            {"id":"a"*16,"enabled":True,"url":"https://pl.example.net"}]
        status,_,body=self.fetch()
        self.assertEqual(status,409)
        self.assertIn("удалена",body.decode())


class PatchSafety(unittest.TestCase):
    def test_ast_and_idempotency(self):
        ast.parse(patched)
        self.assertEqual(fast.patch(patched),patched)
        self.assertIn("wpo-multinode-parallel-v1",patched)
        self.assertIn("ThreadPoolExecutor(max_workers=min(len(remote_nodes),4))",patched)
        self.assertIn('local_count=len(result["users"]) if local_selected else 0',patched)
        self.assertIn('len(distinct_nodes)>1',patched)

if __name__=="__main__":
    unittest.main()

