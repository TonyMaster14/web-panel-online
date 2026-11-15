"""End-to-end WPO first-device preallocation for selected multi-node Happ feeds."""
from pathlib import Path
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_happ_prealloc",ROOT/"maintenance/happ/wpo-happ-preallocate-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

BASE=(ROOT/"wpp_subscriptions.py").read_text()
# Create the saved node selection feature from the already-installed Nodes Lab.
BASE=BASE.replace("def mutate(data, request):",
                  "def clean_node_ids(value): return value\n\ndef mutate(data, request):",1)
BASE=BASE.replace("               'connections':specs,\n               'protocols':",
                  "               'connections':specs,'node_ids':request.get('node_ids',['local']),\n               'protocols':",1)
PATCHED=patcher.patch(BASE)
namespace={"__name__":"wpp_subscriptions_patched_test"}
exec(compile(PATCHED,"wpp_subscriptions.py","exec"),namespace)
mutate=namespace["mutate"]
issue=namespace["issue"]
SubscriptionError=namespace["SubscriptionError"]

class PreallocTests(unittest.TestCase):
    def create(self,nodes,max_devices):
        return mutate({"users":[],"subscriptions":[]},{"operation":"create",
            "name":"Home VPN","max_devices":max_devices,
            "node_ids":nodes,"protocols":["vless"]})

    def test_first_hwid_claims_preprovisioned_identity_without_key_rotation(self):
        data,answer=self.create(["local","a"*16,"b"*16],1)
        sub=data["subscriptions"][0]
        self.assertTrue(sub["devices"][0]["preallocated"])
        self.assertEqual(len(data["users"]),1)
        preallocated_id=sub["devices"][0]["id"]
        before_user=data["users"][0].copy()
        self.assertEqual(patcher.patch(PATCHED),PATCHED)
        fresh,result=issue(data,{"token":sub["token"],"hwid":"happ_ABCDEF_123",
                                 "device_name":"My iPhone"})
        device=fresh["subscriptions"][0]["devices"][0]
        self.assertEqual(device["id"],preallocated_id)
        self.assertEqual(device["name"],"My iPhone")
        self.assertNotIn("preallocated",device)
        self.assertEqual(len(fresh["users"]),1)
        self.assertEqual(fresh["users"][0]["id"],before_user["id"])
        self.assertEqual(fresh["users"][0]["secret"],before_user["secret"])
        self.assertEqual(result["users"][0]["secret"],before_user["secret"])
        again,_=issue(fresh,{"token":sub["token"],"hwid":"happ_ABCDEF_123"})
        self.assertEqual(again["users"][0]["secret"],before_user["secret"])
        with self.assertRaises(SubscriptionError) as cm:
            issue(fresh,{"token":sub["token"],"hwid":"happ_DIFFERENT_456"})
        self.assertEqual(cm.exception.status,403)

    def test_unlimited_shared_subscription_has_credentials_before_import(self):
        data,_=self.create(["local","c"*16],0)
        sub=data["subscriptions"][0]
        self.assertEqual(sub["devices"][0]["hwid_hash"],"shared")
        self.assertNotIn("preallocated",sub["devices"][0])
        self.assertEqual(len(data["users"]),1)
        first=data["users"][0]["secret"]
        data,_=issue(data,{"token":sub["token"]})
        self.assertEqual(data["users"][0]["secret"],first)
        self.assertEqual(len(data["users"]),1)

    def test_local_only_subscription_unmodified(self):
        data,_=self.create(["local"],1)
        self.assertFalse(data["subscriptions"][0]["devices"])
        self.assertFalse(data["users"])

    def test_token_rotate_recreates_unbound_device_and_keys(self):
        data,_=self.create(["local","a"*16],1)
        sub=data["subscriptions"][0]
        old_device=sub["devices"][0]["id"]
        old_secret=data["users"][0]["secret"]
        data,_=mutate(data,{"operation":"rotate","id":sub["id"]})
        self.assertEqual(len(data["users"]),1)
        self.assertNotEqual(data["users"][0]["secret"],old_secret)
        self.assertNotEqual(data["subscriptions"][0]["devices"][0]["id"],old_device)
        self.assertTrue(data["subscriptions"][0]["devices"][0]["preallocated"])

if __name__=="__main__":
    unittest.main()
