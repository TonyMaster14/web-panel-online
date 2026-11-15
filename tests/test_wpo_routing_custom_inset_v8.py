"""Visual and safety regression coverage for inset Custom Exceptions card."""
import ast
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import wpp_ui

spec=importlib.util.spec_from_file_location(
    "routing_custom_inset_v8", ROOT/"maintenance/routing/wpo-routing-custom-inset-v8-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

class RoutingCustomInsetV8(unittest.TestCase):
    @staticmethod
    def page():
        return wpp_ui.routing_ui([
            {"id":"vless","name":"VLESS XHTTP","protocol":"vless","enabled":True},
            {"id":"hyst","name":"Hysteria2","protocol":"hysteria","enabled":True},
            {"id":"awg20","name":"AmneziaWG 2.0","protocol":"awg20","enabled":True}
        ],{"profiles":{"vless":{"enabled":True,"ru_direct":True}}},"/panel-test","csrf")

    def test_inset_border_and_alignment(self):
        html=self.page()
        self.assertIn(patcher.MARKER,html)
        self.assertIn('margin:16px 16px 16px 0',html)
        self.assertIn('padding:17px 16px',html)
        self.assertIn('border-radius:13px',html)
        self.assertIn('.routing-form .routing-layout .routing-custom',html)
        self.assertIn('border:1px solid var(--line)',html)
        self.assertIn('margin:0 16px 16px',html)
        self.assertIn('margin:0 12px 12px',html)
        self.assertIn('box-sizing:border-box;max-width:100%',html)
        self.assertEqual(html.count('<aside class="routing-custom"><h2>Свои исключения</h2>'),2)

    def test_domains_state_actions_are_unchanged(self):
        html=self.page()
        for field in ('direct_domains_delta','proxy_domains_delta','select_ru_direct'):
            self.assertIn('name="'+field+'"',html)
        for action in ('add-selected','remove-selected'):
            self.assertEqual(html.count('name="operation" value="'+action+'"'),2)
        self.assertEqual(html.count('class="routing-actions-primary"'),2)
        self.assertEqual(html.count('class="routing-actions-secondary"'),2)
        self.assertIn('routing-buttons-shift-v7',html)
        self.assertIn('routing-protocol-status',html)
        self.assertIn('data-awg-form="1"',html)

    def test_patch_idempotent_unknown_version_refused(self):
        source=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertEqual(patcher.patch(source),source)
        self.assertEqual(source.count(patcher.MARKER),1)
        with self.assertRaises(ValueError):
            patcher.patch("def unrelated():pass\n")

if __name__=="__main__":
    unittest.main()
