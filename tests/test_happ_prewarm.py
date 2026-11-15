"""Prewarm only existing Happ HWID devices over authenticated Node API, in parallel."""
import contextlib
from io import StringIO
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
src=ROOT/"maintenance/happ/wpo-happ-prewarm.py"
spec=importlib.util.spec_from_file_location("wpo_happ_prewarm",src)
warm=importlib.util.module_from_spec(spec)
spec.loader.exec_module(warm)


class Prewarm(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"users.json"
        self.sub={"id":"c"*16,"name":"123","enabled":True,"created_at":45,
                  "node_ids":["local","a"*16,"b"*16],
                  "connections":[{"protocol":"vless"}],
                  "devices":[{"id":"d"*16,"created_at":50,"revoked":False}]}
        self.path.write_text(json.dumps({"subscriptions":[self.sub]}))
        self.nodes=[
            {"id":"a"*16,"url":"https://pl.example.net","token":"SENSITIVE_TOKEN1","enabled":True},
            {"id":"b"*16,"url":"https://se.example.net","token":"SENSITIVE_TOKEN2","enabled":True}]
        self.patches=[
            mock.patch.object(warm,"USERS",self.path),
            mock.patch.object(warm,"domain",return_value="main.example.net"),
            mock.patch.object(warm.api,"load_nodes",return_value=self.nodes),
            mock.patch.object(warm.api,"location_prefix",return_value="🇳🇱 Нидерланды")]
        for patch in self.patches:
            patch.start();self.addCleanup(patch.stop)

    def test_parallel_preparation_preserves_hwid_and_secret(self):
        barrier=threading.Barrier(2,timeout=2)
        used=[]
        def send(node,method,path,payload,timeout):
            self.assertEqual(timeout,90)
            self.assertEqual(method,"POST")
            self.assertEqual(path,"/wpp-api/v1/federation/sync")
            self.assertEqual(payload["protocols"],["vless"])
            self.assertEqual(payload["external_id"],
                hashlib.sha256(("main.example.net:"+self.sub["id"]+":"+"d"*16).encode()).hexdigest())
            used.append(node["url"])
            barrier.wait()
            host=node["url"].split("//",1)[1]
            return {"ok":True,"profiles":[{
                "protocol":"vless","link":"vless://11111111-1111-4111-8111-111111111111@"
                                       +host+":443?security=tls&type=xhttp"}]}
        with mock.patch.object(warm.api,"request",side_effect=send):
            output=StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(warm.prepare())
        self.assertEqual(set(used),{"https://pl.example.net","https://se.example.net"})
        self.assertNotIn("SENSITIVE_TOKEN",output.getvalue())
        self.assertIn("Все выбранные удалённые профили готовы",output.getvalue())
        self.assertEqual(json.loads(self.path.read_text())["subscriptions"][0],self.sub)

    def test_http_503_is_visible_without_secret(self):
        def fail(node,*args,**kwargs):
            cause=Exception("upstream")
            cause.code=503
            error=warm.api.NodeError("Нода не отвечает или отклонила API-токен.")
            raise error from cause
        with mock.patch.object(warm.api,"request",side_effect=fail):
            output=StringIO()
            with contextlib.redirect_stdout(output):
                self.assertFalse(warm.prepare())
        self.assertIn("HTTP 503",output.getvalue())
        self.assertNotIn("SENSITIVE_TOKEN",output.getvalue())
        self.assertNotIn("upstream",output.getvalue())

    def test_missing_happ_device_never_creates_fake_identity(self):
        self.sub["devices"]=[]
        self.path.write_text(json.dumps({"subscriptions":[self.sub]}))
        with mock.patch.object(warm.api,"request") as api:
            output=StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(warm.prepare())
            api.assert_not_called()

if __name__=="__main__":
    unittest.main()
