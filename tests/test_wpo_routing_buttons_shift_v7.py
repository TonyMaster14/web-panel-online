"""WPO routing footer nudged 6px right; visuals only and safe to repeat."""
import ast
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import wpp_ui

spec=importlib.util.spec_from_file_location(
    "routing_shift_v7",ROOT/"maintenance/routing/wpo-routing-buttons-shift-v7-patch.py")
patch=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

class RoutingShiftV7Tests(unittest.TestCase):
    def test_two_buttons_shift_right_without_changing_behavior(self):
        ui=wpp_ui.routing_ui([
            {"id":"vless","protocol":"vless","name":"VLESS","enabled":True},
            {"id":"hyst","protocol":"hysteria","name":"Hysteria2","enabled":True}],
            {"profiles":{"vless":{"enabled":True,"ru_direct":True}}},
            "/panel-demo","csrf")
        self.assertIn(patch.NEW,ui)
        self.assertNotIn(patch.OLD,ui)
        self.assertIn("gap:12px;min-height:76px;padding:14px 12px 14px 18px",ui)
        self.assertIn("flex-direction:column;align-items:stretch",ui)
        self.assertIn("transform:translateY(-2px)",ui)
        self.assertIn("background:#2563eb",ui)
        self.assertIn("background:#c9364f",ui)
        self.assertIn("name=\"operation\" value=\"add-selected\"",ui)
        self.assertIn("name=\"operation\" value=\"remove-selected\"",ui)

    def test_patch_idempotent_and_rejects_unknown_layout(self):
        original=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        ast.parse(original)
        self.assertEqual(patch.patch(original),original)
        with self.assertRaises(ValueError):
            patch.patch("def unrelated():pass\n")

if __name__=="__main__":
    unittest.main()
