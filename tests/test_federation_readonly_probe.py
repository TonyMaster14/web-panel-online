"""No side effects for the WPO node federation VLESS preflight diagnostic."""
import importlib.util
import io
import json
from pathlib import Path
from unittest import TestCase, mock
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_federation_probe",ROOT/"maintenance/nodes/wpo-node-federation-readonly-probe.py")
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class NodeProbeTests(TestCase):
    def test_invalid_profile_cannot_create_a_real_identity(self):
        source=(ROOT/"maintenance/nodes/wpo-node-federation-readonly-probe.py").read_text()
        self.assertIn('b\'{"external_id":"invalid"',source)
        self.assertIn('"run","-test","-config"',source)
        self.assertIn("TemporaryDirectory(",source)
        self.assertNotIn('"/federation/delete"',source)
        self.assertNotIn('"/federation/purge"',source)
        self.assertNotIn("systemctl restart",source)
    def test_local_400_proves_safe_routing(self):
        class FakeOpener:
            def open(self, request, timeout):
                assert request.data
                raise HTTPError(request.full_url,400,"Bad Request",
                                {},io.BytesIO(json.dumps({
                                     "ok":False,"message":"Invalid federation ID"
                                }).encode()))
        fake=FakeOpener()
        with (mock.patch.object(probe,"build_opener",return_value=fake),
              mock.patch("builtins.print")):
            self.assertEqual(probe.safe_status("http://127.0.0.1:9089/wpp-api/v1/federation/sync",
                                               "test-token"),400)
