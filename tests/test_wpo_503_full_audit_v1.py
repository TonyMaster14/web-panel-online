"""Synthetic regression for a single comprehensive read-only WPO 503 audit."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/wpo-503-full-audit-v1.py"
spec=importlib.util.spec_from_file_location("wpo_503_full_audit_v1",SCRIPT)
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class FullAuditTests(unittest.TestCase):
    def setUp(self):
        audit.issues.clear()
        self.addCleanup(audit.issues.clear)

    def test_node_probe_only_invalid_id_posts(self):
        calls=[]
        class BadStatus(Exception):
            code=400
        class API:
            API_PREFIX="/wpp-api/v1"
            @staticmethod
            def request(node,method,path,payload=None,timeout=10):
                calls.append((method,path,payload))
                if method=="POST":
                    try:raise BadStatus("bad")
                    except BadStatus as ex:raise ValueError("handled") from ex
                if path.endswith("/reality"):
                    return {"ok":True,"profile":{"managed_reality":"remna-443-mirror-v1"}}
                return {"ok":True,"capabilities":["federation","reality","vless","hysteria"]}
        nodes=[{"id":"aaaaaaaaaaaaaaaa","country_code":"SE","enabled":True}]
        capabilities,enabled,totals=audit.check_nodes(API,nodes)
        self.assertEqual(totals["post_400"],1)
        self.assertEqual(totals["get_ok"],3)
        posts=[c for c in calls if c[0]=="POST"]
        self.assertEqual(len(posts),1)
        self.assertEqual(posts[0][2]["external_id"],"BAD_ID_NO_WRITE")
        self.assertEqual(posts[0][1],"/wpp-api/v1/federation/sync")

    def test_subscription_registry_audit_does_not_modify_data(self):
        import json
        data={
            "subscriptions":[
                {"id":"1234567890abcdef","token":"f"*64,"name":"test","enabled":True,
                 "node_ids":["aaaaaaaaaaaaaaaa"],"max_devices":0,
                 "connections":[{"id":"real","protocol":"reality"}],
                 "devices":[]}
            ],
            "users":[]
        }
        import copy
        orig=copy.deepcopy(data)
        class FakeSubs:
            @staticmethod
            def issue(data,request):
                data["users"].append({"in_memory_only":True})
                return data,{"ok":True}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"users.json"
            path.write_text(json.dumps(data))
            with patch.object(audit,"DB",path):
                jobs=audit.check_registry(FakeSubs,
                        [{"id":"aaaaaaaaaaaaaaaa","enabled":True}],
                        {"aaaaaaaaaaaaaaaa":{"reality"}},
                        {"aaaaaaaaaaaaaaaa":True},None)
            self.assertEqual(json.loads(path.read_text()),orig)
        self.assertEqual(len(jobs),1)

    def test_removed_node_detected_without_exposing_token(self):
        import json
        item={"id":"1234567890abcdef","token":"f"*64,"enabled":True,
              "node_ids":["missing-node"],"max_devices":1,
              "connections":[{"id":"vless","protocol":"vless"}],"devices":[]}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"users.json"
            path.write_text(json.dumps({"subscriptions":[item],"users":[]}))
            with patch.object(audit,"DB",path):
                audit.check_registry(None,[],{}, {},None)
        self.assertTrue(any(x[1]=="STALE_NODE" for x in audit.issues))
        self.assertFalse(any(item["token"] in repr(x) for x in audit.issues))

    def test_no_valid_post_or_mutating_service_operations_in_script(self):
        s=SCRIPT.read_text()
        self.assertIn("BAD_ID_NO_WRITE",s)
        self.assertNotIn('systemctl","restart"',s)
        self.assertNotIn('systemctl","stop"',s)
        self.assertNotIn('systemctl","disable"',s)
        self.assertNotIn('"/federation/delete"',s)
        self.assertNotIn('"/federation/purge"',s)


if __name__=="__main__":unittest.main()
