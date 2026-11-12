"""VLESS REALITY opt-in and backward compatibility tests."""
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import wpp_connections as con
import wpp_reality as reality
import wpp_routing as routing


class RealityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = str(self.root / "connections.json")
        con.save(self.registry, {"connections": con.defaults()})

    def item(self):
        return con.get(con.load(self.registry), "vless-reality-primary")

    def test_reality_is_independent_opt_in(self):
        rows = con.defaults()
        self.assertEqual(rows[0]["id"], "vless-direct")
        self.assertEqual(rows[1]["id"], "hysteria-primary")
        self.assertEqual(rows[-1]["id"], "vless-reality-primary")
        self.assertEqual(con._xray_bucket(rows[0]), "direct")
        self.assertIsNone(con._xray_bucket(rows[-1]))
        self.assertEqual(con.inbound_tag(rows[-1]), "vless-reality-vless-reality-primary")

    def test_invalid_sni_and_port_are_rejected(self):
        value = self.item()
        for sni in ("bad domain", "https://www.example.com", "127.0.0.1:443"):
            value["config"]["sni"] = sni
            with self.assertRaises(con.ConnectionError):
                con.validate(value, existing=value)
        value = self.item()
        value["config"]["port"] = 443
        with self.assertRaises(con.ConnectionError):
            con.validate(value, existing=value)

    def test_persistent_port_and_regular_user(self):
        connection = self.item()
        con.claim_reality_port(self.registry, connection["id"])
        self.assertEqual(self.item()["config"]["port"], 20443)
        request = con.request_for_connection(connection)
        self.assertEqual(request["protocol"], "vless")
        self.assertEqual(request["vless_route"], "direct")
        user = {"protocol": "vless", "name": "Test", "cdn": {"enabled": True}}
        con.apply_to_user(user, connection)
        self.assertNotIn("cdn", user)
        self.assertEqual(user["connection_id"], connection["id"])

    def test_secret_storage_and_link(self):
        profile_path = str(self.root / "reality.json")
        output = "PrivateKey: " + "a"*43 + "\nPassword: " + "b"*43 + "\n"
        fake = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch.object(reality.subprocess, "run", return_value=fake):
            profile = reality.ensure_profile("vless-reality-primary", "xray", profile_path)
        self.assertEqual(profile, reality.ensure_profile("vless-reality-primary", "xray", profile_path))
        self.assertEqual(stat.S_IMODE(Path(profile_path).stat().st_mode), 0o600)
        inbound = reality.server_inbound(self.item(), [{"id": "c" * 36, "flow": "xtls-rprx-vision"}], profile)
        self.assertEqual(inbound["streamSettings"]["security"], "reality")
        self.assertEqual(inbound["streamSettings"]["network"], "raw")
        self.assertEqual(inbound["streamSettings"]["realitySettings"]["privateKey"], profile["private_key"])
        link = reality.client_link("8b888888-8888-4888-8888-888888888888",
                                   "vpn.example.com", "test", self.item(), profile)
        uri = urlparse(link)
        options = parse_qs(uri.query)
        self.assertEqual(options["pbk"][0], profile["public_key"])
        self.assertEqual(options["sid"][0], profile["short_id"])
        self.assertEqual(options["flow"][0], "xtls-rprx-vision")
        self.assertEqual(options["sni"][0], "www.microsoft.com")
        outbound = routing._vless_outbound(link)
        self.assertEqual(outbound["streamSettings"]["security"], "reality")
        self.assertEqual(outbound["settings"]["vnext"][0]["users"][0]["flow"], "xtls-rprx-vision")

    def test_xray_26_decorated_password_key(self):
        profile_path = str(self.root / "reality-26.json")
        output = ("PrivateKey: " + "a"*43 +
                  "\\nPassword (PublicKey): " + "b"*43 +
                  "\\nHash32: " + "c"*43 + "\\n")
        # This is the label used by the pinned Xray 26.x binary.
        output = output.replace("\\n", "\n")
        fake = SimpleNamespace(returncode=0, stdout=output, stderr="")
        with patch.object(reality.subprocess, "run", return_value=fake):
            profile = reality.ensure_profile("vless-reality-primary", "xray", profile_path)
        self.assertEqual(profile["public_key"], "b"*43)

    def test_direct_server_address_override(self):
        item = self.item()
        item["config"]["address"] = "203.0.113.42"
        con.validate(item, existing=item)
        dummy = {"private_key": "a"*43, "public_key": "b"*43,
                 "short_id": "0123456789abcdef"}
        link = reality.client_link("8b888888-8888-4888-8888-888888888888",
                                   "vpn.example.com", "test", item, dummy)
        self.assertEqual(urlparse(link).hostname, "203.0.113.42")

    def test_invalid_profile_fail_closed(self):
        with self.assertRaises(reality.RealityError):
            reality.read_profile("vless-reality-primary", str(self.root / "missing.json"))
        with self.assertRaises(reality.RealityError):
            reality.server_inbound(self.item(), [], {"private_key": "x"})


    def test_sni_preset_choices_and_manual_address(self):
        import wpp_ui as ui
        candidates = (
            "www.microsoft.com", "www.apple.com", "www.google.com",
            "www.amazon.com", "www.wikipedia.org",
        )
        markup = ui.connections_ui([self.item()], [], "/panel-test", "csrf")
        self.assertIn('name="reality_preset"', markup)
        self.assertIn('name="reality_sni"', markup)
        self.assertIn('value="custom"', markup)
        for hostname in candidates:
            self.assertIn('<option value="' + hostname + '">', markup)
            raw = self.item()
            raw["config"]["sni"] = hostname
            normalized = con.validate(raw, existing=raw)
            self.assertEqual(normalized["config"]["sni"], hostname)
        raw = self.item()
        raw["config"]["sni"] = "example.org"
        raw["config"]["address"] = "203.0.113.10"
        normalized = con.validate(raw, existing=raw)
        self.assertEqual(normalized["config"]["address"], "203.0.113.10")
        profile = {
            "private_key": "a" * 43,
            "public_key": "b" * 43,
            "short_id": "0123456789abcdef",
        }
        link = reality.client_link("8b888888-8888-4888-8888-888888888888",
                                   "panel.example.net", "test", normalized, profile)
        self.assertEqual(urlparse(link).hostname, "203.0.113.10")
        self.assertEqual(parse_qs(urlparse(link).query)["sni"][0], "example.org")


if __name__ == "__main__":
    unittest.main()
