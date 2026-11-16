"""REALITY NVIDIA default and primary node edit icon layout regression."""
import unittest
from pathlib import Path
from unittest.mock import patch
import wpo_reality as reality
import wpo_reality_ui as ui

ROOT=Path(__file__).resolve().parents[1]

def profile(**updates):
    return dict(reality.DEFAULT, address="203.0.113.18",
                public_key="a"*43, short_id="0123456789abcdef",**updates)

class RealityNvidiaNodePencilTests(unittest.TestCase):
    def test_new_installation_defaults_to_nvidia_and_no_microsoft_preset(self):
        self.assertEqual(reality.DEFAULT["preset"],"nvidia")
        self.assertEqual(reality.DEFAULT["sni"],"www.nvidia.com")
        self.assertEqual(next(iter(reality.PRESETS)),"nvidia")
        self.assertNotIn("microsoft",reality.PRESETS)
        self.assertNotIn("www.microsoft.com",[x[1] for x in reality.PRESETS.values()])
        self.assertEqual(reality.normalize({})["sni"],"www.nvidia.com")
        self.assertIn("www.nvidia.com",reality.haproxy_config("www.nvidia.com"))

    def test_main_and_remote_installers_share_the_default_reality_module(self):
        main=(ROOT/"installers/install-reality.sh").read_text()
        node=(ROOT/"nodes/wpo-node-reality-enable.sh").read_text()
        self.assertIn("wpo_reality.py",main)
        self.assertIn("wpo_reality.py",node)
        self.assertIn("r.initialize(",main)
        self.assertIn("r.initialize(",node)

    def test_existing_unknown_preset_remains_custom_without_overwrite(self):
        legacy={"preset":"microsoft","sni":"www.microsoft.com"}
        self.assertEqual(ui.selected_preset(legacy),"custom")
        self.assertEqual(ui.selected_preset({"preset":"custom","sni":"www.nvidia.com"}),"nvidia")
        with patch.object(ui.reality,"read_profile",return_value=dict(profile(),**legacy)):
            html=ui.editor("/panel","csrf")
        self.assertIn('<option value="custom" selected>',html)
        self.assertIn('name="sni" value="www.microsoft.com"',html)

    def test_dialog_has_no_microsoft_preset_or_brand_label(self):
        with patch.object(ui.reality,"read_profile",return_value=profile()):
            html=ui.editor("/panel","csrf")
        self.assertIn('<option value="nvidia" selected>',html)
        self.assertNotIn("Microsoft",html)
        self.assertNotIn("www.microsoft.com",html)
        self.assertIn("Edge · проверить в клиенте",html)

    def test_primary_pencil_shares_bottom_right_action_row(self):
        def cards(*args,**kwargs):
            return ('<section class="wpo-nodes-page">'
                    '<article class="card wpo-node-card">'
                    '<div class="wpo-node-card-body">'
                    '<div class="wpo-node-meta-row">'
                    '<p class="wpo-node-template wpo-main-node-label">Основная нода</p>'
                    '</div></div></article>'
                    '<article class="card wpo-node-card">'
                    '<div class="wpo-node-meta-row">'
                    '<div class="wpo-node-actions">[EDIT][DELETE]</div>'
                    '</div></article></section>')
        ns={"nodes_ui":cards,"connections_ui":lambda *a,**k:"",
            "icon":lambda name:"<svg>edit</svg>"}
        ui.install(ns)
        with patch.object(ui.reality,"read_profile",return_value=profile()):
            html=ns["nodes_ui"]([],{},"node.example.com","/panel","csrf")
        primary=html.split("</article>",1)[0]
        self.assertEqual(html.count("data-reality-open"),1)
        self.assertIn('<div class="wpo-node-actions"><button type="button" class="icon-btn wpo-node-icon" data-reality-open',primary)
        self.assertLess(primary.index("wpo-main-node-label"),primary.index("data-reality-open"))
        self.assertIn('title="Настройки REALITY"',primary)
        self.assertEqual(primary.count('class="wpo-node-meta-row"'),1)
        self.assertIn("[EDIT][DELETE]",html)
        self.assertEqual(html.count("</article>"),2)

    def test_no_pencil_added_outside_card_when_layout_mismatch(self):
        ns={"nodes_ui":lambda *a,**k:'<article class="wpo-node-card"></article>',
            "connections_ui":lambda *a,**k:"",
            "icon":lambda name:"edit"}
        ui.install(ns)
        with self.assertRaisesRegex(RuntimeError,"основная карточка изменилась"):
            ns["nodes_ui"]([],{},"node.example.com","/panel","csrf")

if __name__=="__main__":
    unittest.main()
