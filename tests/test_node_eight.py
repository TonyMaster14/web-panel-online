"""WPO eight-engine federation test: true backend provisioning with no fake links."""
from pathlib import Path
import copy
import json
import os
import tempfile
import unittest
from unittest import mock

import wpo_node_eight as engine
import wpo_node_vpn as xray


ROOT = Path(__file__).resolve().parents[1]


class EightEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wpo-eight-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module, attr, path in (
                (xray, "STATE", self.root/"state.json"),
                (xray, "SETTINGS", self.root/"settings.json"),
                (xray, "LOCK", self.root/".lock"),
                (engine, "STATE", self.root/"state.json"),
                (engine, "SETTINGS", self.root/"settings.json")):
            patcher = mock.patch.object(module, attr, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        xray.SETTINGS.write_text(json.dumps({
            "domain":"se.example.net", "xhttp_path":"/wpo-xhttp-1234567890abcdef12345678"
        }))
        self.cap = mock.patch.object(engine, "available", return_value=engine.KNOWN)
        self.cap.start()
        self.addCleanup(self.cap.stop)
        self.awg = mock.patch.object(engine.awg, "new_user", side_effect=self.fake_awg)
        self.awg.start();self.addCleanup(self.awg.stop)
        xp = mock.patch.object(xray, "apply")
        self.fake_xray=xp.start();self.addCleanup(xp.stop)
        np = mock.patch.object(engine,"native_apply")
        self.fake_native=np.start();self.addCleanup(np.stop)

    @staticmethod
    def fake_awg(protocol, existing_users, uid):
        return {
            "secret":"privatekey", "server_public_key":"serverpub",
            "backend_port":52000+len(existing_users), "awg_network":"10.80.1.0/30",
            "public_key":"clientpub","preshared_key":"psk",
            "server_private_key":"serverpriv","address":"10.80.1.2/32",
            "server_address":"10.80.1.1/30",
            "awg_interface":"wa"+uid[:11],
            "awg_parameters":{},"awg_schema":2
        }

    def test_eight_protocols_are_unique(self):
        self.assertEqual(len(engine.KNOWN),8)
        self.assertEqual(set(engine.KNOWN),{"vless","hysteria","web","mtproto",
                                            "awg20","awg31","naive","mieru"})
        self.assertEqual(engine.available(),engine.KNOWN)

    def test_one_node_eight_profiles_return_native_configs_and_links(self):
        with mock.patch.object(engine.awg,"client_config",side_effect=lambda u,d,n:"[Interface]\nPrivateKey=xyz") as cfg:
            result=engine.sync({"external_id":"a"*64,"name":"Швеция",
                                "protocols":list(engine.PROTOCOLS_ORDER)})
        self.assertTrue(result["ok"])
        self.assertEqual([x["protocol"] for x in result["profiles"]],
                         list(engine.PROTOCOLS_ORDER))
        links={x["protocol"]:x for x in result["profiles"]}
        self.assertEqual(len(links),8)
        self.assertTrue(links["vless"]["link"].startswith("vless://"))
        self.assertTrue(links["hysteria"]["link"].startswith("hysteria2://"))
        self.assertTrue(links["web"]["link"].startswith("https://t.me/webproxy?"))
        self.assertTrue(links["mtproto"]["link"].startswith("https://t.me/proxy?"))
        self.assertEqual(links["awg20"]["config"],"[Interface]\nPrivateKey=xyz")
        self.assertEqual(links["awg31"]["config"],"[Interface]\nPrivateKey=xyz")
        self.assertTrue(links["naive"]["link"].startswith("naive+https://"))
        self.assertTrue(links["mieru"]["link"].startswith("mieru://"))
        self.assertEqual(cfg.call_count,2)
        self.fake_xray.assert_called_once()
        self.fake_native.assert_called_once()
        state=xray.read_json(xray.STATE)["profiles"]
        self.assertEqual(len(state["a"*64]["native"]),6)

    def test_idempotent_sync_does_not_rotate_keys_or_restart_services(self):
        data={"external_id":"b"*64,"name":"Sweden",
              "protocols":["vless","hysteria","web","mtproto","naive","mieru"]}
        first=engine.sync(data)
        second=engine.sync(data)
        self.assertEqual(first,second)
        self.assertEqual(self.fake_xray.call_count,1)
        self.assertEqual(self.fake_native.call_count,1)

    def test_delete_removes_all_real_units_and_registry_secrets(self):
        data={"external_id":"c"*64,"name":"Sweden",
              "protocols":["vless","mtproto","web"]}
        engine.sync(data)
        removed=engine.remove({"external_id":"c"*64})
        self.assertEqual(removed,{"ok":True,"deleted":True})
        self.assertEqual(xray.read_json(xray.STATE)["profiles"],{})
        self.assertEqual(self.fake_native.call_count,2)

    def test_does_not_persist_failed_native_apply(self):
        self.fake_native.side_effect=[RuntimeError("Mieru down"),None]
        with self.assertRaisesRegex(RuntimeError,"Mieru"):
            engine.sync({"external_id":"d"*64,"name":"Failure","protocols":["mieru"]})
        self.assertFalse(xray.STATE.exists())
        self.assertEqual(self.fake_native.call_count,2)

    def test_uninstalled_protocol_is_rejected_without_broken_link(self):
        with mock.patch.object(engine,"available",return_value=frozenset({"vless","hysteria"})):
            with self.assertRaisesRegex(RuntimeError,"not ready"):
                engine.sync({"external_id":"e"*64,"name":"Offline","protocols":["awg20"]})
        self.assertFalse(xray.STATE.exists())

    def test_inputs_reject_unsupported_and_duplicate_protocols(self):
        for values in (["foo"],["vless","vless"],[],[None],["vless"]*9):
            with self.subTest(protocols=values),self.assertRaises(ValueError):
                engine.validate({"external_id":"f"*64,"name":"Test","protocols":values})

    def test_telegram_unit_uses_real_binary_and_secrets_not_shell(self):
        record=engine.build_profile("f"*64,"mtproto",None)
        unit=engine._mt_unit(record)
        self.assertIn("/opt/MTProxy/objs/bin/mtproto-proxy",unit)
        self.assertIn(" -S ",unit)
        self.assertIn(" -H ",unit)
        self.assertNotIn("bash -c",unit)

    def test_web_relay_has_valid_private_bootstrap_profile_without_users(self):
        install=(ROOT/"wpo-node-eight-enable.sh").read_text()
        engine_src=(ROOT/"wpo_node_eight.py").read_text()
        self.assertIn("relay-bootstrap-secret",install)
        self.assertIn("'name':'node-bootstrap'",install)
        self.assertIn('"name": "node-bootstrap"',engine_src)
        self.assertIn('if not relay_profiles:',engine_src)
        self.assertIn('os.chmod(RELAY_CONFIG, 0o400)',engine_src)

    def test_telegram_profiles_keep_secret_out_of_public_systemd_units(self):
        record=engine.build_profile("f"*64,"web",None)
        unit=engine._mt_unit(record)
        self.assertIn("WPO_MTPROTO_SECRET",unit)
        self.assertIn("EnvironmentFile=/etc/wpp-node-vpn/",unit)
        self.assertNotIn(record["secret"],unit)
        self.assertIn("User=mtproxy",unit)
        self.assertIn("wpo-node-mt-firewall.service",unit)
        firewall=(ROOT/"wpo-node-eight-enable.sh").read_text()
        self.assertIn("tcp dport 24000-24949 drop",firewall)
        self.assertIn("tcp dport 27000-28949 drop",firewall)

    def test_installer_contains_all_pinned_real_backends_and_auto_registers(self):
        installer=(ROOT/"wpo-node-eight-enable.sh").read_text()
        agent=(ROOT/"wpo-node-agent-install-v2.sh").read_text()
        core=(ROOT/"node-install.sh").read_text()
        for needed in ("mtproto-proxy","tproxy-server","amneziawg-go","awg-quick",
                       "caddy-naive","mita-wpp","wpo_node_eight.py"):
            self.assertIn(needed,installer)
        self.assertIn("wpo-node-eight-enable.sh",agent)
        self.assertIn("WPO_NODE_VPN_REF='test/wpo-smooth-progress-v1' bash \"$EIGHT_SETUP\"",agent)
        self.assertIn("wpo-node-agent-install-v2.sh",core)
        self.assertIn("systemctl is-active --quiet wpo-node-relay.service",installer)


if __name__=="__main__":
    unittest.main()
