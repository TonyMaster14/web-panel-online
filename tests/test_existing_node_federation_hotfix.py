"""Prove the existing-node hotfix is scoped to the federation Python module."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"maintenance/nodes/wpo-node-federation-hotfix.sh"
S=SCRIPT.read_text()
ENGINE=(ROOT/"wpo_node_eight.py").read_text()

class ExistingNodeHotfix(unittest.TestCase):
    def test_shell_syntax_and_root_host_scope(self):
        r=subprocess.run(["bash","-n",str(SCRIPT)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('[[ "$EUID" == 0 ]]',S)
        self.assertIn('! -e /opt/tproxy-panel/panel.py',S)
        self.assertIn('MODULE="$ROOT/wpo_node_eight.py"',S)
        self.assertIn('CONFIG=/etc/wpp-node-agent/config.json',S)

    def test_no_service_restarter_except_node_api(self):
        self.assertIn('SERVICE=wpo-node-vpn.service',S)
        self.assertIn('systemctl restart "$SERVICE"',S)
        for dangerous in (
            'systemctl restart wpo-node-xray.service',
            'systemctl restart xray.service',
            'systemctl restart caddy.service',
            'systemctl restart wpo-node-relay.service',
            'systemctl restart tproxy-panel.service',
            'systemctl restart web-panel-proxy-awg',
            'node-agent-install-v2.sh',
            'install-panel.sh',
            'ssh root@',
        ):
            self.assertNotIn(dangerous,S)
        self.assertIn("flock -w 40 8",S)
        self.assertIn('cp -a "$MODULE" "$BACKUP/wpo_node_eight.py"',S)
        self.assertIn('cp -a "$BACKUP/wpo_node_eight.py" "$MODULE"',S)
        self.assertIn('ROLLBACK=0',S)

    def test_service_sandbox_no_longer_blocks_native_config_registries(self):
        # The original Node Agent unit had ProtectSystem=strict with only
        # /etc/wpp-node-vpn writable. That made the first VLESS sync fail
        # because native_apply tried to write /etc/tproxy-server.
        vpn_installer=(ROOT/"wpo-node-vpn-enable.sh").read_text()
        self.assertIn("ProtectSystem=strict",vpn_installer)
        allowlist="ReadWritePaths=/etc/wpp-node-vpn -/etc/systemd/system -/etc/tproxy-server -/etc/web-proxy-panel"
        self.assertIn(allowlist,vpn_installer)
        self.assertIn("ReadWritePaths=-/etc/systemd/system -/etc/tproxy-server -/etc/web-proxy-panel",S)
        self.assertIn("systemctl daemon-reload",S)
        self.assertIn('DROPIN=/etc/systemd/system/wpo-node-vpn.service.d/10-wpo-native-writes.conf',S)

    def test_engine_patch_keeps_real_xray_apply_and_skips_unrelated_services(self):
        self.assertIn('native_changed = assemble(old) != assemble(new)',ENGINE)
        self.assertIn('xray.apply(new)',ENGINE)
        self.assertIn('if native_changed:',ENGINE)
        self.assertIn('native_apply(new, xray.read_json(SETTINGS))',ENGINE)

if __name__=="__main__":
    unittest.main()
