"""Controlled POST diagnostic: classify remote 503 while protecting user secrets."""
from pathlib import Path
import importlib.util
from io import BytesIO
from urllib.error import HTTPError
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_happ_post_diagnostic",ROOT/"wpo-happ-post-diagnostic.py")
diag=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

class PostDiagnostic(unittest.TestCase):
    def err(self,code,message):
        cause=HTTPError("https://example.net/wpp-api/v1/federation/sync",
                        code,"upstream problem",None,BytesIO(
                            ('{"ok":false,"message":'+__import__('json').dumps(message)+'}').encode()))
        try:
            raise diag.api.NodeError("Нода не отвечает") from cause
        except diag.api.NodeError as exc:
            return diag.classify_failure(exc)

    def test_xray_restart_failure_is_specific(self):
        result=self.err(503,"VPN provisioning failed: Xray did not become ready")
        self.assertEqual(result,"HTTP 503 — Xray не запустился после применения профиля")

    def test_config_rejection_has_specific_classification_without_secret(self):
        result=self.err(503,"VPN provisioning failed: Xray configuration validation failed: PRIVATE_UUID_012345")
        self.assertEqual(result,"HTTP 503 — Ошибка проверки конфигурации Xray")
        self.assertNotIn("PRIVATE_UUID",result)

    def test_unrecognized_backend_errors_do_not_reveal_remote_body(self):
        result=self.err(503,"API token SECRET_AAHHH and VLESS UUID value")
        self.assertEqual(result,"HTTP 503")
        self.assertNotIn("SECRET",result)

    def test_node_agent_bad_credentials(self):
        result=self.err(401,"Unauthorized")
        self.assertEqual(result,"HTTP 401 — Авторизация ноды не прошла")

if __name__=="__main__":
    unittest.main()
