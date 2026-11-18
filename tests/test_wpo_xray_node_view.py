"""WPO V28 read-only per-node Xray inspector regression tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import wpo_xray_node_view as view
import wpo_xray_node_view_ui as ui


class NodeViewTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "log":{"loglevel":"warning"},
            "inbounds":[
                {"tag":"vless-reality","protocol":"vless",
                 "settings":{"clients":[{"id":"user-uuid","flow":"xtls-rprx-vision"}]},
                 "streamSettings":{"network":"tcp","security":"reality",
                   "realitySettings":{"privateKey":"private-value",
                      "shortIds":["ab12"],"serverNames":["node.example.com"]}}},
                {"tag":"hysteria2","protocol":"hysteria","port":8443,
                 "settings":{"clients":[{"auth":"hysteria-password"}]},
                 "streamSettings":{"network":"hysteria","security":"tls"}},
                {"tag":"vless-xhttp","protocol":"vless",
                 "streamSettings":{"network":"xhttp","security":"none"}}
            ],
            "outbounds":[{"tag":"direct","protocol":"freedom"}]}

    def test_redacted_read_only(self):
        original=copy.deepcopy(self.config)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"xray.json"
            path.write_text(json.dumps(self.config),encoding="utf-8")
            safe=view.view(path)
            self.assertTrue(safe["ok"])
            self.assertNotIn("private-value",json.dumps(safe))
            self.assertNotIn("user-uuid",json.dumps(safe))
            self.assertNotIn("hysteria-password",json.dumps(safe))
            self.assertIn("node.example.com",json.dumps(safe))
            self.assertEqual(safe["config"]["inbounds"][1]["port"],8443)
            raw=view.view(path,reveal=True)
            self.assertEqual(raw["config"],original)
            self.assertEqual(json.loads(path.read_text()),original)

    def test_detect_both_live_protocols(self):
        self.assertEqual(view.protocol_status(self.config),{"reality":True,"hysteria":True})

    def test_status_per_mode(self):
        status={"reality":True,"hysteria":False}
        self.assertEqual(ui.display("reality",status)[0],"on")
        self.assertEqual(ui.display("both",status)[0],"partial")
        self.assertEqual(ui.display("hysteria",status)[0],"off")

    def test_card_and_popup_with_authenticated_endpoint(self):
        local='<div class="wpo-xray-mode-card"><button type="button" data-wpo-xray-mode-open="local">Конфигурация Xray</button></div>'
        remote='<div class="wpo-xray-mode-card"><button type="button" data-wpo-xray-mode-open="0123456789abcdef">Конфигурация Xray</button></div>'
        with patch.object(ui,"routing_flags",return_value={"reality":True,"hysteria":False}):
            html=ui.attach(local+remote,[{"id":"0123456789abcdef","name":"Poland",
                         "xray_mode":"both"}],"/panel-abc","csrf123")
        self.assertEqual(html.count("data-wpo-xray-code-open="),2)
        self.assertIn("JSON · Маршрутизация включена",html)
        self.assertIn("JSON · Частично включена",html)
        self.assertIn("/panel-abc/node-xray-view",html)
        self.assertIn("Показать ключи",html)
        self.assertIn("readonly spellcheck",html)
        self.assertNotIn("private-value",html)


if __name__=="__main__":
    unittest.main()
