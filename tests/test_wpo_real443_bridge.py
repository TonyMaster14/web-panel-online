"""Offline regression for the opt-in Sweden real443 compatibility bridge."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import wpo_real443_bridge as bridge
import wpo_node_vpn as vpn

DOMAIN = "swejeep.goodarielservice.xyz"
UUID = "12345678-1234-1234-1234-123456789abc"

def source(clients=None):
    if clients is None:
        clients = [{"id": UUID, "email": "node:a", "flow": "xtls-rprx-vision"}]
    return {"inbounds": [
        {"tag": "vless-reality", "port": 19444, "protocol": "vless",
         "settings": {"decryption": "none", "clients": clients},
         "streamSettings": {"network": "tcp", "security": "reality",
                            "realitySettings": {
                                "privateKey": "abc",
                                "shortIds": ["aabb"],
                                "minClientVer": "1.0.0",
                                "serverNames": ["www.nvidia.com"]}}},
        {"tag": "wpo-vless-xhttp", "port": 19000, "protocol": "vless",
         "settings": {"clients": []}, "streamSettings": {"network": "xhttp", "security": "none"}}
    ]}

def canary(clients=None):
    if clients is None: clients=[]
    return {"log": {"loglevel": "warning"},
            "inbounds": [{"tag": "wpo-remna-canary-reality", "port": 443,
              "listen": "0.0.0.0", "protocol": "vless",
              "settings": {"decryption": "none", "clients": clients},
              "streamSettings": {"network": "tcp", "security": "reality",
              "realitySettings": {
                  "privateKey": "abc", "shortIds": ["aabb"], "minClientVer": "1.0.0",
                  "serverNames": [DOMAIN], "dest": bridge.SOCKET, "xver": 1}}}],
            "outbounds": [{"tag": "direct", "protocol": "freedom"}]}

class SwedenReal443BridgeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.marker=self.root/"managed.json"
        self.canary=self.root/"canary.json"
        self._patch(patch.object(bridge, "MODE", self.marker))
        self._patch(patch.object(bridge, "CANARY", self.canary))
        self._patch(patch.object(bridge, "BINARY", self.root/"xray"))
        self._patch(patch.object(bridge, "SERVICE", "test-xray.service"))
        (self.root/"xray").write_text("fake")

    def _patch(self,p):
        p.start();self.addCleanup(p.stop)

    def enable(self):
        self.marker.write_text(json.dumps({"mode": "remna-443-mirror-v1",
                                           "domain": DOMAIN}))

    def test_disabled_by_default(self):
        self.assertFalse(bridge.enabled_for(DOMAIN))
        self.assertFalse(bridge.reconcile(source()))
        self.assertFalse(self.canary.exists())

    def test_strict_marker(self):
        self.enable()
        self.assertTrue(bridge.enabled_for(DOMAIN))
        with self.assertRaisesRegex(RuntimeError, "only allowed"):
            bridge.enabled_for("pl.example.com")
        self.marker.write_text('{"mode":"unknown","domain":"'+DOMAIN+'"}')
        with self.assertRaisesRegex(RuntimeError, "Unsupported"):
            bridge.enabled_for(DOMAIN)

    def test_pure_add_and_remove_without_tampering_with_security(self):
        before=canary()
        copy_before=copy.deepcopy(before)
        created=bridge.mirror_config(source(),before)
        self.assertEqual(created["inbounds"][0]["settings"]["clients"],
                         source()["inbounds"][0]["settings"]["clients"])
        self.assertEqual(before,copy_before)
        deleted=bridge.mirror_config(source([]),created)
        self.assertEqual(deleted["inbounds"][0]["settings"]["clients"], [])
        self.assertEqual(deleted["inbounds"][0]["streamSettings"]["realitySettings"],
                         before["inbounds"][0]["streamSettings"]["realitySettings"])
        self.assertEqual(deleted["outbounds"],before["outbounds"])

    def test_refuses_private_key_mismatch_or_wrong_listener(self):
        wrong=canary()
        wrong["inbounds"][0]["streamSettings"]["realitySettings"]["privateKey"]="different"
        with self.assertRaisesRegex(RuntimeError,"mismatch"):
            bridge.mirror_config(source(),wrong)
        wrong=canary()
        wrong["inbounds"][0]["port"]=24443
        with self.assertRaisesRegex(RuntimeError,"no longer"):
            bridge.mirror_config(source(),wrong)
        with self.assertRaisesRegex(RuntimeError,"duplicate"):
            bridge.mirror_config(source([{"id": UUID,"flow":"xtls-rprx-vision"}]*2), canary())

    def test_reality_link_uses_node_domain_only_when_enabled(self):
        profile={"sni":"www.nvidia.com","address":DOMAIN,"port":443,
                 "public_key":"somepublic","short_id":"aabb","fingerprint":"firefox"}
        def make_link(_secret,_name,p):
            return p["address"]+"|"+p["sni"]+"|"+str(p["port"])
        self.assertEqual(bridge.reality_link(UUID,"test",DOMAIN,profile,make_link),
                         DOMAIN+"|www.nvidia.com|443")
        self.enable()
        with patch.object(bridge, "verify_active"):
            self.assertEqual(bridge.reality_link(UUID,"test",DOMAIN,profile,make_link),
                             DOMAIN+"|"+DOMAIN+"|443")

    def test_reconcile_validates_and_restarts_only_isolated_canary(self):
        self.enable()
        self.canary.write_text(json.dumps(canary()))
        calls=[]
        class R:
            returncode=0
            stderr=""
        def run(*args,**kwargs):
            calls.append(args)
            return R()
        class FakeSocket:
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(bridge,"_run",side_effect=run), \
             patch.object(bridge.socket,"create_connection",return_value=FakeSocket()):
            updated=bridge.reconcile(source())
        self.assertTrue(updated)
        self.assertEqual(json.loads(self.canary.read_text())["inbounds"][0]["settings"]["clients"],
                         source()["inbounds"][0]["settings"]["clients"])
        self.assertEqual([c for c in calls if c[:2]==("systemctl","restart")],
                         [("systemctl","restart","test-xray.service")])
        calls.clear()
        with patch.object(bridge,"_run",side_effect=run):
            self.assertFalse(bridge.reconcile(source()))
        self.assertEqual(calls,[])

    def test_install_hook_keeps_default_node_path_unchanged(self):
        class API:
            def do_GET(self): return {"ok": True}
            def do_POST(self): return {"ok": True}
        calls = []
        def original_apply(state):
            calls.append(("apply", state))
            return "ok"
        def original_link(*args):
            calls.append(("link", args))
            return "legacy"
        ns={"apply":original_apply, "link":original_link, "API": API,
            "SETTINGS":self.root/"settings.json",
            "read_json": lambda _: {"domain": "other.example.com"},
            "render_xray": lambda state, settings: state,
            "wpo_reality": object()}
        bridge.install(ns)
        self.assertEqual(ns["apply"]({}),"ok")
        self.assertEqual(ns["link"]("reality","uuid","title",{"domain":"other.example.com"}),"legacy")
        self.assertEqual(calls,[("apply",{}),
                                ("link",("reality","uuid","title",{"domain":"other.example.com"}))])
        self.assertEqual(API().do_GET(),{"ok":True})
        self.assertEqual(API().do_POST(),{"ok":True})


if __name__=="__main__":
    unittest.main()
