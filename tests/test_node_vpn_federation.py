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

    def test_failed_apply_restores_xray_readable_permissions(self):
        # Before the fix, rollback wrote root-only 0600 config. Restarting
        # Xray as user xray then failed, leaving a persistent federation 503.
        import stat
        from types import SimpleNamespace
        old=b'{"old":true}\\n'
        vpn.XRAY.write_bytes(old)
        bad=SimpleNamespace(returncode=1,stderr="invalid config")
        ok=SimpleNamespace(returncode=0,stderr="")
        with (mock.patch.object(vpn,"command",side_effect=[bad,ok]),
              mock.patch.object(vpn.os,"chown"),
              mock.patch("grp.getgrnam",return_value=SimpleNamespace(gr_gid=123))):
            with self.assertRaisesRegex(RuntimeError,"validation failed"):
                vpn.apply({})
        self.assertEqual(vpn.XRAY.read_bytes(),old)
        self.assertEqual(stat.S_IMODE(vpn.XRAY.stat().st_mode),0o640)

    def test_invalid_id_or_protocol_cannot_provision(self):
        for data in [
            {"external_id": "../../etc/passwd", "name": "X", "protocols": ["vless"]},
            {"external_id": "d"*64, "name": "X", "protocols": ["reality"]},
            {"external_id": "d"*64, "name": "X", "protocols": ["hysteria", "vless", "web"]},
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                vpn.valid_params(data)

    def test_base_health_remains_ready_during_incomplete_eight_engine_retry(self):
        # A first installation may fail after dropping wpo_node_eight.py,
        # while its remaining native services are not running yet.
        import wpo_node_eight as eight
        replies = []
        handler = type("FakeHandler", (), {
            "path": "/healthz",
            "respond": lambda self, body, status=200: replies.append((status, body)),
        })()
        with mock.patch.object(vpn, "live", return_value=True), \
             mock.patch.object(eight, "available", return_value=frozenset({"vless", "hysteria"})), \
             mock.patch.object(eight, "full_ready", return_value=False):
            vpn.API.do_GET(handler)
        self.assertEqual(replies[0][0], 200)
        self.assertTrue(replies[0][1]["ok"], "Base VPN must not depend on all 8 engines")
        self.assertFalse(replies[0][1]["all_protocols_ready"])
        self.assertEqual(set(replies[0][1]["capabilities"]),
                         {"federation", "vless", "hysteria"})

    def test_base_health_rejects_unhealthy_xray_or_caddy(self):
        import wpo_node_eight as eight
        replies=[]
        handler=type("FakeHandler", (), {
            "path": "/healthz",
            "respond": lambda self, body, status=200: replies.append(body),
        })()
        with mock.patch.object(vpn, "live", return_value=False), \
             mock.patch.object(eight, "available", return_value=frozenset()), \
             mock.patch.object(eight, "full_ready", return_value=False):
            vpn.API.do_GET(handler)
        self.assertFalse(replies[0]["ok"])
        self.assertFalse(replies[0]["all_protocols_ready"])

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

    def test_short_sudo_patch_detects_controller_or_node(self):
        dispatcher=(ROOT / "maintenance/other/wpo-vpn-patch.sh").read_text()
        self.assertIn("/opt/tproxy-panel/panel.py",dispatcher)
        self.assertIn("/etc/wpp-node-agent/config.json",dispatcher)
        self.assertIn('target="wpo-node-controller-vpn.sh"',dispatcher)
        self.assertIn('target="wpo-node-vpn-enable.sh"',dispatcher)
        self.assertIn('bash -n "$TMP"',dispatcher)
        self.assertIn('WPO_NODE_VPN_REF="$REF" bash "$TMP"',dispatcher)
        self.assertIn('controller == 1 && node == 1',dispatcher)

    def test_runtime_patch_arguments_expand_in_real_bash(self):
        for filename in ("wpo-node-vpn-enable.sh","wpo-node-controller-vpn.sh","wpo-vpn-patch.sh"):
            source=(ROOT / filename).read_text()
            self.assertNotIn(r"\${",source,filename)
        node_script=(ROOT / "wpo-node-vpn-enable.sh").read_text()
        self.assertIn('REF="${WPO_NODE_VPN_REF:-test/wpo-smooth-progress-v1}"',node_script)
        self.assertIn("stream.write('\\n')",node_script)
        self.assertNotIn("stream.write('\\\\n')",node_script)

    def test_package_includes_federation_capability_and_autoinstall(self):
        script=(ROOT / "wpo-node-agent-install-v2.sh").read_text()
        controller=(ROOT / "node-install.sh").read_text()
        assert "wpo-node-vpn-enable.sh" in script
        assert 'WPO_NODES_VPN_DURING_INSTALL=1' in controller
        assert 'wpo-node-controller-vpn.sh' in controller


if __name__ == "__main__":
    unittest.main()
