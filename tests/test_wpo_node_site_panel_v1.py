"""WPO node cards and offline site template pack: no VPS dependencies."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT))
import wpo_node_site_view_v1 as view
import wpo_node_site_pack_v1 as pack

def installer():
    name=ROOT/"scripts/wpo-node-site-panel-v1.py"
    spec=importlib.util.spec_from_file_location("wpo_node_site_panel_v1",name)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def card():
    return ('<div class="wpo-node-grid"><article class="card wpo-node-card">'
            '<div class="wpo-node-card-head"><b>🇸🇪</b><span>В сети</span></div>'
            '<a class="wpo-node-domain" href="https://swejeep.goodarielservice.xyz" '
            'target="_blank">swejeep.goodarielservice.xyz</a>'
            '<p class="wpo-node-template"><span>⚙</span> Шаблон: Автосервис</p>'
            '<button data-node-edit="abcdef1234567890">Изменить</button>'
            '</article></div>')


class NodeSiteViewTests(unittest.TestCase):
    def test_direct_443_adds_compact_mode_without_second_link_or_card(self):
        original=card()
        changed=view.decorate(original,[{"id":"abcdef1234567890",
                     "capabilities":["federation","reality","reality-direct-443"],
                     "site_template_id":"auto-service"}])
        self.assertEqual(changed.count("wpo-node-domain"),1)
        self.assertEqual(changed.count('href="https://swejeep.goodarielservice.xyz"'),1)
        self.assertEqual(changed.count('<article'),1)
        self.assertIn("REALITY 443",changed)
        self.assertIn("Шаблон: Автосервис",changed)
        self.assertIn("wpo-real443-card-v1",changed)
        self.assertIn("wpo-site-line-v1",changed)
        self.assertIn('target="_blank"',changed)

    def test_legacy_mode_is_not_falsely_marked_direct(self):
        result=view.decorate(card(),[{"id":"abcdef1234567890","capabilities":["reality"]}])
        self.assertIn("REALITY",result)
        self.assertNotIn("REALITY 443",result)
        self.assertNotIn("wpo-real443-card-v1",result)

    def test_pending_template_relabels_without_fake_link(self):
        result=view.decorate(card().replace("Автосервис","Сайт не выбран"),
               [{"id":"abcdef1234567890","auto_site_template_id":"wpo-studio"}])
        self.assertIn("Выбирается автоматически",result)
        self.assertEqual(result.count("wpo-node-domain"),1)
        self.assertNotIn("REALITY 443",result)

    def test_untouched_nodes_and_unrelated_cards(self):
        self.assertEqual(view.decorate(card(),[]),card())
        self.assertEqual(view.decorate(card(),[{"id":"aaaaaaaaaaaaaaaa",
                                                "capabilities":["reality-direct-443"]}]),card())

    def test_installed_wrapper_preserves_original_signature_and_css(self):
        calls=[]
        ns={"nodes_ui":lambda nodes,*a,**kw:calls.append((nodes,a,kw)) or card(),
            "CSS":"body{color:black;}"}
        view.install(ns)
        self.assertIn("WPO_NODE_SITE_VIEW_V1",ns["CSS"])
        example=[{"id":"abcdef1234567890","capabilities":["reality-direct-443"]}]
        html=ns["nodes_ui"](example,"local",path="/panel")
        self.assertIn("REALITY 443",html)
        self.assertEqual(len(calls),1)
        view.install(ns)
        self.assertEqual(ns["CSS"].count("WPO_NODE_SITE_VIEW_V1"),1)


class SitePackTests(unittest.TestCase):
    def test_standalone_site_pack_has_unique_ids_and_no_external_assets(self):
        pages=pack.presets()
        self.assertEqual(len(pages),4)
        self.assertEqual(len({p["id"] for p in pages}),len(pages))
        for p in pages:
            self.assertLess(len(p["html"].encode("utf-8")),2100000)
            for term in ("<!doctype html>","</html>","<meta name=\"viewport\"","<style>"):
                self.assertIn(term,p["html"])
            self.assertNotIn("<script",p["html"])
            self.assertNotIn("http://",p["html"])
            self.assertNotIn("https://",p["html"])
            self.assertNotIn("preset-",p["html"])

    def test_append_to_current_presets_and_skip_duplicate_id(self):
        ns={"presets":lambda:[{"id":"cars","name":"Автосалон","html":"old"},
                               {"id":"wpo-studio","name":"Ранее добавленный","html":"keep"}]}
        pack.install(ns)
        items=ns["presets"]()
        self.assertEqual(items[1]["html"],"keep")
        self.assertEqual(len(items),5)
        pack.install(ns)
        self.assertEqual(ns["presets"](),items)

    def test_panel_installer_only_appends_small_hooks_to_known_modules(self):
        m=installer()
        ui='import hashlib\nCSS=""\nCOMMON_JS=""\ndef nodes_ui(*a):\n    return "wpo-node-domain wpo-node-template"\n'
        out=m.patch_ui(ui)
        self.assertIn("wpo_node_site_view_v1.install(globals())",out)
        self.assertIn("ASSET_REV=hashlib.sha256",out)
        compile(out,"panel-ui","exec")
        with self.assertRaises(RuntimeError):
            m.patch_ui(out)
        source='def presets():\n    return []\n'
        lib=m.patch_library(source)
        self.assertIn("wpo_node_site_pack_v1.install(globals())",lib)
        compile(lib,"presets","exec")
        with self.assertRaises(RuntimeError):
            m.patch_library(lib)

    def test_installer_has_rollback_and_does_not_touch_vpn_services(self):
        text=(ROOT/"scripts/wpo-node-site-panel-v1.py").read_text()
        self.assertIn("def restore(",text)
        self.assertIn("original_sha256",text)
        self.assertNotIn('systemctl","restart","wpo-node-xray',text)
        self.assertNotIn('systemctl","restart","caddy',text)


if __name__=="__main__":
    unittest.main()
