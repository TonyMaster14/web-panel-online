"""Offline safety tests for authenticated Swedish REALITY 443 node capability."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import wpo_real443_status_advertise_v1 as status


class Real443NodeStatusTests(unittest.TestCase):
    def test_patch_is_idempotent_fail_closed_on_unknown_agent(self):
        original=(
          "from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer\n"
          "class H(BaseHTTPRequestHandler):\n"
          "    def out(self,data,code=200):\n"
          "        return data\n"
          "ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()\n"
        )
        modified=status.patch(original)
        self.assertIn(status.MARKER,modified)
        self.assertIn(status.RUN,modified)
        compile(modified,"agent","exec")
        with self.assertRaises(ValueError):
            status.patch(modified)
        with self.assertRaises(ValueError):
            status.patch("class H: pass\n")

    def test_status_capability_emitted_only_for_verified_upstream(self):
        class H:
            path="/wpp-api/v1/status"
            def out(self,data,code=200):
                return code,data
        env={"H":H}
        exec(status.INJECTION,env)
        with patch.dict(env,{"_wpo_real443_live":lambda:True}):
            code,response=H().out({"ok":True,"capabilities":["node-agent","site-template"]})
        self.assertEqual(code,200)
        self.assertIn("reality-direct-443",response["capabilities"])
        with patch.dict(env,{"_wpo_real443_live":lambda:False}):
            _,response=H().out({"ok":True,"capabilities":["node-agent"]})
        self.assertNotIn("reality-direct-443",response["capabilities"])

    def test_no_unauthorized_capability_in_unrelated_endpoint(self):
        class H:
            path="/wpp-api/v1/profiles"
            def out(self,data,code=200):
                return code,data
        env={"H":H}
        exec(status.INJECTION,env)
        env["_wpo_real443_live"]=lambda:True
        _,response=H().out({"ok":True,"capabilities":["node-agent"]})
        self.assertNotIn("reality-direct-443",response["capabilities"])

    def test_managed_installer_restarts_only_agents_and_keeps_backup(self):
        source=(ROOT/"scripts/wpo-sweden-real443-managed-v1.py").read_text()
        self.assertIn("download_status_patch",source)
        self.assertIn('b/"agent.py"',source)
        self.assertIn("SITE_UNIT",source)
        self.assertIn("probe_site_status()",source)
        self.assertNotIn('restart",REAL443',source)


if __name__=="__main__":
    unittest.main()
