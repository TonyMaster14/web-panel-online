"""WPO routing: persisted flags remain highlighted after server-side save."""
import ast
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("routing_persisted_v2",ROOT/"maintenance/routing/wpo-routing-persisted-rules-v2-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

import sys
sys.path.insert(0,str(ROOT))
import wpp_ui

def render(state):
    connections=[{"id":"vless","name":"VLESS XHTTP","protocol":"vless","enabled":True},
                 {"id":"hyst","name":"Hysteria2","protocol":"hysteria","enabled":True}]
    return wpp_ui.routing_ui(connections,state,"/panel-test","csrf-test")

class RoutingPersistedRuleTests(unittest.TestCase):
    def test_saved_rules_keep_blue_outline_and_green_dot(self):
        page=render({"profiles":{"vless":{"enabled":True,"ru_direct":True,
                                             "youtube_proxy":True,
                                             "private_direct":False}}})
        self.assertIn('class="routing-toggle is-active"><input type="checkbox" name="select_ru_direct"',page)
        self.assertIn('class="routing-toggle is-active"><input type="checkbox" name="select_youtube_proxy"',page)
        self.assertIn('class="routing-toggle"><input type="checkbox" name="select_private_direct"',page)
        self.assertEqual(page.count('class="routing-toggle is-active"'),2)
        self.assertIn('.routing-switches label.routing-toggle.is-active .routing-rule-dot i',page)
        self.assertIn('border-color:#3b82f6',page)
        self.assertIn('background:#22c55e',page)
        # Existing checkbox remains DELTA action selection. Saved flags and pending
        # actions are separate so no unwanted remove operation can be submitted.
        self.assertNotIn('name="select_ru_direct" value="1" checked',page)
        self.assertIn('name="operation" value="add-selected"',page)
        self.assertIn('name="operation" value="remove-selected"',page)
        self.assertIn('Российские сайты напрямую <em>Добавлено</em>',page)

    def test_disabled_profile_has_no_false_active_indicators(self):
        page=render({"profiles":{"vless":{"enabled":False,"ru_direct":True}}})
        self.assertNotIn('class="routing-toggle is-active"',page)
        self.assertNotIn('Российские сайты напрямую <em>Добавлено</em>',page)

    def test_red_notice_is_even_and_hero_has_dark_background(self):
        page=render({})
        self.assertIn(patcher.MARKER,page)
        self.assertIn('.routing-form .routing-client-notice{',page)
        self.assertIn('border:1px solid color-mix(in srgb,var(--red) 52%,var(--line))',page)
        self.assertIn('box-shadow:none',page)
        self.assertIn('.routing-form .routing-hero{background:var(--surface)}',page)
        self.assertIn('Обновите подключение после изменения маршрутизации',page)
        self.assertEqual(page.count('data-routing-choice='),2)

    def test_file_patch_idempotent_and_scope_limited(self):
        src=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        self.assertEqual(patcher.patch(src),src)
        ast.parse(src)
        with self.assertRaises(ValueError):
            patcher.patch("def unrelated():\n    pass\n")

if __name__=="__main__":
    unittest.main()
