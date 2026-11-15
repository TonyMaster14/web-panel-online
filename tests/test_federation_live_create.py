"""Regression: create a WPO account using live Federation, not stale Node Agent status."""
from pathlib import Path
import ast
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"wpo-federation-live-create-patch.py"
spec=importlib.util.spec_from_file_location("federation_live_gate",SCRIPT)
patch=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

class FederationCreationTests(unittest.TestCase):
    def test_exact_installed_v27_anchor_is_supported(self):
        controller=(ROOT/"wpo-node-controller-vpn.sh").read_text()
        self.assertIn(patch.BEFORE,controller)
        source="def create():\n    chosen_nodes=['local','a'*16,'b'*16]\n    connection_specs=[]\n"+patch.BEFORE+"\n"
        result=patch.patch(source)
        ast.parse(result)
        self.assertEqual(result.count(patch.MARKER),1)
        self.assertEqual(patch.patch(result),result)
        self.assertNotIn('node_api.API_PREFIX+"/status"',result)
        self.assertIn('node_api.API_PREFIX+"/federation/status"',result)
        self.assertIn('wanted_protocols.issubset(caps)',result)
        self.assertIn('if uid!="local"',result)
        self.assertIn('if not node.get("enabled",True)',result)
        self.assertIn('create_error("VPN Federation не готова',result)
    def test_no_bypass_for_dead_remote_or_missing_node(self):
        self.assertIn('if any(uid not in available_nodes',patch.AFTER)
        self.assertIn('except node_api.NodeError:',patch.AFTER)
        self.assertIn('if unavailable:',patch.AFTER)
        self.assertNotIn('continue\n                if unavailable:',patch.AFTER)
    def test_pure_patch_refuses_unknown_install(self):
        with self.assertRaisesRegex(ValueError,"Expected installed"):
            patch.patch("def create(): pass\n")
    def test_main_only_rollback(self):
        script=(ROOT/"wpo-federation-live-create-install.sh").read_text()
        self.assertIn('! -e /etc/wpp-node-agent/config.json',script)
        self.assertIn('cp -a "$BACKUP" "$PANEL"',script)
        self.assertIn('systemctl restart tproxy-panel.service',script)
        for unsafe in ('ssh root@','sshpass','systemctl restart wpo-node-xray',
                       'systemctl restart caddy.service','apt-get','curl -k'):
            self.assertNotIn(unsafe,script)

if __name__=="__main__":
    unittest.main()
