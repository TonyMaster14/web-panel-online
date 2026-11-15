"""Regression: Node 0.4 federation must handle VLESS-only cleanup and native connections.

This reproduces the actual VPS traceback:
 wpo_node_eight.remove -> native_apply -> extras._connection_map
 AttributeError: 'str' object has no attribute 'get'
No system services or real credentials are used.
"""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import wpo_node_eight as engine
import wpp_extra_protocols as extras


class TestNodeFederationNativeConnections(unittest.TestCase):
    def test_connections_are_dict_items_not_envelope(self):
        records = engine._native_connections()
        self.assertIsInstance(records, list)
        self.assertEqual({c["protocol"] for c in records}, {"naive", "mieru"})
        self.assertEqual(set(extras._connection_map(records)),
                         {"naive-primary", "mieru-primary"})

    def test_native_apply_passes_valid_connection_items(self):
        applied = []
        def check(users, connections, domain, cert, key):
            applied.append((domain, extras._connection_map(connections)))
        with patch.object(engine, "_update_mtproxy"), \
             patch.object(engine.awg, "sync"), \
             patch.object(engine.extras, "sync", side_effect=check):
            engine.native_apply({}, {"domain": "baba.goodarielservice.xyz"})
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0][0], "baba.goodarielservice.xyz")
        self.assertEqual(set(applied[0][1]), {"naive-primary", "mieru-primary"})

    def setup_profiles(self):
        return {"a"*64: {"name": "WPO test", "secrets": {
            "vless": "cc98a634-bf01-42f0-8c9c-1fd3d5338e55",
            "hysteria": "81899b7c-3a8d-4ea5-bbe0-22c45c03e2a4",
        }, "native": {}}}

    def run_vless_change(self, operation, fail_first=False):
        old=self.setup_profiles()
        with tempfile.TemporaryDirectory(prefix="wpo-native-") as td:
            state=Path(td)/"profiles.json"
            lock=Path(td)/"federation.lock"
            settings=Path(td)/"settings.json"
            def lookup(path, default=None):
                if path == state:
                    return {"profiles":old}
                if path == settings:
                    return {"domain":"baba.goodarielservice.xyz"}
                raise AssertionError(path)
            count=0
            def apply(value):
                nonlocal count
                count+=1
                if fail_first and count==1:
                    raise RuntimeError("simulated Xray failure")
            with patch.object(engine.xray, "LOCK",lock), \
                 patch.object(engine, "STATE",state), \
                 patch.object(engine, "SETTINGS",settings), \
                 patch.object(engine.xray, "read_json",side_effect=lookup), \
                 patch.object(engine.xray, "apply",side_effect=apply), \
                 patch.object(engine.xray, "atomic_json") as saved, \
                 patch.object(engine, "native_apply") as native:
                if fail_first:
                    with self.assertRaisesRegex(RuntimeError,"simulated Xray"):
                        operation(next(iter(old)))
                    self.assertEqual(count,2)
                    saved.assert_not_called()
                else:
                    output=operation(next(iter(old)))
                    self.assertTrue(output["ok"])
                    saved.assert_called_once_with(state,{"profiles":{}})
                native.assert_not_called()

    def test_remove_vless_hysteria_only_skips_unrelated_native_services(self):
        self.run_vless_change(lambda identifier: engine.remove({"external_id":identifier}))

    def test_remove_rollback_skips_unrelated_native_services(self):
        self.run_vless_change(lambda identifier: engine.remove({"external_id":identifier}),True)

    def test_purge_vless_hysteria_only_skips_native_services(self):
        self.run_vless_change(lambda identifier: engine.purge())


if __name__ == "__main__":
    unittest.main()
