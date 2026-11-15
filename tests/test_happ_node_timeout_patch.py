"""Regression: real WPO Node API errors distinguish HTTP failures from 20s timeouts."""
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_happ_timeout",ROOT/"wpo-happ-node-timeout-patch.py")
patcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(patcher)
import wpp_nodes as node_api

class FederationTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.patched=patcher.patch((ROOT/"wpp_nodes.py").read_text())
        self.assertEqual(patcher.patch(self.patched),self.patched)
        self.ns={"__name__":"test_actual_wpp_nodes_patched"}
        exec(compile(self.patched,"wpp_nodes.py","exec"),self.ns)

    def call(self,backend_error):
        class Opener:
            def open(_,request,timeout):
                self.assertEqual(timeout,90)
                raise backend_error
        with mock.patch.dict(self.ns), mock.patch.object(
                self.ns["urllib"].request,"build_opener",return_value=Opener()):
            self.ns["normalize_url"]=lambda url:url
            self.ns["resolve_public"]=lambda host:None
            try:
                self.ns["sync_profile"](
                    {"url":"https://node.example.net","token":"SENSITIVE_NODE_TOKEN"},
                    "a"*64,"Швеция",["vless"])
                self.fail("Expected NodeError")
            except self.ns["NodeError"] as exc:
                return str(exc)

    def test_http_503_xray_error_is_specific_and_secret_free(self):
        raw=json.dumps({"ok":False,"message":"VPN provisioning failed: Xray did not become ready. SECRET123"}).encode()
        error=HTTPError("https://node.example.net/wpp-api/v1/federation/sync",503,
                        "Service Unavailable",None,BytesIO(raw))
        msg=self.call(error)
        self.assertEqual(msg,"Нода вернула HTTP 503 (Xray не запустился)")
        self.assertNotIn("SECRET",msg)

    def test_invalid_xray_config_is_labeled_without_server_payload(self):
        raw=json.dumps({"ok":False,"message":"Xray configuration validation failed SECRET_UUID"}).encode()
        error=HTTPError("https://node.example.net/wpp-api/v1/federation/sync",503,
                        "Service Unavailable",None,BytesIO(raw))
        self.assertEqual(self.call(error),"Нода вернула HTTP 503 (конфигурация Xray отклонена)")

    def test_generic_error_never_prints_private_body(self):
        raw=b'{"ok": false, "message": "token SECRET_NODE_TOKEN"}'
        error=HTTPError("https://node.example.net",502,"Bad Gateway",None,BytesIO(raw))
        self.assertEqual(self.call(error),"Нода вернула HTTP 502")

    def test_timeout_is_separate_from_token_error(self):
        self.assertIn("время ожидания",self.call(URLError(TimeoutError("timeout"))))

    def test_patcher_refuses_unknown_bases(self):
        with self.assertRaises(ValueError):
            patcher.patch("def request(): pass\n")

if __name__=="__main__":unittest.main()
