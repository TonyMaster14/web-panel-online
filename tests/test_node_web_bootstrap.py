"""Regression tests: WEB Proxy bootstrap registry and interrupted Node Agent 0.4."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
import socket
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
installer=(ROOT/"wpo-node-eight-enable.sh").read_text(encoding="utf-8")
start="python3 - <<'PY_RELAY'\n"
end="\nPY_RELAY"
assert installer.count(start)==1
relay_block=installer.split(start,1)[1].split(end,1)[0]


class RelayBootstrapRegression(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="wpo-relay-bootstrap-")
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.registry=self.base/"profiles.json"
        self.secret_file=self.base/"secret"
        self.secret_file.write_text("abcdef1234567890abcdef1234567890\n")
        # Use exactly the installer-embedded script, remapping its two
        # absolute paths to the disposable temp directory.
        self.source=(relay_block
            .replace("Path('/etc/tproxy-server/profiles.json')",
                     f"Path({str(self.registry)!r})")
            .replace("Path('/etc/wpp-node-vpn/relay-bootstrap-secret')",
                     f"Path({str(self.secret_file)!r})"))

    def run_bootstrap(self, expected=0):
        p=subprocess.run([sys.executable,"-c",self.source],capture_output=True,
                         text=True,timeout=10)
        self.assertEqual(p.returncode,expected,p.stdout+"\n"+p.stderr)
        return p

    def test_fresh_install_writes_real_valid_json(self):
        self.run_bootstrap()
        doc=json.loads(self.registry.read_text())
        self.assertEqual(len(doc["profiles"]),1)
        self.assertEqual(doc["profiles"][0]["name"],"node-bootstrap")
        self.assertTrue(self.registry.read_bytes().endswith(b"\n"))
        self.assertFalse(self.registry.read_bytes().endswith(b"\\n"))

    def test_previous_bug_is_repaired_without_changing_credentials(self):
        original={"profiles":[{"name":"real-web-user","secret":"dont-rotate-secret",
                               "backend":"127.0.0.1:12345","carrier_mode":"https"}]}
        self.registry.write_text(json.dumps(original)+r"\n")
        self.run_bootstrap()
        self.assertEqual(json.loads(self.registry.read_text()),original)
        self.assertTrue(self.registry.read_bytes().endswith(b"\n"))

    def test_existing_valid_registry_stays_byte_identical(self):
        original='{"profiles":[{"name":"custom","secret":"untouched"}]}\n'
        self.registry.write_text(original)
        self.run_bootstrap()
        self.assertEqual(self.registry.read_text(),original)

    def test_unexpected_corruption_is_not_silently_overwritten(self):
        original='{"profiles":[{"name":"real-user",broken!]}'
        self.registry.write_text(original)
        self.run_bootstrap(expected=1)
        self.assertEqual(self.registry.read_text(),original)

    def test_real_precompiled_relay_serves_site_using_exact_bootstrap(self):
        # This catches the real outage: the relay unit may initially be
        # 'active' yet exit seconds later if the JSON ends in a literal \\n.
        executable=ROOT/"assets/node-prebuilt/tproxy-server-linux-amd64"
        if not executable.is_file():
            self.skipTest("precompiled relay not available on this platform")
        self.run_bootstrap()
        root=self.base/"site"
        root.mkdir()
        (root/"index.html").write_text("<html>WPO WEB relay OK</html>")
        def pick_port():
            with socket.socket() as sock:
                sock.bind(("127.0.0.1",0))
                return sock.getsockname()[1]
        public=pick_port()
        admin=pick_port()
        config={
            "public_hostname":"node.example.net",
            "listen":f"127.0.0.1:{public}",
            "admin_listen":f"127.0.0.1:{admin}",
            "public_dir":str(root),
            "profiles_file":str(self.registry),
        }
        path=self.base/"relay.json"
        path.write_text(json.dumps(config))
        with subprocess.Popen([str(executable),"-config",str(path)],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
            success=False
            try:
                for _ in range(45):
                    if process.poll() is not None:
                        break
                    try:
                        request=urllib.request.Request(
                            f"http://127.0.0.1:{public}/",
                            headers={"Host":"node.example.net"})
                        with urllib.request.urlopen(request,timeout=.35) as resp:
                            if b"WPO WEB relay OK" in resp.read():
                                success=True
                                break
                    except (OSError,ValueError):
                        time.sleep(.12)
                if not success:
                    self.fail("Real precompiled WEB relay did not start with "
                              "the installer bootstrap: "+str(process.poll()))
            finally:
                process.terminate()
                try: process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill();process.communicate(timeout=3)

    def test_repeated_initialization_keeps_bootstrap_credential(self):
        self.run_bootstrap()
        original=self.registry.read_bytes()
        self.run_bootstrap()
        self.assertEqual(self.registry.read_bytes(),original)


if __name__=="__main__":
    unittest.main()
