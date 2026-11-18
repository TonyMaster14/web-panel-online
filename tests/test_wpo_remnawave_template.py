"""Unit tests for the credential-free RemnaWave REALITY/Hysteria2 templates."""
import copy
import unittest

import wpo_remnawave_template as rm


class RemnaWaveTemplateTests(unittest.TestCase):
    def setUp(self):
        self.r_clients = [{
            "id": "11111111-1111-4111-8111-111111111111",
            "email": "node:test", "level": 0, "flow": "xtls-rprx-vision",
        }]
        self.h_clients = [{"auth": "11111111-1111-4111-8111-111111111111"}]

    def test_only_reality_and_hysteria_with_real_protocol_settings(self):
        reality = rm.reality_inbound(
            node_domain="node.example.com", private_key="A"*43,
            short_id="0123456789abcdef", clients=self.r_clients,
            fallback_socket="/run/wpo-reality-fallback.sock"
        )
        hysteria = rm.hysteria_inbound(
            cert_path="/etc/wpo/tls/cert.pem", key_path="/etc/wpo/tls/key.pem",
            clients=self.h_clients
        )
        doc = rm.remnawave_server_reference(reality, hysteria)
        self.assertEqual(len(doc["inbounds"]), 2)
        self.assertEqual([x["protocol"] for x in doc["inbounds"]], ["vless", "hysteria"])
        self.assertEqual(reality["port"], 19444)
        self.assertEqual(reality["listen"], "127.0.0.1")
        self.assertEqual(reality["streamSettings"]["network"], "tcp")
        self.assertEqual(reality["streamSettings"]["security"], "reality")
        rs = reality["streamSettings"]["realitySettings"]
        self.assertEqual(rs["minClientVer"], "1.0.0")
        self.assertEqual(rs["xver"], 1)
        self.assertEqual(rs["serverNames"], ["node.example.com"])
        self.assertEqual(hysteria["port"], 443)
        self.assertEqual(hysteria["streamSettings"]["finalmask"]["quicParams"]["congestion"], "bbr")
        self.assertEqual(hysteria["streamSettings"]["tlsSettings"]["alpn"], ["h3"])
        self.assertEqual(doc["dns"]["queryStrategy"], "UseIPv4")
        self.assertEqual(len(doc["routing"]["rules"]), 2)
        self.assertNotIn("grpc", repr(doc))
        self.assertNotIn("xhttp", repr(doc))

    def test_user_credentials_and_templates_are_not_shared_between_nodes(self):
        copy_clients = copy.deepcopy(self.r_clients)
        r1 = rm.reality_inbound(
            node_domain="a.example.com", private_key="A"*43,
            short_id="1111111111111111", clients=self.r_clients,
            fallback_socket="/run/wpo-reality-fallback.sock")
        r2 = rm.reality_inbound(
            node_domain="b.example.com", private_key="B"*43,
            short_id="2222222222222222", clients=self.r_clients,
            fallback_socket="/run/wpo-reality-fallback.sock")
        self.assertNotEqual(r1["streamSettings"]["realitySettings"]["privateKey"],
                            r2["streamSettings"]["realitySettings"]["privateKey"])
        self.assertNotEqual(r1["streamSettings"]["realitySettings"]["serverNames"],
                            r2["streamSettings"]["realitySettings"]["serverNames"])
        r1["settings"]["clients"].clear()
        self.assertEqual(self.r_clients, copy_clients)

    def test_rejects_invalid_private_key_host_and_ports(self):
        args = dict(node_domain="node.example.com", private_key="A"*43,
                    short_id="1111111111111111", clients=self.r_clients,
                    fallback_socket="/run/wpo-reality-fallback.sock")
        for overrides in (
            {"port": 0}, {"port": 65536}, {"port": True},
            {"private_key": "REDACTED"},
            {"node_domain": "https://node.example.com"},
            {"fallback_socket": "www.example.com:443"},
            {"short_id": "not-hex"}
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                rm.reality_inbound(**(args | overrides))


if __name__ == "__main__":
    unittest.main()
