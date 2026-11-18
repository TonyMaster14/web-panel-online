"""Regression: website, API, and XHTTP paths stay separate after REALITY-443."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import wpo_node_site_pack_v1 as sites


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


class SiteTransportTests(unittest.TestCase):
    def test_new_node_random_template_works_with_zero_webp_assets(self):
        autotemplate=load("nodes/wpo-node-autotemplate-v20.py","node_autotemplate_test")
        with tempfile.TemporaryDirectory() as folder:
            autotemplate._ROOT=folder
            eligible=autotemplate._eligible(sites.presets())
            self.assertEqual(len(eligible),4)
            chosen=autotemplate.choose([],sites.presets())
            self.assertIn(chosen,eligible)
            another=autotemplate.choose([{"site_template_id":chosen}],sites.presets())
            self.assertIn(another,eligible)
            self.assertNotEqual(chosen,another,"Prefer an unused template")
            payload=autotemplate._payload(sites.presets(),another)
            self.assertEqual(payload["assets"],[])
            self.assertEqual(payload["template_id"],another)
            self.assertIn("</html>",payload["html"])

    def test_website_root_does_not_overlap_node_vpn_or_api_paths(self):
        site=(ROOT/"nodes/wpo-node-agent-install-v2.sh").read_text()
        vpn=(ROOT/"nodes/wpo-node-vpn-enable.sh").read_text()
        self.assertIn("handle /wpp-api/* {",site)
        self.assertIn("reverse_proxy 127.0.0.1:9088",site)
        self.assertIn("handle {\n        root * /var/www/wpp-node-site",site)
        self.assertIn("file_server",site)
        self.assertIn('handle /wpp-api/v1/federation/* {',vpn)
        self.assertIn("reverse_proxy 127.0.0.1:9089",vpn)
        self.assertIn("@wpo_node_xhttp path",vpn)
        self.assertIn("reverse_proxy 127.0.0.1:19000",vpn)
        self.assertLess(vpn.index("handle @wpo_node_xhttp"),
                        vpn.index("s=s.replace(anchor,addon,1)"))

    def test_sweden_real443_nginx_forwards_non_reality_tls_to_caddy(self):
        source=(ROOT/"scripts/wpo-sweden-real443-switch-v1.py").read_text()
        self.assertIn("proxy_pass https://127.0.0.1:19443;",source)
        self.assertIn("proxy_set_header Upgrade $http_upgrade;",source)
        self.assertIn("proxy_http_version 1.1;",source)
        self.assertIn("proxy_ssl_server_name on;",source)

    def test_node_site_templating_keeps_manual_priority(self):
        code=(ROOT/"nodes/wpo-node-autotemplate-v20.py").read_text()
        self.assertIn('if selected.get("site_template_id"):',code)
        self.assertIn('selected.pop("auto_site_template_id", None)',code)
        panel=(ROOT/"node-install.sh").read_text()
        self.assertIn('selected.pop("auto_site_template_id",None)',panel)
        self.assertIn('node_api.API_PREFIX+"/site-template"',panel)


if __name__=="__main__":
    unittest.main()
