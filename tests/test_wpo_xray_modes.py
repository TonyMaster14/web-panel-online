"""Offline tests for three per-node Xray choices in WPO V27."""
import json
from pathlib import Path
import tempfile
import unittest

import wpo_xray_modes as modes
import wpo_xray_modes_ui as ui


class TestMode(unittest.TestCase):
    def _config(self):
        return {"api":{"tag":"api"},
                "inbounds":[
                    {"tag":"vless-reality","protocol":"vless",
                     "settings":{"clients":[]},
                     "streamSettings":{"network":"tcp","security":"reality",
                                       "realitySettings":{"show":False}}},
                    {"tag":"hysteria2","protocol":"hysteria",
                     "settings":{"clients":[]},
                     "streamSettings":{"network":"hysteria","security":"tls"}},
                    {"tag":"vless-xhttp","protocol":"vless",
                     "streamSettings":{"network":"xhttp","security":"none"}},
                ],
                "outbounds":[{"tag":"direct","protocol":"freedom"}]}

    def test_three_modes(self):
        self.assertEqual(set(modes.MODES), {"both","reality","hysteria"})
        self.assertFalse(any("шаблон" in v.lower() for v in modes.MODES.values()))
        for mode, expected in (
            ("both",["vless-reality","hysteria2","vless-xhttp"]),
            ("reality",["vless-reality","vless-xhttp"]),
            ("hysteria",["hysteria2","vless-xhttp"])):
            with self.subTest(mode=mode):
                cfg=modes.tune_config(self._config(),mode)
                self.assertEqual([x["tag"] for x in cfg["inbounds"]], expected)
                self.assertEqual(cfg["outbounds"],self._config()["outbounds"])
        reality=modes.tune_config(self._config(),"reality")["inbounds"][0]
        self.assertEqual(reality["streamSettings"]["realitySettings"]["minClientVer"],"1.0.0")
        hysteria=modes.tune_config(self._config(),"hysteria")["inbounds"][0]
        self.assertEqual(hysteria["streamSettings"]["finalmask"]["quicParams"]["congestion"],"bbr")

    def test_no_drop_of_existing_clients(self):
        value=self._config()
        value["inbounds"][1]["settings"]["clients"]=[{"auth":"uuid"}]
        with self.assertRaisesRegex(ValueError,"пользователи Hysteria2"):
            modes.refuse_live_drop("reality",value)

    def test_rollback_on_failed_sync(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"mode.json"
            def broken():
                raise RuntimeError("Xray failed")
            with self.assertRaises(RuntimeError):
                modes.switch(path,"reality",self._config(),broken)
            self.assertEqual(modes.get(path),"both")
            events=[]
            result=modes.switch(path,"hysteria",self._config(),lambda:events.append("ok"))
            self.assertTrue(result["ok"])
            self.assertEqual(modes.get(path),"hysteria")
            self.assertEqual(events,["ok"])

    def test_node_specific_happ_filter(self):
        self.assertEqual(modes.select_for_node({"xray_mode":"hysteria"},
                                                ("reality","hysteria","vless")),
                         ("hysteria","vless"))
        self.assertEqual(modes.select_for_node({"xray_mode":"reality"},
                                                ("reality","hysteria")),
                         ("reality",))

    def test_compact_node_ui(self):
        rows=[
            '<article class="card wpo-node-card"><div class="wpo-node-card-head">'
            'main</div><div class="wpo-node-card-bottom">actions</div></article>',
            '<article class="card wpo-node-card"><div class="wpo-node-card-head">'
            'remote <button data-node-edit="0123456789abcdef">edit</button></div>'
            '<div class="wpo-node-card-bottom">actions</div></article>',
            '<article class="card wpo-node-card wpo-pending-node">pending</article>'
        ]
        html=ui.attach("".join(rows),[{"id":"0123456789abcdef",
                                       "name":"Finland","xray_mode":"reality"}],
                       "/panel-test","csrf")
        self.assertEqual(html.count('data-wpo-xray-mode-open='),2)
        self.assertIn('<option value="both">REALITY + Hysteria2</option>',html)
        self.assertIn('<option value="reality">REALITY</option>',html)
        self.assertIn('<option value="hysteria">Hysteria2</option>',html)
        self.assertNotIn('>Шаблон<',html)


if __name__=="__main__":
    unittest.main()
