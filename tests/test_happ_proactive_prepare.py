"""WPO preparer produces authenticated verified remote profiles ahead of Happ HTTP."""
from pathlib import Path
import importlib.util
import hashlib
import json
import tempfile
import time
from urllib.error import HTTPError
from unittest import mock
import unittest

import wpo_happ_async_feed as feed
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_happ_preparer",ROOT/"wpo_happ_preparer.py")
prep=importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)

class ProactivePreparation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.users=root/"users.json"
        self.ready=root/"ready.json"
        self.nodes=root/"nodes.json"
        self.domain="wpo.example.com"
        self.s="a"*16
        self.d="b"*16
        self.remote=[
            {"id":"c"*16,"url":"https://pl.example.net","enabled":True,"token":"DO_NOT_PRINT"},
            {"id":"d"*16,"url":"https://se.example.net","enabled":True,"token":"DO_NOT_PRINT"},
        ]
        self.users.write_text(json.dumps({"subscriptions":[{
            "id":self.s,"enabled":True,"node_ids":["local","c"*16,"d"*16],
            "connections":[{"protocol":"vless"}],
            "devices":[{"id":self.d,"revoked":False,"preallocated":True}]
        }]}))
        self.patchers=[
            mock.patch.object(prep,"USERS",self.users),
            mock.patch.object(prep,"NODES",self.nodes),
            mock.patch.object(prep,"READY",self.ready),
            mock.patch.object(prep,"domain",return_value=self.domain),
            mock.patch.object(prep.api,"load_nodes",return_value=self.remote),
            mock.patch.object(prep.api,"location_prefix",return_value="🇳🇱 Нидерланды")
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_verified_credentials_are_ready_before_first_hwid_claim(self):
        seen=[]
        def request(node,method,path,payload,timeout):
            self.assertEqual(method,"POST")
            self.assertEqual(timeout,90)
            self.assertEqual(path,"/wpp-api/v1/federation/sync")
            self.assertEqual(payload["protocols"],["vless"])
            expected=hashlib.sha256((self.domain+":"+self.s+":"+self.d).encode()).hexdigest()
            self.assertEqual(payload["external_id"],expected)
            seen.append(node["url"])
            host=node["url"].split("://",1)[1]
            return {"ok":True,"profiles":[{"protocol":"vless",
                "link":"vless://11111111-1111-4111-8111-111111111111@"
                       +host+":443?encryption=none&security=tls&type=xhttp"}]}
        with mock.patch.object(prep.api,"request",side_effect=request):
            self.assertTrue(prep.prepare())
        self.assertEqual(len(seen),2)
        stored=json.loads(self.ready.read_text())
        self.assertEqual(len(stored),2)
        self.assertNotIn("DO_NOT_PRINT",self.ready.read_text())
        self.assertNotIn("vless://",self.ready.read_text())
        with mock.patch.object(feed,"Path",side_effect=lambda name: self.ready):
            external_id=hashlib.sha256((self.domain+":"+self.s+":"+self.d).encode()).hexdigest()
            self.assertTrue(feed.prewarmed(self.remote,external_id,["vless"]))

    def test_one_failed_node_is_not_misreported_as_ready(self):
        def request(node,method,path,payload,timeout):
            if "pl.example.net" in node["url"]:
                return {"ok":True,"profiles":[{"protocol":"vless",
                    "link":"vless://11111111-1111-4111-8111-111111111111@pl.example.net:443"}]}
            from urllib.error import HTTPError
            from io import BytesIO
            e=HTTPError(node["url"],503,"unavailable",None,BytesIO(b''))
            raise prep.api.NodeError("node unavailable") from e
        with mock.patch.object(prep.api,"request",side_effect=request):
            self.assertFalse(prep.prepare())
        self.assertEqual(len(json.loads(self.ready.read_text())),1)

    def test_no_devices_means_no_fabricated_profiles(self):
        content=json.loads(self.users.read_text())
        content["subscriptions"][0]["devices"]=[]
        self.users.write_text(json.dumps(content))
        with mock.patch.object(prep.api,"request") as r:
            self.assertTrue(prep.prepare())
            r.assert_not_called()

if __name__=="__main__":
    unittest.main()
