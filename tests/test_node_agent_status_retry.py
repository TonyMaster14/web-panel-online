"""Regression: a transient Caddy 502 during Node Agent restart must not abort install."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"wpo-node-agent-install-v2.sh").read_text()
START="# wpo-eight-agent-ready-retry-v1:"
END="if ! NODE_STATUS=\"$NODE_STATUS\" python3 - <<'PY_EIGHT_STATUS'"
assert SOURCE.count(START)==1 and SOURCE.count(END)==1
RETRY_BLOCK=START+SOURCE.split(START,1)[1].split(END,1)[0]


class NodeAgentReadiness(unittest.TestCase):
    def run_script(self, fail_count):
        with tempfile.TemporaryDirectory() as work:
            counter=Path(work)/"attempts"
            counter.write_text("0")
            # A realistic mock of the LOCAL agent responding immediately and
            # the PUBLIC Caddy endpoint returning HTTP 502 during the first
            # one or two seconds of backend startup.
            wrapper=r'''
set -euo pipefail
API_KEY=private-test-token
DOMAIN=node.example.net
export RETRY_CTR
systemctl(){ return 0; }
sleep(){ :; }
report(){ :; }
journalctl(){ echo 'mock agent journal'; }
curl(){
  if [[ "$*" == *"http://127.0.0.1:9088/healthz"* ]]; then
    return 0
  fi
  if [[ "$*" == *"/wpp-api/v1/status"* ]]; then
    n="$(cat "$RETRY_CTR")"
    n=$((n+1))
    printf '%s' "$n" > "$RETRY_CTR"
    if (( n <= FAIL_COUNT )); then return 22; fi
    printf '%s' '{"ok":true,"capabilities":["federation","vless","hysteria","web","mtproto","awg20","awg31","naive","mieru"]}'
    return 0
  fi
  echo "Unexpected HTTP endpoint" >&2
  return 99
}
'''+RETRY_BLOCK+'''
printf 'READY=%s ATTEMPTS=%s STATUS=%s\n' "$NODE_API_READY" "$(cat "$RETRY_CTR")" "$NODE_STATUS"
'''
            env=dict(os.environ,RETRY_CTR=str(counter),FAIL_COUNT=str(fail_count))
            result=subprocess.run(["bash","-c",wrapper],env=env,
                    capture_output=True,text=True,timeout=8)
            return result

    def test_caddy_502_twice_then_agent_comes_online(self):
        run=self.run_script(2)
        self.assertEqual(run.returncode,0,run.stdout+"\n"+run.stderr)
        self.assertIn("READY=1 ATTEMPTS=3",run.stdout)
        self.assertIn('"capabilities":',run.stdout)
        self.assertNotIn("private-test-token",run.stdout+run.stderr)

    def test_persistent_agent_failure_refuses_registration_and_shows_diagnostic(self):
        run=self.run_script(99)
        self.assertEqual(run.returncode,4,run.stdout+"\n"+run.stderr)
        self.assertIn("Node Agent не готов",run.stderr)
        self.assertIn("Локальная проверка API",run.stderr)
        self.assertIn("mock agent journal",run.stderr)
        self.assertNotIn("private-test-token",run.stdout+run.stderr)


if __name__=="__main__":
    unittest.main()
