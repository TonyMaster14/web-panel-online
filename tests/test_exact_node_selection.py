"""Regression coverage of exact WPO node selection and pinned 8-engine installer."""
import ast
from pathlib import Path
import unittest

import wpo_node_selection_v2 as patch

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
base=source.split("cat > \"$APP_FILE\" <<'PY'\n",1)[1].split("\nPY\n",1)[0]

def installed_panel():
    return base.replace("def traffic():",
                        "def selected_node_ids(form): return ['local']\ndef traffic():",1)

class ExactNodeSelection(unittest.TestCase):
    def test_extracted_panel_is_patchable_and_python_valid(self):
        result=patch.patch_panel(installed_panel())
        ast.parse(result)
        self.assertIn(patch.MARKER,result)
        self.assertIn('chosen=subscription.get("node_ids")',result)
        self.assertIn('if chosen is None: chosen=["local"]',result)
        self.assertIn('local_selected="local" in chosen',result)
        self.assertIn('if uid=="local": continue',result)
        self.assertIn('if uid=="local": continue',result)
        self.assertIn('node_api.sync_profile(',result)
        self.assertIn('len(profiles)!=len(wanted)',result)
        self.assertIn('set(by_protocol)!=set(wanted)',result)
        self.assertIn('urlparse(link).hostname!=urlparse(node.get("url","")).hostname',result)
        self.assertIn('local_count=len(result["users"]) if local_selected else 0',result)
        self.assertIn('len(distinct_nodes)>1',result)
        self.assertEqual(patch.patch_panel(result),result)

    def test_html_dashboard_branch_is_preserved(self):
        original=installed_panel()
        fixed=patch.patch_panel(original)
        start='    def serve_subscription(self,token):'
        end='    def serve_direct_profile(self,token):'
        original_body=original.split(start,1)[1].split(end,1)[0]
        fixed_body=fixed.split(start,1)[1].split(end,1)[0]
        html_prefix='            labels={"vless":"VLESS","hysteria":"Hysteria2"}'
        self.assertEqual(original_body.split(html_prefix,1)[0],
                         fixed_body.split(html_prefix,1)[0])
        self.assertIn('self.send_html(subscription_dashboard(',fixed)
        self.assertEqual(fixed.count('    def serve_direct_profile(self,token):'),1)

    def test_missing_nodes_lab_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"Nodes Lab"):
            patch.patch_panel(base)

    def test_eight_engine_enrollment_token_last_two_hours(self):
        source=installed_panel().replace(
            "def traffic():",
            'def test_bootstrap_ttl():\n'
            '    if path==PANEL_PATH+"/node-bootstrap":\n'
            '        pending={"expires_at":now+900}\n'
            '        answer={"expires_in":900}\n'
            'def traffic():',1)
        result=patch.patch_panel(source)
        ast.parse(result)
        self.assertIn('"expires_at":now+7200',result)
        self.assertIn('"expires_in":7200',result)
        self.assertNotIn('"expires_at":now+900',result)

    def test_validation_rejects_unsaved_node_ids(self):
        with self.assertRaisesRegex(ValueError,"persist"):
            patch.verify_subscriptions('def mutate(data, request): pass')

    def test_node_agent_installer_pins_dependencies_and_checks_eight(self):
        installer=(ROOT/"wpo-node-agent-install-v2.sh").read_text()
        required=(
            "ENGINE_REV=", 'WPO_NODE_VPN_REF="$ENGINE_REV"',
            '"https://$DOMAIN/wpp-api/v1/status"',
            '"Authorization: Bearer $API_KEY"',
            'expected={"federation","vless","hysteria","web","mtproto",'
            '"awg20","awg31","naive","mieru"}',
            "Node API lacks live engines:",
        )
        for value in required:
            self.assertIn(value,installer)

if __name__=="__main__":
    unittest.main()
