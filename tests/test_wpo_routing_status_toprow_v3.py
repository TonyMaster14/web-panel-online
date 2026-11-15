"""WPO Routing v3 status tile follows selected protocol without being a button."""
import ast
from pathlib import Path
import unittest
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import wpp_ui


def row(protocol, name):
    return {"id":protocol,"protocol":protocol,"name":name,"enabled":True}


def page(*,profiles=None,awg_profiles=None,connections=None):
    items=connections if connections is not None else [
        row("awg31","AWG 3.1"),
        row("hysteria","Hysteria2"),
        row("vless","VLESS XHTTP"),
        row("awg20","AWG 2.0")]
    state={"profiles":profiles or {},"awg_profiles":awg_profiles or {}}
    return wpp_ui.routing_ui(items,state,"/panel-test","csrf")


class RoutingStatusTopRowTest(unittest.TestCase):
    def test_fifth_status_card_is_readonly_after_four_protocol_cards(self):
        html=page(profiles={"vless":{"enabled":True,"ru_direct":True}})
        self.assertEqual(html.count('data-routing-choice='),4)
        self.assertEqual(html.count('id="routingState"'),1)
        self.assertEqual(html.count('id="routingStateTitle"'),1)
        self.assertEqual(html.count('class="routing-protocol-status is-on"'),1)
        self.assertLess(html.index('data-routing-choice="awg31"'),
                        html.index('id="routingState"'))
        self.assertIn('role="status" aria-live="polite"',html)
        self.assertIn('Маршрутизация включена',html)
        self.assertNotIn('class="routing-status ',html)
        self.assertIn('grid-template-columns:repeat(5,minmax(0,1fr))',html)
        self.assertIn('pointer-events:none;user-select:none',html)
        self.assertIn('cursor:default;',html)

    def test_status_for_each_connection_is_server_grounded_and_switchable(self):
        html=page(profiles={"hysteria":{"enabled":True},
                            "vless":{"enabled":False}},
                  awg_profiles={"awg20":{"allowed_ips":["1.1.1.0/24"]}})
        self.assertIn('data-routing-choice="vless" data-routing-enabled="0"',html)
        self.assertIn('data-routing-choice="hysteria" data-routing-enabled="1"',html)
        self.assertIn('data-routing-choice="awg20" data-routing-enabled="1"',html)
        self.assertIn('data-routing-choice="awg31" data-routing-enabled="0"',html)
        self.assertIn('id="routingState" class="routing-protocol-status"',html)
        self.assertIn("const chosen=cards.find(card=>card.dataset.routingChoice===select.value)",html)
        self.assertIn("const enabled=chosen?.dataset.routingEnabled==='1'",html)
        self.assertIn("title.textContent=enabled?'Маршрутизация включена':'Маршрутизация отключена'",html)
        self.assertIn("card.classList.toggle('is-selected',active)",html)
        self.assertIn("history.replaceState(null",html)
        self.assertEqual(html.count('aria-pressed="true"'),1)

    def test_persisted_rule_ui_and_route_operations_are_untouched(self):
        html=page(profiles={"vless":{"enabled":True,"ru_direct":True}})
        self.assertIn('class="routing-toggle is-active"',html)
        self.assertIn('Российские сайты напрямую <em>Добавлено</em>',html)
        self.assertIn('name="operation" value="add-selected"',html)
        self.assertIn('name="operation" value="remove-selected"',html)
        self.assertIn('name="select_ru_direct" value="1"',html)
        self.assertIn('action="/panel-test/routing-action"',html)
        self.assertIn('Обновите подключение после изменения маршрутизации',html)
        self.assertIn('Скачать JSON',html)

    def test_v3_patch_is_idempotent_with_current_source(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location(
            "routing_status_patch",ROOT/"maintenance/routing/wpo-routing-status-toprow-v3-patch.py")
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        s=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        ast.parse(s)
        self.assertEqual(module.patch(s),s)
        with self.assertRaises(ValueError):
            module.patch('def unrelated(): pass\n')

if __name__=="__main__":
    unittest.main()
