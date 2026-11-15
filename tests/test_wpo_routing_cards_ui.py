"""WPO routing UI: protocol radio cards, multi-select rule cards, unchanged actions."""
import ast
import html
import importlib.util
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_routing_cards_patch",
    ROOT/"wpo-routing-cards-ui-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


def render(connections, state=None):
    src=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
    updated=patcher.patch(src)
    assert patcher.patch(updated)==updated
    ast.parse(updated)
    tree=ast.parse(updated)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="routing_ui")
    code=compile(ast.Module(body=[fn],type_ignores=[]),"<wpo-routing-ui>","exec")
    ns={"esc":lambda s:html.escape(str(s),quote=True),
        "selectable_connection":lambda item:True}
    exec(code,ns)
    return ns["routing_ui"](connections,state or {}, "/panel-test", "csrf-test"),src,updated


def conn(id,proto):
    return {"id":id,"name":proto+" / test","enabled":True,"protocol":proto}


class RoutingCardsUITests(unittest.TestCase):
    def setUp(self):
        self.all=[conn("wg31","awg31"),conn("hyst","hysteria"),
                  conn("vless","vless"),conn("wg20","awg20")]

    def test_four_exclusive_tabs_and_original_server_forms(self):
        result,old,updated=render(self.all)
        self.assertEqual(result.count('data-routing-choice='),4)
        self.assertEqual(result.count('aria-pressed="true"'),1)
        self.assertIn('data-routing-choice="vless" data-routing-enabled="0" aria-pressed="true"',result)
        self.assertIn('class="routing-protocol-card is-selected"',result)
        self.assertLess(result.index('data-routing-choice="vless"'),
                        result.index('data-routing-choice="hyst"'))
        self.assertLess(result.index('data-routing-choice="hyst"'),
                        result.index('data-routing-choice="wg20"'))
        self.assertLess(result.index('data-routing-choice="wg20"'),
                        result.index('data-routing-choice="wg31"'))
        self.assertIn('AmneziaWG 2.0',result)
        self.assertIn('AmneziaWG 3.1',result)
        self.assertNotIn('Подключение для маршрутизации<select',result)
        self.assertIn('id="routingConnection" hidden',result)
        self.assertIn("select.dispatchEvent(new Event('change'",result)
        self.assertEqual(result.count('data-routing-form='),4)
        self.assertIn('data-routing-form="vless" method="post"',result)
        self.assertIn('data-routing-form="hyst" method="post" action=',result)
        self.assertIn('data-routing-form="wg20" data-awg-form="1"',result)
        self.assertIn('data-routing-form="wg31" data-awg-form="1"',result)
        self.assertEqual(result.count('name="operation" value="add-selected"'),2)
        self.assertEqual(result.count('name="operation" value="remove-selected"'),2)
        self.assertIn('Скачать JSON',result)
        self.assertIn('.routing-form .routing-switches label.routing-toggle{',result)
        self.assertNotIn('.routing-form .routing-switches .routing-toggle{',result)
        self.assertIn(patcher.MARKER,result)
        self.assertIn('border-radius:13px',result)
        self.assertIn('#3b82f6',result)
        self.assertIn('#22c55e',result)
        self.assertEqual(old[:old.index('def routing_ui(')],
                         updated[:updated.index('def routing_ui(')])
        self.assertEqual(old[old.index('\n\ndef connections_ui('):],
                         updated[updated.index('\n\ndef connections_ui('):])

    def test_multi_select_preserves_input_names_and_persisted_markers(self):
        state={"profiles":{"vless":{"enabled":True,"ru_direct":True,
                                    "youtube_proxy":True}}}
        result,_,_=render([conn("vless","vless")],state)
        for flag in ("ru_direct","private_direct","youtube_proxy","push_proxy",
                     "captive_direct","block_bittorrent","split_dns"):
            self.assertIn(f'name="select_{flag}" value="1"',result)
        self.assertEqual(result.count('class="routing-rule-dot"'),7)
        self.assertIn('Российские сайты напрямую <em>Добавлено</em>',result)
        self.assertIn('YouTube через VPN <em>Добавлено</em>',result)
        self.assertEqual(result.count('data-routing-choice='),1)
        self.assertIn('class="routing-protocol-card is-unavailable"',result)
        self.assertEqual(result.count('aria-disabled="true"'),3)
        self.assertIn('routing-toggle:has(input:checked)',result)

    def test_multiple_connections_of_same_protocol_remain_accessible(self):
        result,_,_=render([conn("a","vless"),conn("b","vless"),
                           conn("c","awg20")])
        self.assertEqual(result.count('data-routing-choice='),3)
        for key in ("a","b","c"):
            self.assertIn(f'data-routing-choice="{key}"',result)
            self.assertIn(f'data-routing-form="{key}"',result)
        self.assertEqual(result.count('aria-pressed="true"'),1)

    def test_no_available_connection_keeps_existing_fallback(self):
        result,_,_=render([])
        self.assertIn('Нет доступных подключений',result)
        self.assertNotIn('routing-protocol-grid',result)

    def test_unknown_ui_version_is_refused(self):
        with self.assertRaises(ValueError):
            patcher.patch('def routing_ui(connections, state, path, csrf):\n    return ""\n')

if __name__=="__main__":
    unittest.main()
