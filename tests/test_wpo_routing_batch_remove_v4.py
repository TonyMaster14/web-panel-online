"""Routing bulk removal regression: real persistence, UI affordance, red off status."""
import ast
import importlib.util
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

import sys
sys.path.insert(0,str(ROOT))
import wpp_routing as routing
import wpp_ui as ui

spec=importlib.util.spec_from_file_location(
    "route_batch_patch",ROOT/"maintenance/routing/wpo-routing-batch-remove-v4-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

INSTALLER=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
PANEL=INSTALLER.split('cat > "$APP_FILE" <<\'PY\'\n',1)[1].split('\nPY\n',1)[0]


class RoutingBatchRemoveV4(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path=str(Path(directory.name)/"routing.json")
        self.cid="vless-test"
        self.connection=[{"id":self.cid,"name":"VLESS XHTTP",
                          "protocol":"vless","enabled":True}]

    def add(self, *rules, domains=None):
        form={"select_"+key:"1" for key in rules}
        if domains:
            form["direct_domains_delta"]="\n".join(domains)
        return routing.update_selected(self.path,self.cid,form)

    def render(self):
        return ui.routing_ui(self.connection,routing.load(self.path),
                             "/panel-test","csrf-test")

    def test_remove_subset_of_three_leaves_other_saved_rules_active(self):
        self.add("ru_direct","private_direct","youtube_proxy",
                 "push_proxy","split_dns")
        state=routing.update_selected(self.path,self.cid,{
            "select_ru_direct":"1",
            "select_youtube_proxy":"1",
            "select_split_dns":"1"
        },remove=True)
        self.assertIsNotNone(state)
        self.assertFalse(state["ru_direct"])
        self.assertFalse(state["youtube_proxy"])
        self.assertFalse(state["split_dns"])
        self.assertTrue(state["private_direct"])
        self.assertTrue(state["push_proxy"])
        page=self.render()
        self.assertEqual(page.count('class="routing-toggle is-active"'),2)
        self.assertIn('data-routing-stored="1"',page)
        self.assertIn('id="routingState" class="routing-protocol-status is-on"',page)
        self.assertIn('data-routing-enabled="1"',page)

    def test_remove_all_seven_rules_turns_status_red(self):
        keys=list(routing.ROUTING_FLAGS)
        self.add(*keys)
        value=routing.update_selected(self.path,self.cid,{
            "select_"+key:"1" for key in keys},remove=True)
        self.assertIsNone(value)
        self.assertEqual(routing.load(self.path)["profiles"],{})
        page=self.render()
        self.assertIn('data-routing-enabled="0"',page)
        self.assertIn('id="routingState" class="routing-protocol-status"',page)
        self.assertIn('Маршрутизация отключена',page)
        self.assertIn('background:#ef4444',page)
        self.assertNotIn('class="routing-toggle is-active"',page)

    def test_explicit_remove_all_also_clears_saved_custom_domains(self):
        self.add("ru_direct","private_direct",domains=["example.com"])
        self.assertIn("domain:example.com",routing.load(self.path)["profiles"][self.cid]["direct_domains"])
        # The POST handler routes operation=remove-all to delete_profile.
        self.assertIn('elif operation=="remove-all" and not is_awg: routing_store.delete_profile(ROUTING_FILE,connection_id)',PANEL)
        routing.delete_profile(self.path,self.cid)
        self.assertNotIn(self.cid,routing.load(self.path)["profiles"])
        page=self.render()
        self.assertIn('data-routing-stored="0"',page)
        self.assertIn('Маршрутизация отключена',page)

    def test_ui_remove_without_explicit_checks_switches_to_confirmed_remove_all(self):
        page=self.render()
        self.assertIn('data-routing-stored="0"',page)
        self.add("ru_direct")
        page=self.render()
        self.assertIn('data-routing-stored="1"',page)
        self.assertIn("button.value='remove-all'",page)
        self.assertIn("if(!specific&&form.dataset.routingStored==='1')",page)
        self.assertIn("button.value==='remove-selected'&&saved",page)
        self.assertIn("Удалить всю маршрутизацию выбранного подключения",page)
        self.assertIn("Убрать только выбранные правила маршрутизации",page)
        self.assertIn(".routing-switches label.routing-toggle.is-active:has(input:checked)::after",page)
        self.assertIn('name="operation" value="remove-selected"',page)
        self.assertIn('name="operation" value="add-selected"',page)

    def test_existing_awg_operation_is_not_broadened(self):
        self.assertIn('elif operation=="remove-selected" and is_awg: routing_store.update_awg_selected(',PANEL)
        self.assertIn('elif operation=="remove-all" and not is_awg:',PANEL)
        self.assertIn('else: raise routing_store.RoutingError("Неизвестная операция маршрутизации.")',PANEL)

    def test_exact_version_patch_is_idempotent(self):
        ui_source=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        ast.parse(ui_source)
        ast.parse(PANEL)
        self.assertEqual(patcher.patch_ui(ui_source),ui_source)
        self.assertEqual(patcher.patch_app(PANEL),PANEL)
        with self.assertRaises(ValueError):
            patcher.patch_ui("def unrelated(): pass\n")
        with self.assertRaises(ValueError):
            patcher.patch_app("def unrelated(): pass\n")

if __name__=="__main__":
    unittest.main()
