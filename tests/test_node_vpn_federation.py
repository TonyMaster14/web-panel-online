"""Test remote-node VPN federation without installing services or opening ports."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock
import uuid

import wpo_node_vpn as vpn

ROOT = Path(__file__).resolve().parents[1]


class NodeFederationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wpo-node-vpn-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({
            "domain": "se.example.net",
            "xhttp_path": "/wpo-xhttp-1234567890abcdef12345678",
        }), encoding="utf-8")
        for name, file in {
            "SETTINGS": settings,
            "STATE": self.root / "profiles.json",
            "XRAY": self.root / "xray.json",
            "LOCK": self.root / ".lock",
            "CERT": self.root / "cert.crt",
            "KEY": self.root / "cert.key",
        }.items():
            original = getattr(vpn, name)
            patcher = mock.patch.object(vpn, name, file)
            patcher.start()
            self.addCleanup(patcher.stop)
        vpn.CERT.write_text("example cert")
        vpn.KEY.write_text("example key")

    def test_render_real_xhttp_and_hysteria2_inbounds(self):
        identifier = "a" * 64
        vless_id = str(uuid.uuid4())
        hysteria_id = str(uuid.uuid4())
        config = vpn.render_xray({
            identifier: {"name": "🇸🇪 Швеция", "secrets": {
                "vless": vless_id, "hysteria": hysteria_id
            }}
        }, vpn.read_json(vpn.SETTINGS))
        self.assertEqual([x["protocol"] for x in config["inbounds"]],
                         ["vless", "hysteria"])
        vless, hysteria = config["inbounds"]
        self.assertEqual(vless["streamSettings"]["network"], "xhttp")
        self.assertEqual(vless["listen"], "127.0.0.1")
        self.assertEqual(vless["settings"]["clients"][0]["id"], vless_id)
        self.assertEqual(hysteria["port"], 8443)
        self.assertEqual(hysteria["streamSettings"]["security"], "tls")
        self.assertEqual(hysteria["settings"]["clients"][0]["auth"], hysteria_id)

    def test_remote_links_are_distinct_and_target_remote_host(self):
        settings = vpn.read_json(vpn.SETTINGS)
        key = str(uuid.uuid4())
        vless = vpn.link("vless", key, "🇸🇪 Швеция", settings)
        hysteria = vpn.link("hysteria", key, "🇸🇪 Швеция", settings)
        self.assertTrue(vless.startswith("vless://" + key + "@se.example.net:443?"))
        self.assertIn("type=xhttp", vless)
        self.assertIn("path=%2Fwpo-xhttp-", vless)
        self.assertTrue(hysteria.startswith("hysteria2://" + key + "@se.example.net:8443/?"))
        self.assertIn("alpn=h3", hysteria)
        self.assertNotEqual(vless, hysteria)

    def test_idempotent_sync_reuses_device_keys_and_removes_profiles(self):
        id_ = "b" * 64
        item = {"external_id": id_, "name": "🇸🇪 Швеция",
                "protocols": ["vless", "hysteria"]}
        with mock.patch.object(vpn, "apply") as apply:
            first = vpn.mutate("sync", item)
            second = vpn.mutate("sync", item)
            self.assertEqual(first, second)
            self.assertEqual(len(first["profiles"]), 2)
            self.assertEqual(apply.call_count, 1, "reimport must not restart Xray")
            removed = vpn.mutate("delete", {"external_id": id_})
            self.assertTrue(removed["deleted"])
            self.assertEqual(vpn.read_json(vpn.STATE)["profiles"], {})
            self.assertEqual(apply.call_count, 2)

    def test_failed_apply_never_commits_subscriber_secrets(self):
        with mock.patch.object(vpn, "apply", side_effect=RuntimeError("xray down")):
            with self.assertRaises(RuntimeError):
                vpn.mutate("sync", {"external_id": "c" * 64,
                                    "name": "Sweden", "protocols": ["vless"]})
        self.assertFalse(vpn.STATE.exists())

    def test_invalid_id_or_protocol_cannot_provision(self):
        for data in [
            {"external_id": "../../etc/passwd", "name": "X", "protocols": ["vless"]},
            {"external_id": "d"*64, "name": "X", "protocols": ["reality"]},
            {"external_id": "d"*64, "name": "X", "protocols": ["hysteria", "vless", "web"]},
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                vpn.valid_params(data)

    def test_node_agent_never_advertises_vpn_if_sidecar_unhealthy(self):
        installer=(ROOT / "wpo-node-vpn-enable.sh").read_text()
        assert "if vpn_ready() else []" in installer
        assert "http://127.0.0.1:9089/healthz" in installer
        assert "systemctl is-active --quiet wpo-node-xray.service" in installer
        assert "8195d909f1109b8f3d99eefe401a3c451d7bf4af71f24d3815420f77e5dd2a40" in installer

    def test_controller_does_not_accept_site_only_agents(self):
        bridge=(ROOT / "wpo-node-controller-vpn.sh").read_text()
        assert "wanted_protocols.issubset(caps)" in bridge
        assert '"federation" not in caps' in bridge
        assert '"GET",node_api.API_PREFIX+"/status"' in bridge
        assert "wpo-vpn-controller-v27" in bridge
        assert "def sync_profile(" in (ROOT / "wpp_nodes.py").read_text()

    def test_package_includes_federation_capability_and_autoinstall(self):
        script=(ROOT / "wpo-node-agent-install-v2.sh").read_text()
        controller=(ROOT / "node-install.sh").read_text()
        assert "wpo-node-vpn-enable.sh" in script
        assert 'WPO_NODES_VPN_DURING_INSTALL=1' in controller
        assert 'wpo-node-controller-vpn.sh' in controller


if __name__ == "__main__":
    unittest.main()
