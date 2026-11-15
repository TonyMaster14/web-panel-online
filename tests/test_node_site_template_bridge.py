"""WPO regression: node templates must stay styled and update live with WEB relay."""
from pathlib import Path
import json
import os
import socket
import subprocess
import tarfile
import tempfile
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/"maintenance/nodes/wpo-node-site-template-fix.sh").read_text()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]


class NodeSiteTemplateBridgeTests(unittest.TestCase):
    def test_repairs_only_additional_node_site_without_touching_vpn(self):
        self.assertIn("systemctl reload caddy.service", SCRIPT)
        self.assertIn("systemctl restart wpo-node-relay.service", SCRIPT)
        self.assertIn('"public_upstream"', SCRIPT)
        self.assertIn('http://127.0.0.1:18082', SCRIPT)
        self.assertIn("bind 127.0.0.1", SCRIPT)
        self.assertIn("file_server", SCRIPT)
        self.assertIn("try_files {path} /index.html", SCRIPT)
        self.assertIn('header Cache-Control "no-store"',SCRIPT)
        self.assertIn('COMMITTED=0',SCRIPT)
        self.assertIn('cp -a "$WORK/Caddyfile.old" "$CADDY"',SCRIPT)
        self.assertIn('cp -a "$WORK/relay.old" "$RELAY"',SCRIPT)
        self.assertNotIn("systemctl restart wpo-node-xray",SCRIPT)
        self.assertNotIn("systemctl restart wpo-node-vpn",SCRIPT)
        self.assertNotIn("systemctl restart wpp-node-agent",SCRIPT)

    def test_actual_caddy_and_relay_show_updated_html_with_inline_styles(self):
        relay=ROOT/"assets/node-prebuilt/tproxy-server-linux-amd64"
        caddy_pkg=ROOT/"assets/caddy-forwardproxy-naive-v2.11.7-naive2.tar.xz"
        if not (relay.exists() and caddy_pkg.exists()):
            self.skipTest("CI node engines absent")
        with tempfile.TemporaryDirectory(prefix="wpo-node-site-live-") as tmp:
            base=Path(tmp)
            with tarfile.open(caddy_pkg,"r:xz") as archive:
                names=[x for x in archive.getmembers() if x.isfile() and x.name.endswith("/caddy")]
                self.assertEqual(len(names),1)
                target=base/"caddy"
                with archive.extractfile(names[0]) as source, target.open("wb") as output:
                    while True:
                        chunk=source.read(1024*1024)
                        if not chunk:break
                        output.write(chunk)
                target.chmod(0o755)
            site=base/"site";site.mkdir()
            index=site/"index.html"
            first=b"<!doctype html><style>body{background:#123456}</style><h1>WPO TEMPLATE FIRST</h1>"
            second=b"<!doctype html><style>body{background:#654321}</style><h1>WPO TEMPLATE UPDATED</h1>"
            index.write_bytes(first)
            (site/"preset-example.webp").write_bytes(b"demo asset")
            local=free_port(); public=free_port(); admin=free_port()
            # The same syntax as the repair installer, just ephemeral ports and dirs.
            caddyfile=base/"Caddyfile"
            caddyfile.write_text(
                "{\n  admin off\n}\n"
                +f":{local} {{\n bind 127.0.0.1\n root * {site}\n"
                +" header Cache-Control \"no-store\"\n try_files {path} /index.html\n file_server\n}\n"
            )
            validation=subprocess.run([str(target),"validate","--config",str(caddyfile),
                                       "--adapter","caddyfile"],capture_output=True,text=True,timeout=10)
            self.assertEqual(validation.returncode,0,validation.stderr)
            profiles=base/"profiles.json"
            profiles.write_text(json.dumps({"profiles":[{
                "name":"node-bootstrap","secret":"1234567890abcdef1234567890abcdef",
                "backend":"127.0.0.1:2398","carrier_mode":"https"
            }]}))
            profiles.chmod(0o400)
            cfg=base/"relay.json"
            cfg.write_text(json.dumps({
                "public_hostname":"node.example.net",
                "listen":f"127.0.0.1:{public}",
                "admin_listen":f"127.0.0.1:{admin}",
                "public_upstream":f"http://127.0.0.1:{local}",
                "profiles_file":str(profiles)
            }))
            processes=[]
            try:
                processes.append(subprocess.Popen(
                    [str(target),"run","--config",str(caddyfile),"--adapter","caddyfile"],
                    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE))
                processes.append(subprocess.Popen(
                    [str(relay),"-config",str(cfg)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE))
                def request(path="/"):
                    req=urllib.request.Request(f"http://127.0.0.1:{public}{path}",
                        headers={"Host":"node.example.net"})
                    with urllib.request.urlopen(req,timeout=2) as response:
                        return response.read(),response.headers
                for i in range(45):
                    if any(x.poll() is not None for x in processes):break
                    try:
                        body,headers=request()
                        if body==first:break
                    except OSError:
                        time.sleep(0.12)
                self.assertEqual(body,first,
                    "WEB relay must return exact site HTML via Caddy upstream")
                self.assertEqual(headers.get("Cache-Control"),"no-store")
                self.assertNotIn("style-src 'self'",headers.get("Content-Security-Policy",""),
                    "CSP from upstream relay may not block inline template styles")
                index.write_bytes(second)
                newer,other_headers=request()
                self.assertEqual(newer,second,
                    "Changing Node Agent index.html must take effect without restarting WEB relay")
                asset,_=request("/preset-example.webp")
                self.assertEqual(asset,b"demo asset")
                self.assertTrue(all(x.poll() is None for x in processes),
                                "Both Caddy and WEB relay must keep running")
            finally:
                for process in processes:
                    if process.poll() is None:process.terminate()
                for process in processes:
                    try:process.communicate(timeout=4)
                    except subprocess.TimeoutExpired:
                        process.kill();process.communicate(timeout=4)


if __name__=="__main__":
    unittest.main()
