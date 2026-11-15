"""Compact WPO v28 node chooser: visual labels only, no VPN logic changes."""
import ast
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("node_picker_patch",ROOT/"maintenance/nodes/wpo-node-picker-compact-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

vspec=importlib.util.spec_from_file_location("wpo_user_v28",ROOT/"wpo_user_v28.py")
form_module=importlib.util.module_from_spec(vspec)
vspec.loader.exec_module(form_module)

class CompactNodePickerTest(unittest.TestCase):
    def test_rendered_node_cards_have_one_line_and_primary_star(self):
        local={"name":"Нидерланды","country_code":"NL"}
        nodes=[
            {"id":"a"*16,"name":"Польша","country_code":"PL","status":"online",
             "enabled":True,"capabilities":["federation","vless","hysteria"]},
            {"id":"b"*16,"name":"Швеция","country_code":"SE","status":"offline",
             "enabled":True,"capabilities":["federation","vless","hysteria"]}
        ]
        html=form_module.form("/panel-test","csrf",[],nodes,local)
        self.assertIn("Нидерланды",html)
        self.assertIn("Польша",html)
        self.assertIn("Швеция",html)
        self.assertIn('title="Основная нода"',html)
        self.assertEqual(html.count('class="wpo-v28-node-star"'),1)
        self.assertIn('color:#facc15;font-size:15px;font-weight:750;',html)
        self.assertEqual(html.count('class="wpo-v28-node-title"'),3)
        self.assertNotIn("VPN готов",html)
        self.assertNotIn("VPN пока не готова",html)
        self.assertNotIn("Основная ·",html)
        self.assertIn('name="node_local" value="1" checked',html)
        self.assertIn('name="node_'+"a"*16+'" value="1"',html)
        self.assertIn('name="node_'+"b"*16+'" value="1" disabled',html)
        self.assertIn(".wpo-v28-node>span.wpo-v28-node-title{display:inline-flex;align-items:center;",html)
        self.assertIn(".wpo-v28-flag{display:inline-flex;align-items:center;",html)

    def test_updater_is_idempotent_on_committed_source(self):
        updated=(ROOT/"wpo_user_v28.py").read_text(encoding="utf-8")
        ast.parse(updated)
        self.assertEqual(patcher.patch(updated),updated)

    def test_updater_rejects_unknown_file(self):
        with self.assertRaises(ValueError):
            patcher.patch("def unrelated():\n    return None\n")

if __name__=="__main__":
    unittest.main()
