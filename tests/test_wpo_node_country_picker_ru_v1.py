"""Regression: Russian country label in the node choice, no state mutations."""
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import wpo_user_v28 as user


class NodePickerCountryTests(unittest.TestCase):
    def test_sweden_poland_netherlands_auto_names_are_russian(self):
        self.assertEqual(user.display_node_name({"country_code":"SE","name":"Sweden"}),"Швеция")
        self.assertEqual(user.display_node_name({"country_code":"PL","name":"Poland"}),"Польша")
        self.assertEqual(user.display_node_name({"country_code":"NL","name":"Netherlands"}),"Нидерланды")
        self.assertEqual(user.display_node_name({"country_code":"SE","name":"Sweden","name_auto":True}),"Швеция")

    def test_admin_custom_names_not_overwritten(self):
        node={"id":"aaaaaaaaaaaaaaaa","country_code":"SE","name":"Stockholm 02","name_auto":False}
        original=dict(node)
        self.assertEqual(user.display_node_name(node),"Stockholm 02")
        self.assertEqual(node,original)

    def test_main_node_uses_localized_label(self):
        self.assertEqual(user.display_node_name({"country_code":"SE","name":"Sweden"}, "Основная нода"),"Швеция")

    def test_form_shows_russian_without_moving_flags_or_node_identifiers(self):
        code="abcdef1234567890"
        node={"id":code,"name":"Sweden","country_name":"Швеция",
              "country_code":"SE","enabled":True,"status":"online",
              "capabilities":["federation","vless","hysteria","reality"]}
        html=user.form("/panel-123","csrf",[],[node],
                       {"country_code":"NL","name":"Netherlands"})
        self.assertIn("Швеция",html)
        self.assertIn("Нидерланды",html)
        self.assertNotIn("<strong>Sweden</strong>",html)
        self.assertNotIn("<strong>Netherlands</strong>",html)
        self.assertIn("node_"+code,html)
        self.assertIn("🇸🇪",html)


if __name__=="__main__":unittest.main()
