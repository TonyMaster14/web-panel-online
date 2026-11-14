"""A VLESS-only federation POST must not require native write permissions.

Native protocol registration still needs writable backend registries under
systemd ProtectSystem=strict, on both fresh installs and existing-node hotfix.
"""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class Sandbox(unittest.TestCase):
    def test_eight_engine_fresh_node_uses_correct_native_permissions(self):
        script=(ROOT/"wpo-node-vpn-enable.sh").read_text()
        self.assertIn("ProtectSystem=strict",script)
        self.assertIn(
            "ReadWritePaths=/etc/wpp-node-vpn -/etc/systemd/system -/etc/tproxy-server -/etc/web-proxy-panel",
            script
        )

    def test_existing_node_updater_merges_permission_allowlist(self):
        script=(ROOT/"wpo-node-federation-hotfix.sh").read_text()
        self.assertIn("wpo-node-vpn.service.d/10-wpo-native-writes.conf",script)
        self.assertIn(
            "ReadWritePaths=-/etc/systemd/system -/etc/tproxy-server -/etc/web-proxy-panel",
            script
        )
        self.assertIn('systemctl daemon-reload',script)
        self.assertIn('systemctl restart "$SERVICE"',script)
        self.assertNotIn("systemctl restart wpo-node-xray.service",script)
        self.assertNotIn("systemctl restart caddy.service",script)
        self.assertIn('cp -a "$BACKUP/wpo_node_eight.py" "$MODULE"',script)

    def test_vless_only_never_executes_native_apply(self):
        src=(ROOT/"wpo_node_eight.py").read_text()
        self.assertIn("native_changed = assemble(old) != assemble(new)",src)
        self.assertIn("if native_changed:\n                    native_apply(new",src)
        self.assertIn("xray.apply(new)",src)

    def test_main_installer_pins_correct_future_sandbox(self):
        installer=(ROOT/"wpo-happ-ready-install.sh").read_text()
        self.assertIn("NODE_INSTALL_REV=50fc724db31fe2e8b20862dfc5eff67e99e67984",installer)
        self.assertIn("ENGINE_REV=b4d2691a6e942c0ff1ff4652acd63819cc0e0c6f",installer)
        self.assertNotIn("ssh ",installer)

if __name__=="__main__":
    unittest.main()
