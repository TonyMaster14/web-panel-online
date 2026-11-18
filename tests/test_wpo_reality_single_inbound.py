"""Regression: default REALITY configuration stays short and persists through WPO Node render_xray."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import wpo_reality as reality
import wpo_node_vpn as node


class SingleRealityTest(unittest.TestCase):
    def test_routes_and_xray_inbound_match_selected_sni(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / "private.key"
            key.write_text("test-private-key-not-for-production\n", encoding="ascii")
            for sni in ("www.nvidia.com", "www.apple.com", "www.amazon.com"):
                profile = {"sni": sni, "short_id": "abcd1234",
                           "address": "test.example.com", "port": 443}
                with self.subTest(sni=sni), patch.object(reality, "PRIVATE", key):
                    routes = reality.reality_routes(profile)
                    self.assertEqual(routes, [(sni, 19444)])
                    result = reality.inbounds([{"id": "test-uuid"}], profile)
                    self.assertEqual(len(result), 1)
                    inbound = result[0]
                    self.assertEqual(inbound["tag"], "vless-reality")
                    self.assertEqual(inbound["port"], 19444)
                    self.assertEqual(inbound["settings"]["clients"], [{"id": "test-uuid"}])
                    settings = inbound["streamSettings"]["realitySettings"]
                    self.assertEqual(settings["serverNames"], [sni])
                    self.assertEqual(settings["target"], sni + ":443")
                    self.assertEqual(settings["minClientVer"], "1.0.0")
                    self.assertEqual(settings["shortIds"], ["abcd1234"])

    def test_node_generator_keeps_single_reality_across_sync(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / "private.key"
            key.write_text("test-private-key-not-for-production\n", encoding="ascii")
            profile = {"sni": "www.nvidia.com", "short_id": "abcd1234",
                       "address": "test.example.com", "port": 443}
            with patch.object(node, "REALITY_READY", True), \
                 patch.object(node, "wpo_reality", reality), \
                 patch.object(reality, "PRIVATE", key), \
                 patch.object(reality, "read_profile", return_value=profile):
                config = node.render_xray({}, {"domain": "test.example.com",
                                                "xhttp_path": "/wpo-test"})
            inbounds = config["inbounds"]
            self.assertEqual(len(inbounds), 1)
            self.assertEqual(inbounds[0]["streamSettings"]["security"], "reality")
            self.assertEqual(
                inbounds[0]["streamSettings"]["realitySettings"]["minClientVer"],
                "1.0.0"
            )
            self.assertEqual(config["outbounds"], [{"tag": "direct", "protocol": "freedom"}])


if __name__ == "__main__":
    unittest.main()
