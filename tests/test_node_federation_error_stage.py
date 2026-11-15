"""WPO Node Federation stage tracing is secret-free and rollback-safe."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("fed_trace_patch",ROOT/"maintenance/nodes/wpo-node-federation-error-stage-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

class StageTraceTests(unittest.TestCase):
    def test_stage_patch_preserves_backend_and_handles_duplicate(self):
        before=(ROOT/"wpo_node_vpn.py").read_text(encoding="utf-8")
        patched=patcher.patch(before)
        ast.parse(patched)
        self.assertEqual(patcher.patch(patched),patched)
        self.assertIn(patcher.MARKER,patched)
        self.assertIn('phase = "xray-config-validation"',patched)
        self.assertIn('phase = "systemctl-restart"',patched)
        self.assertIn('phase = "post-restart-health"',patched)
        self.assertIn('WPO_FED_REQUEST_FAILURE',patched)
        self.assertIn('WPO_FED_REQUEST_CRASH',patched)
        for fragment in ('atomic_json(STATE, {"profiles": updated})',
                         'command("systemctl", "restart", UNIT, timeout=30)',
                         'wpo_node_eight.sync(data)',
                         'fcntl.flock(lock.fileno(), fcntl.LOCK_EX)'):
            self.assertIn(fragment,patched)
        self.assertEqual(before.count('WPO_FED_APPLY_FAILURE'),0)
        self.assertNotIn('str(exc) + " phase=',patched)

    def test_patch_rejects_unexpected_service_file(self):
        with self.assertRaisesRegex(ValueError,"Unexpected Node VPN"):
            patcher.patch("def x():\n    pass\n")

    def test_installer_only_additional_node_with_rollback(self):
        src=(ROOT/"maintenance/nodes/wpo-node-federation-error-stage-install.sh").read_text()
        result=subprocess.run(["bash","-n"],input=src,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for required in ('! -e /opt/tproxy-panel/panel.py',
                         'cp -a "$BACKUP" "$MODULE"',
                         "systemctl restart wpo-node-vpn.service",
                         "wpo-node-federation-error-stage-patch.py",
                         "http://127.0.0.1:9089/healthz",
                         "grep WPO_FED"):
            self.assertIn(required,src)
        for prohibited in ('rm -rf /etc/wpp-node-vpn',
                           'systemctl restart wpo-node-xray.service',
                           'systemctl restart caddy.service',
                           'sshpass','apt-get'):
            self.assertNotIn(prohibited,src)

if __name__=="__main__":
    unittest.main()
