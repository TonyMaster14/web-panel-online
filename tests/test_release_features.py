"""Regression checks for released functionality, independent of historical patch scripts."""
import unittest
from pathlib import Path

import wpp_ui
import wpo_happ_async_feed

ROOT=Path(__file__).resolve().parents[1]


class CurrentRoutingUI(unittest.TestCase):
    def test_protocol_selection_and_mass_actions_are_present(self):
        connections=[
            {"id":"vless","name":"Home VPN","protocol":"vless","enabled":True},
            {"id":"hyst","name":"Hysteria2","protocol":"hysteria","enabled":True},
            {"id":"awg20","name":"AmneziaWG 2.0","protocol":"awg20","enabled":True},
        ]
        html=wpp_ui.routing_ui(connections,{
            "profiles":{"vless":{"enabled":True,"ru_direct":True}},
        },"/panel-example","csrf-example")
        self.assertIn("Свои исключения",html)
        self.assertIn("VLESS XHTTP",html)
        self.assertIn("Hysteria2",html)
        self.assertIn('data-routing-choice="awg20"',html)
        self.assertIn('name="operation" value="add-selected"',html)
        self.assertIn('name="operation" value="remove-selected"',html)
        self.assertIn('data-routing-enabled="1"',html)
        self.assertIn('name="direct_domains_delta"',html)
        self.assertIn('name="proxy_domains_delta"',html)


class CurrentHappFederation(unittest.TestCase):
    class API:
        API_PREFIX="/wpp-api/v1"
        NodeError=ValueError
        def __init__(self,links):
            self.links=links
            self.calls=0
        def request(self,node,method,path,payload,timeout):
            assert method=="POST" and path.endswith("/federation/sync")
            assert payload["protocols"]==["vless","hysteria"]
            assert timeout==90
            self.calls+=1
            return {"profiles":[
                {"protocol":"vless","link":self.links[0]},
                {"protocol":"hysteria","link":self.links[1]},
            ]}

    def test_only_verified_remote_profiles_are_returned(self):
        links=[
            "vless://11111111-1111-4111-8111-111111111111@pl.example.net:443?type=xhttp",
            "hysteria2://secret@pl.example.net:8443/?sni=pl.example.net",
        ]
        api=self.API(links)
        node={"id":"a"*16,"url":"https://pl.example.net","enabled":True}
        actual=wpo_happ_async_feed.verified_links(
            api,node,"account-device","Home VPN",["vless","hysteria"])
        self.assertEqual(actual,links)
        self.assertEqual(api.calls,1)

    def test_links_from_other_domains_are_rejected(self):
        api=self.API([
            "vless://11111111-1111-4111-8111-111111111111@wrong.example.net:443?type=xhttp",
            "hysteria2://secret@pl.example.net:8443/?sni=pl.example.net",
        ])
        node={"id":"a"*16,"url":"https://pl.example.net","enabled":True}
        with self.assertRaises(ValueError):
            wpo_happ_async_feed.verified_links(
                api,node,"account-device","Home VPN",["vless","hysteria"])


class UserDocumentation(unittest.TestCase):
    def test_current_readme_exposes_install_and_local_zip_update(self):
        md=(ROOT/"README.md").read_text(encoding="utf-8")
        self.assertIn("WEB PANEL ONLINE 3.0.0",md)
        self.assertIn("/main/install.sh",md)
        self.assertIn("bash ./update.sh --local",md)
        self.assertIn("archive/refs/heads/main.zip",md)
        self.assertNotIn("Аренда VPS",md)
        self.assertNotIn("POLESNIESOVETI12",md)
        self.assertNotIn("maintenance/",md)

    def test_only_active_installation_dependencies_are_published(self):
        self.assertFalse((ROOT/"maintenance").exists())
        self.assertTrue((ROOT/"installers/site-service-update.sh").is_file())
        self.assertTrue((ROOT/"installers/site-relay-module.py").is_file())


if __name__=="__main__":
    unittest.main()
