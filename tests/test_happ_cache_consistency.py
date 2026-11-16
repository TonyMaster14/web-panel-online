"""Happ remote URI cache must not serve all-day-old REALITY values.

Regression covers a historical race: update invalidates caches while a
network worker is still POSTing to a remote node. That worker must not republish
the old SNI/keys, or erase the reservation for the new request.
"""
import unittest
from unittest.mock import patch
import wpo_happ_async_feed as feed

KEY=("nodeid","https://node.invalid","api-hash","extid",("reality",))
NODE={"id":"nodeid","url":"https://node.invalid","token":"[secret]"}
PROTOCOLS=("reality",)

class HappRealityCacheTests(unittest.TestCase):
    def setUp(self):
        with feed.LOCK:
            self.backup=(dict(feed.CACHE),dict(feed.PENDING),dict(feed.FAILURES),feed.CACHE_EPOCH)
            feed.CACHE.clear();feed.PENDING.clear();feed.FAILURES.clear()
            feed.CACHE_EPOCH=0

    def tearDown(self):
        with feed.LOCK:
            old_cache,old_pending,old_failures,epoch=self.backup
            feed.CACHE.clear();feed.CACHE.update(old_cache)
            feed.PENDING.clear();feed.PENDING.update(old_pending)
            feed.FAILURES.clear();feed.FAILURES.update(old_failures)
            feed.CACHE_EPOCH=epoch

    def test_cache_max_age_is_minutes_not_one_day(self):
        self.assertGreater(feed.CACHE_TTL,0)
        self.assertLessEqual(feed.CACHE_TTL,600)

    def test_update_clears_all_cached_links_and_increments_generation(self):
        with feed.LOCK:
            feed.CACHE[KEY]=(float("inf"),("vless://old",))
            feed.FAILURES[KEY]=(float("inf"),"old")
            feed.PENDING[KEY]=feed.CACHE_EPOCH
        feed.invalidate_all()
        self.assertEqual(feed.CACHE,{})
        self.assertEqual(feed.FAILURES,{})
        self.assertEqual(feed.PENDING,{})
        self.assertEqual(feed.CACHE_EPOCH,1)

    def test_late_old_worker_cannot_resurrect_prior_sni_or_clear_new_pending(self):
        with feed.LOCK:
            feed.PENDING[KEY]=0
        feed.invalidate_all()
        with feed.LOCK:
            feed.PENDING[KEY]=1
        with patch.object(feed,"verified_links",return_value=["vless://old"]):
            feed._sync_worker(KEY,None,NODE,"extid","Node",PROTOCOLS,0)
        self.assertNotIn(KEY,feed.CACHE)
        self.assertEqual(feed.PENDING.get(KEY),1)
        with patch.object(feed,"verified_links",return_value=["vless://new"]):
            feed._sync_worker(KEY,None,NODE,"extid","Node",PROTOCOLS,1)
        self.assertEqual(feed.CACHE[KEY][1],("vless://new",))
        self.assertNotIn(KEY,feed.PENDING)

    def test_old_worker_failure_does_not_cause_retry_delay(self):
        with feed.LOCK:
            feed.PENDING[KEY]=0
        feed.invalidate_all()
        def offline(*args,**kwargs):
            raise RuntimeError("stale network exception")
        with patch.object(feed,"verified_links",side_effect=offline):
            feed._sync_worker(KEY,None,NODE,"extid","Node",PROTOCOLS,0)
        self.assertEqual(feed.FAILURES,{})

    def test_obsolete_prewarmer_does_not_republish_prior_profile(self):
        def old_warm(*args,**kwargs):
            feed.invalidate_all()
            return ["vless://old"]
        with patch.object(feed,"verified_links",side_effect=old_warm):
            feed.warm(None,NODE,"extid","Node",PROTOCOLS)
        self.assertEqual(feed.CACHE,{})

    def test_enqueue_starts_new_generation_after_invalidation(self):
        class StubWorkers:
            def __init__(self):
                self.args=[]
            def submit(self,fn,*args):
                self.args.append((fn,args))
        worker=StubWorkers()
        with patch.object(feed,"WORKERS",worker),patch.object(feed,"verified_links",return_value=["vless://new"]):
            self.assertEqual(feed.enqueue(None,NODE,"extid","Node",PROTOCOLS),([],True))
            self.assertEqual(worker.args[0][1][-1],0)
            feed.invalidate_all()
            self.assertEqual(feed.enqueue(None,NODE,"extid","Node",PROTOCOLS),([],True))
            self.assertEqual(worker.args[1][1][-1],1)

    def test_no_remote_credentials_are_printed(self):
        source=__import__("pathlib").Path(feed.__file__).read_text()
        self.assertNotIn("print(uri)",source)
        self.assertNotIn("print(result)",source)
        self.assertNotIn("print(node)",source)

if __name__=="__main__":
    unittest.main()
