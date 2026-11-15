"""One command on the main WPO VPS; no separate user run on additional nodes."""
import re
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"maintenance/happ/wpo-one-vps-multinode-repair.sh"
SOURCE=SCRIPT.read_text(encoding="utf-8")


class SingleServerOrchestration(unittest.TestCase):
    def test_bash_valid(self):
        r=subprocess.run(["bash","-n",str(SCRIPT)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_controller_only_with_registered_nodes(self):
        self.assertIn("APP=/opt/tproxy-panel",SOURCE)
        self.assertIn("NODES=/var/lib/tproxy-panel/nodes.json",SOURCE)
        self.assertIn("! -e /etc/wpp-node-agent/config.json",SOURCE)
        self.assertIn("api.load_nodes(sys.argv[1])",SOURCE)
        self.assertIn('if host not in hosts:',SOURCE)
        self.assertNotIn("bafy.goodarielservice.xyz",SOURCE)
        self.assertNotIn("swegen.goodarielservice.xyz",SOURCE)
        self.assertIn("python3 -m py_compile",SOURCE)

    def test_authenticated_ssh_and_no_weak_security_bypass(self):
        self.assertIn("StrictHostKeyChecking=ask",SOURCE)
        self.assertIn('NumberOfPasswordPrompts=3',SOURCE)
        self.assertIn('"$SSH_USER@$host"',SOURCE)
        self.assertIn("'bash -se' < \"$WORK/node.sh\"",SOURCE)
        self.assertNotIn("StrictHostKeyChecking=no",SOURCE)
        self.assertNotIn("UserKnownHostsFile=/dev/null",SOURCE)
        self.assertNotIn("sshpass",SOURCE)
        self.assertNotIn("curl -k",SOURCE)
        self.assertNotIn("site-template",SOURCE)

    def test_upgrades_and_verifies_before_claiming_success(self):
        self.assertIn('wpo-node-federation-hotfix.sh',SOURCE)
        self.assertIn('wpo-happ-multinode-main-install.sh',SOURCE)
        self.assertIn('wpo_happ_preparer.py',SOURCE)
        self.assertLess(SOURCE.index('python3 "$WORK/panel-patch.py"'),SOURCE.index("while IFS= read -r host"))
        self.assertLess(SOURCE.index("while IFS= read -r host"),SOURCE.index('bash "$WORK/main.sh"'))
        self.assertIn("✗ Не все VPN-профили созданы.",SOURCE)
        self.assertIn("выбранные ноды подготовлены",SOURCE)
        # No remote script run from the user's terminal: only orchestrator SSH.
        self.assertIn("одна команда только на основном VPS",SOURCE)

    def test_absent_optional_ssh_env_is_safe_under_set_nounset(self):
        self.assertIn("set -Eeuo pipefail",SOURCE)
        self.assertIn('[[ -z "$'+'{WPO_NODE_SSH_PORT:-}" ]]',SOURCE)
        self.assertIn('[[ -z "$'+'{WPO_NODE_SSH_USER:-}" ]]',SOURCE)


if __name__=="__main__":
    unittest.main()
