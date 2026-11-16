"""Read-only actual external-port REALITY diagnostics, no generated credentials."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_happ_live_reality",ROOT/"scripts/wpo-happ-live-reality-check.py")
diag=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

class LiveRealityTests(unittest.TestCase):
    def test_resolve_refuses_private_addresses(self):
        with patch.object(diag.socket,"getaddrinfo",return_value=[(None,None,None,None,("127.0.0.1",443))]):
            self.assertEqual(diag.resolve("localhost"),[])

    def test_reject_bad_host(self):
        for host in ("", "a;cat /secret", "123\nfake", "localhost"):
            with self.subTest(host=host),self.assertRaises(diag.CheckError):
                diag.safe_host(host)

    def test_no_provisioning_or_service_restart(self):
        source=(ROOT/"scripts/wpo-happ-live-reality-check.py").read_text()
        for forbidden in ("systemctl restart", "systemctl reload", "write_bytes(",
                "reality.configure(", "save_nodes(", "mutate(", "apt-get", "install.sh"):
            self.assertNotIn(forbidden,source)
        self.assertIn('tunnel(profile,"127.0.0.1")',source)
        self.assertIn("--socks5-hostname",source)
        self.assertIn('"xtls-rprx-vision"',source)
        self.assertIn("204",source)
        self.assertNotIn("print(profile)",source)

    def test_uses_actual_external_and_local_443_not_synthetic_server(self):
        events=[]
        uuid="11111111-1111-4111-8111-111111111111"
        p={"uuid":uuid,"key":"A"*43,"sid":"0123456789abcdef",
           "sni":"www.nvidia.com","fp":"firefox"}
        class FakeProc:
            def poll(self): return None
            def terminate(self): return None
            def wait(self,timeout=None):return 0
        def fake_popen(args,**kwargs):
            with open(args[-1]) as stream:
                data=stream.read()
            import json
            parsed=json.loads(data)
            outbound=parsed["outbounds"][0]
            self.assertEqual(outbound["settings"]["vnext"][0]["address"],"127.0.0.1")
            self.assertEqual(outbound["settings"]["vnext"][0]["port"],443)
            self.assertNotIn("reality",str(parsed["inbounds"]))
            events.append("started")
            return FakeProc()
        fake_result=SimpleNamespace(returncode=0,stdout="204 0.029",stderr="")
        with patch.object(diag,"local_port",return_value=15803), \
             patch.object(diag.subprocess,"Popen",side_effect=fake_popen), \
             patch.object(diag.subprocess,"run",return_value=fake_result) as run:
            with patch.object(diag.time,"sleep",return_value=None):
                result=diag.tunnel(p,"127.0.0.1")
        self.assertEqual(result,["29ms"]*3)
        self.assertEqual(events,["started"])
        self.assertEqual(run.call_count,3)
        self.assertIn("--socks5-hostname",run.call_args.args[0])

if __name__=="__main__":
    unittest.main()
