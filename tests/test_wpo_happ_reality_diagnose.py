"""Read-only fleet diagnostics: do not print VPN credentials or modify files."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_happ_diag",ROOT/"scripts/wpo-happ-reality-diagnose.py")
diag=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

class HappReadOnlyDiagnosticsTests(unittest.TestCase):
    def test_profile_only_emits_sni_and_fp(self):
        details={"sni":"www.nvidia.com","fingerprint":"firefox",
                 "private_key":"DO_NOT_PRINT","public_key":"DO_NOT_PRINT",
                 "short_id":"DO_NOT_PRINT","uuid":"DO_NOT_PRINT"}
        self.assertEqual(diag.concise(details),("www.nvidia.com","firefox"))
        self.assertEqual(diag.concise(dict(details,sni="evil;touch /tmp/x"))[0],"unknown")

    def test_hostname_uses_registered_node_not_reality_decoy(self):
        self.assertEqual(diag.hostname("https://poland.example.net"),"poland.example.net")
        self.assertEqual(diag.hostname("https://node.example.net:443"),"node.example.net")
        with self.assertRaises(ValueError):
            diag.hostname("")

    def test_no_private_addresses_are_probed(self):
        local=("127.0.0.1",443)
        fake=[(None,None,None,None,local)]
        with patch.object(diag.socket,"getaddrinfo",return_value=fake):
            self.assertEqual(diag.tcp_probe("localhost"),"DNS/IP")

    def test_api_credentials_and_keys_are_not_in_report(self):
        node={"name":"Poland","url":"https://poland.example.org",
              "token":"SECRET_BEARER_NEVER_PRINT"}
        class FakeApi:
            @staticmethod
            def request(n,method,path,timeout=8):
                self.assertEqual(n["token"],"SECRET_BEARER_NEVER_PRINT")
                self.assertEqual(method,"GET")
                return {"ok":True,"profile":{"sni":"www.nvidia.com",
                    "fingerprint":"firefox","private_key":"NEVER_PRINT"}}
        with patch.object(diag,"tcp_probe",return_value="42ms"):
            result=diag.scan_node(node,FakeApi())
        self.assertEqual(result["tcp"],["42ms"]*3)
        self.assertEqual(result["sni"],"www.nvidia.com")
        self.assertNotIn("SECRET_BEARER",str(result))
        self.assertNotIn("NEVER_PRINT",str(result))

    def test_unreachable_api_does_not_fabricate_reality_ping(self):
        node={"name":"N/A","url":"https://unavailable.example.org"}
        class FakeApi:
            @staticmethod
            def request(*args,**kwargs):
                raise ConnectionError("TOKEN_SECRET")
        with patch.object(diag,"tcp_probe",return_value="timeout"):
            result=diag.scan_node(node,FakeApi())
        self.assertEqual(result["api"],"ERROR")
        self.assertEqual(result["sni"],"unknown")
        self.assertNotIn("TOKEN_SECRET",str(result))

    def test_source_has_no_destructive_system_actions(self):
        source=(ROOT/"scripts/wpo-happ-reality-diagnose.py").read_text()
        for token in ("systemctl restart","subprocess.run(","shutil.rmtree",
                      "write_text(","save_nodes(","configure("):
            self.assertNotIn(token,source)
        self.assertIn("TCP 443 ≠",source)

if __name__=="__main__":
    unittest.main()
