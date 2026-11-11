"""Regression tests for the optional VLESS TCP Reality + Vision route."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import wpp_reality
import wpp_routing
import wpp_connections
import wpp_cdn
import wpp_subscriptions

KEY_PRIVATE = "A" * 43
KEY_PUBLIC = "B" * 43


class RealityTests(unittest.TestCase):
    def test_x25519_formats(self):
        examples = [
            f"Private key: {KEY_PRIVATE}\nPublic key: {KEY_PUBLIC}\n",
            f"PrivateKey: {KEY_PRIVATE}\nPassword: {KEY_PUBLIC}\nHash32: xyz\n",
            f"PrivateKey: {KEY_PRIVATE}\nPassword (PublicKey): {KEY_PUBLIC}\n",
        ]
        for example in examples:
            with self.subTest(format=example.splitlines()[1].split(":")[0]):
                self.assertEqual(wpp_reality._parse_keys(example), (KEY_PRIVATE, KEY_PUBLIC))

    def test_invalid_key_rejected(self):
        with self.assertRaises(RuntimeError):
            wpp_reality._parse_keys("PrivateKey: broken\nPassword: invalid\n")

    def test_credentials_atomic_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = os.path.join(tmp, "reality.json")
            response = Mock(stdout=f"PrivateKey: {KEY_PRIVATE}\nPassword: {KEY_PUBLIC}\n")
            with patch("wpp_reality.subprocess.run", return_value=response) as runner:
                original = wpp_reality.load_or_create("/usr/bin/xray", file)
                self.assertEqual(original["private_key"], KEY_PRIVATE)
                self.assertEqual(original["public_key"], KEY_PUBLIC)
                self.assertEqual(len(original["short_id"]), 16)
                self.assertEqual(stat.S_IMODE(Path(file).stat().st_mode), 0o600)
                self.assertEqual(original, wpp_reality.load_or_create("/usr/bin/xray", file))
                self.assertEqual(runner.call_count, 1)

    def test_reality_uri_and_xray_outbound(self):
        config = dict(private_key=KEY_PRIVATE, public_key=KEY_PUBLIC,
                      short_id="0123456789abcdef", port=8444,
                      target="www.microsoft.com:443", server_name="www.microsoft.com")
        uuid = "8aee6613-a0d1-4f2b-a8be-a767d65870d6"
        link = wpp_reality.client_link(uuid, "vpn.example.com", "🇨🇿 Чехия", config)
        parsed = urlsplit(link)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.port, 8444)
        self.assertEqual(params["flow"], ["xtls-rprx-vision"])
        self.assertEqual(params["pbk"], [KEY_PUBLIC])
        self.assertNotIn(KEY_PRIVATE, link)
        self.assertEqual(params["type"], ["tcp"])
        outbound = wpp_routing._vless_outbound(link)
        self.assertEqual(outbound["streamSettings"]["security"], "reality")
        self.assertEqual(outbound["streamSettings"]["network"], "tcp")
        self.assertEqual(outbound["streamSettings"]["realitySettings"]["password"], KEY_PUBLIC)
        self.assertEqual(outbound["settings"]["vnext"][0]["users"][0]["flow"], "xtls-rprx-vision")
        server = wpp_reality.inbound([{"id": uuid, "email": "panel:test:1"}], config)
        self.assertEqual(server["streamSettings"]["realitySettings"]["privateKey"], KEY_PRIVATE)
        self.assertEqual(server["settings"]["clients"][0]["flow"], "xtls-rprx-vision")

    def test_subscription_and_failover(self):
        config = dict(private_key=KEY_PRIVATE, public_key=KEY_PUBLIC,
                      short_id="0123456789abcdef", port=8444,
                      target="www.microsoft.com:443", server_name="www.microsoft.com")
        uuid = "8aee6613-a0d1-4f2b-a8be-a767d65870d6"
        reality_link = wpp_reality.client_link(uuid, "vpn.example.com", "🇨🇿 Чехия", config)
        xhttp_link = ("vless://" + uuid + "@vpn.example.com:443?encryption=none"
                      "&security=tls&type=xhttp&path=%2Ftest&host=vpn.example.com#XHTTP")
        sub = {
            "id": "account123", "name": "Fenix VPN", "enabled": True,
            "max_devices": 0, "profile_ids": [],
            "connections": [{"id": "vless-reality", "name": "Reality", "protocol": "vless"}],
            "protocols": ["vless"], "devices": [],
        }
        data = {"users": []}
        wpp_subscriptions.provision(data, sub, {"id": "device123", "name": "iPhone"})
        self.assertEqual(data["users"][0]["connection_id"], "vless-reality")
        self.assertEqual(data["users"][0]["protocol"], "vless")
        single = wpp_routing.plain_xray_config(reality_link, "Fenix VPN")
        self.assertEqual(single["remarks"], "Fenix VPN")
        self.assertEqual(single["outbounds"][0]["streamSettings"]["network"], "tcp")
        combined = wpp_routing.failover_xray_config([reality_link, xhttp_link], name="Fenix VPN")
        self.assertEqual(combined["remarks"], "Fenix VPN")
        self.assertEqual([x["streamSettings"]["network"] for x in combined["outbounds"][:2]],
                         ["tcp", "xhttp"])

    def test_original_xhttp_untouched(self):
        link = ("vless://8aee6613-a0d1-4f2b-a8be-a767d65870d6@vpn.example.com:443"
                "?encryption=none&security=tls&type=xhttp&path=%2Ftest&host=vpn.example.com"
                "&mode=auto&alpn=h2#%F0%9F%87%A8%F0%9F%87%BF")
        outbound = wpp_routing._vless_outbound(link)
        self.assertEqual(outbound["streamSettings"]["security"], "tls")
        self.assertEqual(outbound["streamSettings"]["network"], "xhttp")
        self.assertNotIn("flow", outbound["settings"]["vnext"][0]["users"][0])

    def test_connection_template_and_subscription(self):
        entries = {item["id"]: item for item in wpp_connections.defaults()}
        self.assertIn("vless-reality", entries)
        self.assertEqual(entries["vless-reality"]["config"]["route"], "reality")
        self.assertEqual(wpp_connections._xray_bucket(entries["vless-reality"]), "reality")
        self.assertEqual(wpp_connections.inbound_tag(entries["vless-reality"]), "vless-reality")
        self.assertEqual(wpp_connections._xray_bucket(entries["vless-direct"]), "direct")
        self.assertIsNone(wpp_cdn.profile_from_request({"vless_route": "reality"}))
        self.assertEqual(wpp_connections.subscription_spec(entries["vless-reality"])["protocol"], "vless")


if __name__ == "__main__":
    unittest.main()
