"""Node 9089 start must be bounded, diagnosable and not lie about progress."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]/"nodes/wpo-node-agent-install-v2.sh"
BEGIN="python3 - \"$VPN_SETUP\" <<'PY_WPO_VPN_9089_READY'\n"
END="\nPY_WPO_VPN_9089_READY"

class TestVPN9089Readiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src=SOURCE.read_text(encoding="utf-8")
        assert src.count(BEGIN)==1
        assert src.count(END)==1
        cls.patch=src.split(BEGIN,1)[1].split(END,1)[0]

    def test_pinned_check_is_extended_and_has_journal(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"vpn-setup.sh"
            path.write_text('''#!/usr/bin/env bash
set -Eeuo pipefail
ok=0
for _ in 1 2 3 4 5 6; do
    if curl -4fsS --max-time 3 http://127.0.0.1:9089/healthz |
        grep -q '"ok": true'; then ok=1; break; fi
    sleep 1
done
(( ok == 1 )) || { echo 'VPN health check failed' >&2; exit 3; }
''')
            before=path.read_text()
            proc=subprocess.run(["python3","-c",self.patch,str(path)],
                                capture_output=True,text=True,timeout=6)
            self.assertEqual(proc.returncode,0,proc.stderr)
            new=path.read_text()
            self.assertNotEqual(new,before)
            self.assertIn("$(seq 1 30)",new)
            self.assertIn("systemctl is-active --quiet wpo-node-vpn.service",new)
            self.assertIn("journalctl -u wpo-node-vpn.service --no-pager -n 40",new)
            self.assertIn("127.0.0.1:9089",new)
            self.assertNotIn("for _ in 1 2 3 4 5 6;",new)
            subprocess.run(["bash","-n",str(path)],check=True)

    def test_unfamiliar_upstream_is_not_patched(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"different.sh"
            path.write_text("#!/bin/bash\nexit 0\n")
            result=subprocess.run(["python3","-c",self.patch,str(path)],
                                  capture_output=True,text=True,timeout=6)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("Pinned VPN readiness code changed",result.stderr)
            self.assertEqual(path.read_text(),"#!/bin/bash\nexit 0\n")

    def test_progress_cannot_outrun_actual_checkpoints(self):
        src=SOURCE.read_text(encoding="utf-8")
        wizard=src.split("# WPO_NODE_WIZARD_END",1)[0]
        self.assertIn("node_percent=$node_confirmed",wizard)
        self.assertNotIn("wanted=$((1+elapsed*98/",wizard)
        self.assertNotIn("node_percent=$((node_percent+1))",wizard)
        self.assertIn("while (( node_percent < 100 )); do",wizard)

if __name__=="__main__":
    unittest.main()
