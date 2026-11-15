"""Regression for the Node Agent relay readiness race on slow systemd/Caddy reloads.

The node installer downloads a specific pinned eight-engine script and injects
longer, bounded startup checks into a *temporary* copy. Exercise that exact
embedded patch against the pinned call sites without touching host services.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT/"nodes/wpo-node-agent-install-v2.sh"
OUTER='python3 - "$EIGHT_SETUP" <<'+"'PY_WPO_RELAY_READY_RETRY'"+'\n'
OUTER_END='\nPY_WPO_RELAY_READY_RETRY'
INNER='python3 - "$TEMP/site-template-fix.sh" <<'+"'PY_WPO_SITE_READY_RETRY'"+'\n'
INNER_END='\nPY_WPO_SITE_READY_RETRY'


class TestRelayWaitPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        content=AGENT.read_text(encoding="utf-8")
        assert content.count(OUTER)==1, "Missing pinned eight-engine adjustment"
        assert content.count(OUTER_END)==1
        cls.outer=content.split(OUTER,1)[1].split(OUTER_END,1)[0]

    def test_eight_engine_and_site_bridge_use_bounded_waits(self):
        with tempfile.TemporaryDirectory(prefix="wpo-relay-patch-") as td:
            eight=Path(td)/"eight.sh"
            eight.write_text(
                '#!/usr/bin/env bash\n'
                'set -Eeuo pipefail\n'
                'for attempt in 1 2 3 4 5 6 7 8 9 10; do\n'
                '    if systemctl is-active --quiet wpo-node-relay.service; then break; fi\n'
                '    sleep 0.2\n'
                'done\n'
                'bash -n "$TEMP/site-template-fix.sh"\n'
                'bash "$TEMP/site-template-fix.sh"\n',
                encoding="utf-8",
            )
            result=subprocess.run(
                ["python3","-c",self.outer,str(eight)],
                capture_output=True,text=True,timeout=6,
            )
            self.assertEqual(result.returncode,0,result.stderr)
            new=eight.read_text()
            self.assertIn('for attempt in $(seq 1 60); do',new)
            self.assertIn('    sleep 0.5\n',new)
            self.assertEqual(new.count(INNER),1)
            subprocess.run(["bash","-n",str(eight)],check=True)

            inner=new.split(INNER,1)[1].split(INNER_END,1)[0]
            bridge=Path(td)/"bridge.sh"
            bridge.write_text(
                '#!/usr/bin/env bash\n'
                'for _ in 1 2 3 4 5 6 7 8 9 10; do\n'
                '    curl -4fsS --noproxy "*" --max-time 2 http://127.0.0.1:18082/ || :\n'
                '    sleep 0.2\n'
                'done\n'
                'for _ in 1 2 3 4 5 6 7 8 9 10; do\n'
                '    curl -4fsS --noproxy "*" --max-time 2 http://127.0.0.1:8080/ || :\n'
                '    sleep 0.2\n'
                'done\n',
                encoding="utf-8",
            )
            result=subprocess.run(
                ["python3","-c",inner,str(bridge)],
                capture_output=True,text=True,timeout=6,
            )
            self.assertEqual(result.returncode,0,result.stderr)
            updated=bridge.read_text()
            self.assertEqual(updated.count('for _ in $(seq 1 60); do'),2)
            self.assertEqual(updated.count('sleep 0.5'),2)
            self.assertNotIn('curl -4fsS --noproxy',updated)
            self.assertEqual(updated.count('curl -4fs --noproxy'),2)
            subprocess.run(["bash","-n",str(bridge)],check=True)

    def test_pinned_layout_change_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="wpo-relay-reject-") as td:
            candidate=Path(td)/"invalid.sh"
            candidate.write_text("#!/usr/bin/env bash\nexit 0\n")
            result=subprocess.run(
                ["python3","-c",self.outer,str(candidate)],
                capture_output=True,text=True,timeout=6,
            )
            self.assertNotEqual(result.returncode,0)
            self.assertIn("Pinned relay startup layout changed",result.stderr)


if __name__=="__main__":
    unittest.main()
