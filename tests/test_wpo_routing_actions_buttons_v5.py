"""UI regression tests for the routing action bar: polished styling only."""
import ast
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import wpp_ui

spec=importlib.util.spec_from_file_location(
    "routing_actions_v5",ROOT/"wpo-routing-actions-buttons-v5-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


def render():
    connections=[
        {"id":"vless","protocol":"vless","name":"VLESS XHTTP","enabled":True},
        {"id":"hyst","protocol":"hysteria","name":"Hysteria2","enabled":True},
        {"id":"wg20","protocol":"awg20","name":"AmneziaWG 2.0","enabled":True},
    ]
    state={"profiles":{"vless":{"enabled":True,"ru_direct":True}},
           "awg_profiles":{}}
    return wpp_ui.routing_ui(connections,state,"/panel-demo","csrf-test")


class RoutingActionsV5(unittest.TestCase):
    def test_blue_add_and_red_remove_buttons_with_hover_lift(self):
        html=render()
        self.assertEqual(html.count('class="routing-actions-primary"'),2)
        self.assertEqual(html.count('class="routing-actions-secondary"'),2)
        self.assertEqual(html.count('class="routing-actions"'),2)
        self.assertIn('button.routing-add{',html)
        self.assertIn('background:#2563eb',html)
        self.assertIn('button.danger{',html)
        self.assertIn('background:#c9364f',html)
        self.assertIn('transform:translateY(-2px)',html)
        self.assertIn('border-radius:11px',html)
        self.assertIn('min-width:210px;min-height:46px',html)
        self.assertIn('transition:transform .2s cubic-bezier(.2,.75,.25,1)',html)
        self.assertIn('background:#df405a!important',html)

    def test_aligns_to_main_custom_columns_and_stacks_on_mobile(self):
        html=render()
        self.assertIn('grid-template-columns:minmax(0,1.5fr) minmax(300px,.65fr)',html)
        self.assertIn('.routing-form .routing-actions-secondary{',html)
        self.assertIn('justify-content:flex-end',html)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',html)
        self.assertIn('@media(max-width:600px)',html)
        self.assertIn('grid-template-columns:1fr',html)
        self.assertIn('border-top:1px solid var(--line)',html)
        self.assertIn('prefers-reduced-motion:reduce',html)

    def test_existing_post_and_confirm_actions_unchanged(self):
        html=render()
        self.assertEqual(html.count('name="operation" value="add-selected"'),2)
        self.assertEqual(html.count('name="operation" value="remove-selected"'),2)
        self.assertIn('button.value=&#x27;remove-all&#x27;' if False else "button.value='remove-all'",html)
        self.assertIn('name="select_ru_direct" value="1"',html)
        self.assertIn('name="direct_domains_delta"',html)
        self.assertIn('name="proxy_domains_delta"',html)
        self.assertIn('Маршрутизация включена',html)
        self.assertIn('data-routing-choice="wg20"',html)

    def test_patch_is_idempotent_and_scoped(self):
        src=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        self.assertEqual(src,patcher.patch(src))
        ast.parse(src)
        self.assertEqual(src.count(patcher.MARKER),1)
        with self.assertRaises(ValueError):
            patcher.patch("def unrelated():\n    pass\n")

if __name__=="__main__":
    unittest.main()
