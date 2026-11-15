"""Real WPO prebuilt WEB relay startup on both initial and live-site configurations.

The node uses this shipped binary (not the source built by the older smoke test).
Exercise it with precisely the Node Agent 0.4 JSON profile structure.
"""
import contextlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/"assets/node-prebuilt/tproxy-server-linux-amd64"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]


class WPOSite(BaseHTTPRequestHandler):
    def do_GET(self):
        body=b"WPO NODE SITE CONTENT"
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):
        pass


class TestNodeRelayStartup(unittest.TestCase):
    def test_prebuilt_initial_and_live_site_restart(self):
        self.assertTrue(BINARY.exists(),str(BINARY))
        self.assertTrue(BINARY.stat().st_mode & 0o111,str(BINARY))
        with tempfile.TemporaryDirectory(prefix="wpo-relay-live-") as location:
            root=Path(location)
            site=root/"site"
            site.mkdir(mode=0o755)
            (site/"index.html").write_bytes(b"WPO NODE SITE CONTENT")
            profiles=root/"profiles.json"
            profiles.write_text(json.dumps({"profiles":[{
                "name":"node-bootstrap",
                "secret":secrets.token_hex(16),
                "backend":"127.0.0.1:2398",
                "carrier_mode":"https",
            }]}))
            profiles.chmod(0o400)
            port,admin,upstream=free_port(),free_port(),free_port()
            config=root/"config.json"
            host="baba.goodarielservice.xyz"

            def config_write(bridge):
                data={
                    "public_hostname":host,
                    "listen":f"127.0.0.1:{port}",
                    "admin_listen":f"127.0.0.1:{admin}",
                    "profiles_file":str(profiles),
                }
                if bridge:
                    data["public_upstream"]=f"http://127.0.0.1:{upstream}"
                else:
                    data["public_dir"]=str(site)
                config.write_text(json.dumps(data))
                config.chmod(0o640)

            def try_relay(label):
                check=subprocess.run(
                    [str(BINARY),"-config",str(config),"-check"],
                    text=True,capture_output=True,timeout=6,
                )
                self.assertEqual(check.returncode,0,
                                 f"{label} relay config invalid: {check.stderr}")
                process=subprocess.Popen(
                    [str(BINARY),"-config",str(config)],
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                )
                url=f"http://127.0.0.1:{port}/"
                try:
                    outcome=None
                    for attempt in range(45):
                        if process.poll() is not None:
                            break
                        req=urllib.request.Request(url,headers={"Host":host})
                        try:
                            with urllib.request.urlopen(req,timeout=1) as response:
                                outcome=response.read(65536)
                            break
                        except Exception:
                            time.sleep(0.15)
                    if outcome is None:
                        process.kill()
                        details=process.communicate(timeout=4)[0].decode(errors="replace")
                        self.fail(f"{label}: prebuilt relay failed to accept HTTP on {port}:\n"+details)
                    self.assertIn(b"WPO NODE SITE CONTENT",outcome)
                finally:
                    process.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=3)
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=3)
                    if process.stdout:
                        process.stdout.close()

            config_write(False)
            try_relay("initial static node site")

            server=ThreadingHTTPServer(("127.0.0.1",upstream),WPOSite)
            worker=threading.Thread(target=server.serve_forever,daemon=True)
            worker.start()
            try:
                config_write(True)
                try_relay("post-install live site bridge")
            finally:
                server.shutdown()
                server.server_close()


if __name__=="__main__":
    unittest.main()
