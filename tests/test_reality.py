"""VLESS REALITY opt-in and backward compatibility tests."""
import json
import stat
import tempfile
import unittest
from pathlib import Path
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
        xray = self.root / "xray"
        xray.write_text("#!/bin/sh\\nprintf 'PrivateKey: %s\\\\nPassword: %s\\\\n' \\n  'a'$(printf '%042d' 0) 'b'$(printf '%042d' 0)\\n", encoding="utf-8")
        xray.chmod(0o700)
        # No real Xray is needed: only the keypair output format is stubbed.
        profile_path = str(self.root / "reality.json")
        profile = reality.ensure_profile("vless-reality-primary", str(xray), profile_path)
        self.assertEqual(profile, reality.ensure_profile("vless-reality-primary", str(xray), profile_path))
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

    def test_invalid_profile_fail_closed(self):
        with self.assertRaises(reality.RealityError):
            reality.read_profile("vless-reality-primary", str(self.root / "missing.json"))
        with self.assertRaises(reality.RealityError):
            reality.server_inbound(self.item(), [], {"private_key": "x"})


if __name__ == "__main__":
    unittest.main()
