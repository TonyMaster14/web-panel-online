"""One-command MAIN WPO updater must avoid VPN daemon restarts and rotated keys."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SH=(ROOT/"wpo-happ-multinode-main-install.sh").read_text()
WORKER=(ROOT/"wpo_happ_async_feed.py").read_text()
PREP=(ROOT/"wpo_happ_preparer.py").read_text()
PANEL=(ROOT/"wpo-happ-async-panel-patch.py").read_text()
SUBS=(ROOT/"wpo-happ-preallocate-patch.py").read_text()


class MainOnlyUpdate(unittest.TestCase):
    def test_shell_syntax(self):
        proc=subprocess.run(["bash","-n",str(ROOT/"wpo-happ-multinode-main-install.sh")],
                            capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)

    def test_main_only_no_remote_ssh_or_daemon_restarts(self):
        self.assertIn('! -e /etc/wpp-node-agent/config.json',SH)
        self.assertIn('wpo_happ_async_feed.py',SH)
        self.assertIn('wpo_happ_preparer.py',SH)
        self.assertIn('systemctl restart tproxy-panel.service',SH)
        self.assertIn('cp -a "$BACKUP/panel.py" "$PANEL"',SH)
        for dangerous in ("ssh root@", "sshpass", "apt-get", "curl -k",
                          "systemctl restart caddy.service",
                          "systemctl restart wpo-node-xray.service",
                          "systemctl restart wpo-node-vpn.service",
                          "systemctl restart wpo-node-relay.service",
                          "systemctl restart xray.service"):
            self.assertNotIn(dangerous,SH)

    def test_fast_happ_and_preallocation_are_both_installed(self):
        self.assertIn('WPO_NODE_VPN_REF="$ENGINE_REV" bash "$EIGHT_SETUP"',SH)
        self.assertNotIn("wpo-node-site-template-fix.sh",SH)
        # A previous invalid grep silently aborted the installer before
        # touching panel.py, leaving the old 503 path in place.
        self.assertIn("wpo-happ-preallocate-patch.py",SH)
        self.assertIn("wpo-happ-async-panel-patch.py",SH)
        self.assertIn("wpo-happ-preparer.path",SH)
        self.assertIn("wpo-happ-preparer.timer",SH)
        self.assertIn('PathChanged=/etc/web-proxy-panel/users.json',SH)
        self.assertIn('OnUnitInactiveSec=90s',SH)
        self.assertIn('ReadWritePaths=/var/lib/tproxy-panel /run/lock',SH)
        self.assertIn("Нода",SH)

        self.assertIn('ROLLBACK=1',SH)
        self.assertIn('ROLLBACK=0',SH)
        self.assertIn("def verified_links(",WORKER)
        self.assertIn("def prewarmed(",WORKER)
        self.assertIn("def prepare(",PREP)
        self.assertIn("wpo_happ_async_feed.enqueue(",PANEL)
        self.assertIn("preallocate_first_remote_device",SUBS)

    def test_happ_doesnt_wait_for_unbounded_remote_ops(self):
        self.assertIn("time.monotonic()+2.5",PANEL)
        self.assertNotIn("node_api.sync_profile(",PANEL.split("BODY='''",1)[1].split("'''",1)[0])
        self.assertIn("CACHE_TTL =",WORKER)
        self.assertIn("WORKERS = concurrent.futures.ThreadPoolExecutor(max_workers=4",WORKER)


if __name__=="__main__":
    unittest.main()
