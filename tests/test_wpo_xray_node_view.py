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
            raw=view.view(path,reveal=True,
                          reality_profile={"port":9443,"address":"poland.example.com",
                                           "sni":"www.nvidia.com"})
            self.assertEqual(raw["meta"]["reality_tcp"],9443)
            self.assertEqual(raw["meta"]["hysteria_udp"],[8443])
            self.assertEqual(raw["meta"]["address"],"poland.example.com")
            self.assertEqual(raw["meta"]["sni"],"www.nvidia.com")
            self.assertEqual(raw["config"],original)
            self.assertEqual(json.loads(path.read_text()),original)

    def test_detect_both_live_protocols(self):
        self.assertEqual(view.protocol_status(self.config),{"reality":True,"hysteria":True})

    @staticmethod
    def routing(reality=0,hysteria=0):
        return {"reality":{"count":reality,"total":7,"custom":False,"found":True},
                "hysteria":{"count":hysteria,"total":7,"custom":False,"found":True}}

    def test_status_per_mode_and_all_seven_flags(self):
        whole=self.routing(reality=7,hysteria=0)
        self.assertEqual(ui.display("reality",whole)[0],"on")
        self.assertEqual(ui.display("both",whole)[0],"on")
        self.assertEqual(ui.display("hysteria",whole)[0],"off")
        self.assertEqual(ui.display("both",self.routing(reality=3))[0],"partial")
        self.assertEqual(ui.display("both",self.routing())[0],"off")

    def test_saved_routing_counts_seven_switches(self):
        flags=list(ui.wpp_routing.ROUTING_FLAGS)
        self.assertEqual(len(flags),7)
        connection={"id":"reality-primary","protocol":"reality","enabled":True}
        for count in (0,3,7):
            stored={key:i<count for i,key in enumerate(flags)}
            stored["enabled"]=True
            with self.subTest(count=count), patch.object(ui.wpp_connections,"load",
                     return_value={"connections":[connection]}), patch.object(
                     ui.wpp_routing,"load",return_value={"profiles":{"reality-primary":stored}}):
                result=ui.routing_flags()
                self.assertEqual(result["reality"]["count"],count)
                self.assertEqual(ui.display("both",result)[0],
                                 "off" if count==0 else "on" if count==7 else "partial")

    def test_card_and_popup_inside_configuration_selector(self):
        local='<div class="wpo-xray-mode-card"><button type="button" data-wpo-xray-mode-open="local">Конфигурация Xray</button></div>'
        remote='<div class="wpo-xray-mode-card"><button type="button" data-wpo-xray-mode-open="0123456789abcdef">Конфигурация Xray</button></div>'
        chooser=('<dialog id="wpoXrayModeDialog"><form>'
                 '<input type="hidden" name="id" value="local">'
                 '<select name="mode"><option value="both">REALITY + Hysteria2</option>'
                 '</select></label></form></dialog>')
        with patch.object(ui,"routing_flags",return_value=self.routing(7,0)):
            html=ui.attach(local+remote+chooser,[{"id":"0123456789abcdef",
                        "name":"Poland","xray_mode":"reality"}],"/panel-abc","csrf123")
        self.assertNotIn('data-wpo-xray-code-open=',html)
        self.assertEqual(html.count('data-wpo-xray-config-preview'),2)
        self.assertEqual(html.count('wpo-xray-route-dot on'),2)
        self.assertIn("JSON · Маршрутизация включена",html)
        self.assertIn("Просмотр конфигурации Xray",html)
        self.assertIn("/panel-abc/node-xray-view",html)
        self.assertIn("Показать ключи",html)
        self.assertIn("readonly spellcheck",html)
        self.assertNotIn("private-value",html)


if __name__=="__main__":
    unittest.main()
