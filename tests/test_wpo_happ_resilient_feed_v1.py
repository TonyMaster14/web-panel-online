"""Regression tests: WPO Happ rescue with actual code execution and safety."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import wpo_happ_resilient_feed_v1 as rescue
import wpo_happ_async_feed as feed


def fixture_source():
    return '''import sys
class Handler:
    def __init__(self, local, remote, pending):
        self.local=local
        self.remote=remote
        self.pending=pending
        self.status=200
        self.error=None
    def send_data(self, message, status, headers=None):
        self.status=status
        self.error=message
    def serve_subscription(self,token):
        chosen=["local","remote"]
        lines=list(self.local)
        remote_nodes=["remote"]
        remote_id="redacted"
        wanted=["reality"]
        remote_links,pending=wpo_happ_async_feed.collect(None,remote_nodes,remote_id,wanted)
        if True:
                if pending:
                    self.send_data("Подписка готовится. Повторите обновление.",503,headers={"Retry-After":"2"}); return
                lines.extend(remote_links)
        distinct_nodes={"node-a" for _ in lines}
        failover=bool(lines) and len(chosen)>1
        return lines,failover
    def serve_direct_profile(self,token):
        return "untouched"
'''

class RescueTests(unittest.TestCase):
    def new_handler(self,local,remote,pending):
        src=rescue.patch_panel(fixture_source())
        module=types.ModuleType("temp_wpo_happ")
        api=types.SimpleNamespace(collect=lambda *a,**kw:(remote,pending))
        module.__dict__["wpo_happ_async_feed"]=api
        exec(compile(src,"panel.py","exec"),module.__dict__)
        return module.Handler(local,remote,pending)

    def test_normal_single_remote_without_pending(self):
        handler=self.new_handler([],["vless://verified"],0)
        result=handler.serve_subscription("token")
        self.assertEqual(result[0],["vless://verified"])
        self.assertEqual(handler.status,200)

    def test_remote_only_pending_returns_honest_503_not_empty_feed(self):
        handler=self.new_handler([],[],1)
        self.assertIsNone(handler.serve_subscription("token"))
        self.assertEqual(handler.status,503)

    def test_local_and_pending_remote_returns_local_200(self):
        handler=self.new_handler(["vless://local"],[],1)
        result=handler.serve_subscription("token")
        self.assertEqual(result[0],["vless://local"])
        self.assertEqual(handler.status,200)

    def test_remote_only_multi_partially_ready_returns_verified(self):
        handler=self.new_handler([],["vless://verified"],1)
        result=handler.serve_subscription("token")
        self.assertEqual(result[0],["vless://verified"])
        self.assertEqual(handler.status,200)

    def test_failover_counts_real_hosts_not_selected_ghost_nodes(self):
        handler=self.new_handler([],["vless://one"],1)
        result=handler.serve_subscription("token")
        self.assertFalse(result[1], "No auto switch for only one returned host")
        self.assertIn("len(distinct_nodes)>1",rescue.patch_panel(fixture_source()))

    def test_existing_modes_fingerprint_and_domain_stay_untouched(self):
        before=fixture_source()
        after=rescue.patch_panel(before)
        self.assertIn('return "untouched"',after)
        self.assertEqual(after.count("class Handler:"),1)
        self.assertNotIn("wpo_real443",after)
        self.assertEqual(after.count("lines.extend(remote_links)"),1)
        with self.assertRaises(ValueError):
            rescue.patch_panel(after)
        with self.assertRaises(ValueError):
            rescue.patch_panel("print('unknown')")

    def test_feed_patch_preserves_validation_and_retries_without_identifiers(self):
        orig=(ROOT/"src/wpo_happ_async_feed.py").read_text()
        patched=rescue.patch_feed(orig)
        compile(patched,"feed.py","exec")
        self.assertIn("RETRY_DELAY = 8",patched)
        self.assertIn("def verified_links(",patched)
        self.assertIn("def collect(",patched)
        self.assertIn('"wpo async sync failed:"',patched)
        self.assertNotIn('key[0], error_kind',patched)
        with self.assertRaises(ValueError):rescue.patch_feed(patched)

    def test_unchanged_node_links_are_still_required_to_be_eligible(self):
        class Fake:
            API_PREFIX="/wpp-api/v1"
            class NodeError(ValueError):pass
            @classmethod
            def request(cls,node,method,path,payload,timeout):
                return {"ok":True,"profiles":[{"protocol":"reality",
                         "link":"vless://00000000-0000-4000-8000-000000000000@wrong.example:443?security=reality"}]}
        with self.assertRaises(Fake.NodeError):
            feed.verified_links(Fake,{"url":"https://right.example"},
                   "opaque","Name",["reality"],timeout=1)

    def test_installer_has_no_live_node_or_subscription_mutations(self):
        script=(ROOT/"scripts/wpo-happ-rescue-v1.py").read_text()
        self.assertIn("def rollback():",script)
        self.assertIn("def preview():",script)
        self.assertIn("original_sha256",script)
        self.assertNotIn('systemctl","restart","wpo-node-',script)
        self.assertNotIn('"/federation/sync"',script)
        self.assertNotIn("users.json",script)


if __name__=="__main__":
    unittest.main()
