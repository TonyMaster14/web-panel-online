"""One-command read-only SSH Happ diagnosis, preserving password secrecy."""
import contextlib
import importlib.util
import io
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_fleet_ssh_diagnose",
    ROOT/"scripts/wpo-happ-fleet-ssh-diagnose.py")
diag=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

class FleetSshTests(unittest.TestCase):
    def test_local_and_remote_code_compile(self):
        compile((ROOT/"scripts/wpo-happ-fleet-ssh-diagnose.py").read_text(),
                "wpo-happ-fleet-ssh-diagnose.py","exec")
        compile(diag.REMOTE,"remote-probe.py","exec")

    def test_hosts_only_from_registered_https_addresses(self):
        self.assertEqual(diag.hostname({"url":"https://baby.goodarielservice.xyz"}),
                         "baby.goodarielservice.xyz")
        for uri in ("http://example.com","https://-attacker.example",
                    "https://root:secret@example.com","", "https://localhost"):
            with self.subTest(uri=uri),self.assertRaises(ValueError):
                diag.hostname({"url":uri})

    def test_ssh_does_not_request_a_password_in_code_or_expose_secret(self):
        fake=SimpleNamespace(returncode=0,stdout='{"ok":true,"client_secret":"sensitive-data"}\n')
        capture=io.StringIO()
        with patch.object(diag.subprocess,"run",return_value=fake) as run, \
             contextlib.redirect_stdout(capture):
            result=diag.ssh_check("swejeep.goodarielservice.xyz",["a"*64])
        argv=run.call_args.args[0]
        self.assertIn("-T",argv)
        self.assertIn("StrictHostKeyChecking=ask",argv)
        self.assertTrue(any(x.startswith("root@") for x in argv))
        self.assertNotIn("sshpass",str(argv))
        self.assertNotIn("sensitive-data",capture.getvalue())
        self.assertEqual(result["client_secret"],"sensitive-data")

    def test_diagnostic_does_not_modify_profiles_or_restart_daemons(self):
        src=(ROOT/"scripts/wpo-happ-fleet-ssh-diagnose.py").read_text()
        for forbidden in ("systemctl restart","systemctl reload",
            "sshpass", "curl -k", "StrictHostKeyChecking=no", "api.request(",
            "atomic_json(", "xray.apply(", "write_text('/etc/"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,src)
        self.assertIn("TemporaryDirectory(",src)
        self.assertIn("flow':'xtls-rprx-vision",src)
        self.assertIn("REALITY подписок",src)
        self.assertIn("HAProxy→Xray",src)
        self.assertIn("SSH-пароли" if "SSH-пароли" in src else "Пароли, UUID",src)

    def test_real_haproxy_regex_matches_correct_target(self):
        router='''frontend wpo_tls
    use_backend reality if { req.ssl_sni -i www.nvidia.com }
backend reality
    server reality 127.0.0.1:19444
backend website
    server caddy 127.0.0.1:19443
'''
        sni="www.nvidia.com"
        pat=(r'(?im)^\s*use_backend\s+([a-zA-Z0-9_-]+)\s+if\s+\{\s*req\.ssl_sni\s+-i\s+'
             +re.escape(sni)+r'\s*\}')
        matched=re.search(pat,router)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.group(1),"reality")

if __name__=="__main__":
    unittest.main()
