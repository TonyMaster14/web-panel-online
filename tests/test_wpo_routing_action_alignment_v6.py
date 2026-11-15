"""WPO routing v6 visuals: paired buttons and red removal-only dots."""
import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import wpp_ui
import wpp_routing

spec=importlib.util.spec_from_file_location(
    "wpo_routing_v6", ROOT/"wpo-routing-action-alignment-v6-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


def conns():
    return [
        {"id":"vless","name":"VLESS XHTTP","enabled":True,"protocol":"vless"},
        {"id":"hyst","name":"Hysteria2","enabled":True,"protocol":"hysteria"},
        {"id":"wg20","name":"AmneziaWG 2.0","enabled":True,"protocol":"awg20"},
        {"id":"wg31","name":"AmneziaWG 3.1","enabled":True,"protocol":"awg31"}
    ]


def render(state=None):
    return wpp_ui.routing_ui(conns(),state or {},"/panel-test","csrf")


class RoutingV6Tests(unittest.TestCase):
    def test_red_circle_replaces_blue_checkmark(self):
        page=render({"profiles":{
            "vless":{"enabled":True,"ru_direct":True},
            "hyst":{"enabled":True,"youtube_proxy":True}
        }})
        self.assertIn(patcher.MARKER,page)
        self.assertNotIn('content:"✓"',page)
        self.assertIn('label.routing-toggle.is-active:has(input:checked)::after',page)
        self.assertIn('right:14px;top:50%',page)
        self.assertIn('width:16px;height:16px',page)
        self.assertIn('border:1.5px solid #ef4444;border-radius:50%',page)
        self.assertIn('transform:translateY(-50%)',page)
        self.assertIn('radial-gradient(circle,#ef4444',page)
        self.assertIn('padding-right:38px',page)
        self.assertIn('class="routing-rule-dot"',page)
        self.assertIn('class="routing-toggle is-active"',page)
        self.assertIn('name="select_ru_direct" value="1"',page)
        self.assertIn('name="select_youtube_proxy" value="1"',page)
        # AWG's user-download workflow is not incorrectly represented as a
        # locally deletable routing toggle.
        self.assertIn('data-awg-form="1"',page)
        self.assertIn('Скачать JSON',page)
        self.assertEqual(page.count('class="routing-actions"'),2)

    def test_buttons_are_adjacent_in_single_right_aligned_footer(self):
        page=render()
        self.assertIn('.routing-form .routing-actions{',page)
        self.assertIn('display:flex;align-items:center;justify-content:flex-end',page)
        self.assertIn('gap:12px;min-height:76px;padding:14px 12px 14px 18px',page)
        self.assertIn('.routing-form .routing-actions-primary>.muted',page)
        self.assertIn('flex:0 0 auto;display:flex;align-items:center;justify-content:flex-end',page)
        self.assertNotIn('grid-template-columns:minmax(0,1.5fr) minmax(300px,.65fr);\n    align-items:stretch;gap:0;padding:0;min-height:76px',page)
        self.assertIn('background:#2563eb',page)
        self.assertIn('background:#c9364f',page)
        self.assertIn('transform:translateY(-2px)',page)
        self.assertIn('flex-direction:column;align-items:stretch;gap:10px',page)

    def test_same_backend_for_vless_hysteria_bulk_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/"routing.json")
            for cid in ("vless","hyst"):
                wpp_routing.update_selected(path,cid,{
                    "select_ru_direct":"1","select_youtube_proxy":"1",
                    "select_push_proxy":"1"})
            # Remove two of three per connection, preserving remaining saved.
            for cid in ("vless","hyst"):
                state=wpp_routing.update_selected(path,cid,{
                    "select_ru_direct":"1","select_youtube_proxy":"1"},
                    remove=True)
                self.assertTrue(state["push_proxy"])
                self.assertFalse(state["ru_direct"])
                self.assertFalse(state["youtube_proxy"])
            output=render(wpp_routing.load(path))
            self.assertEqual(output.count('class="routing-toggle is-active"'),2)
            self.assertIn('name="operation" value="remove-selected"',output)
            self.assertIn('name="operation" value="add-selected"',output)

    def test_exact_patch_idempotence_and_legacy_guard(self):
        source=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertEqual(source,patcher.patch(source))
        self.assertEqual(source.count(patcher.MARKER),1)
        with self.assertRaises(ValueError):
            patcher.patch("def unknown():pass\n")


if __name__=="__main__":
    unittest.main()
