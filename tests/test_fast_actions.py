import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wpo_fast_actions as fast
import wpo_fast_actions_apply as patch

class FastActionsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data={'users':[{'id':'a','protocol':'reality'}]}
        self.registry={'connections':[{'id':'r','protocol':'reality'}]}
        self.ns={key:Mock() for key in ('refresh_connections','collect_traffic','delete','subscription_command','sync_firewall','sync_xray','save','_save_traffic')}
        self.ns.update(load=lambda:copy.deepcopy(self.data),CONNECTIONS='unused',TRAFFIC_LOCK=self.temp.name+'/traffic.lock',
            _xray_traffic=Mock(return_value={'a':{'up':8,'down':50}}),
            _load_traffic=lambda:{'a':{'up':100,'down':40,'raw_up':20,'raw_down':40},'native':{'up':20}},
            wpp_connections=SimpleNamespace(ensure=lambda *args:self.registry,sync_users=Mock(),sync_subscriptions=Mock()))
        self.original=dict(self.ns);fast.install(self.ns)
    def refresh(self,old=None):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.ns['refresh_connections']({'previous_registry':old or {'connections':[]}})
        return output.getvalue()
    def test_xray_connection_skips_full_apply_and_firewall(self):
        self.assertIn('"ok": true',self.refresh())
        self.ns['sync_xray'].assert_called_once()
        self.ns['sync_firewall'].assert_not_called()
        self.original['refresh_connections'].assert_not_called()
    def test_hysteria_keeps_firewall(self):
        self.registry['connections'][0]['protocol']='hysteria'
        self.refresh();self.ns['sync_firewall'].assert_called_once()
    def test_native_and_unknown_requests_keep_original(self):
        self.registry['connections'][0]['protocol']='web'
        self.refresh();self.ns['refresh_connections']()
        self.assertEqual(self.original['refresh_connections'].call_count,2)
    def test_runtime_failure_never_reports_success_or_saves(self):
        self.ns['sync_xray'].side_effect=RuntimeError('rejected')
        with self.assertRaisesRegex(RuntimeError,'rejected'):self.refresh()
        self.ns['save'].assert_not_called()
    def test_deletion_snapshots_xray_and_restores_collector(self):
        self.original['delete'].side_effect=lambda uid:self.ns['collect_traffic'](self.data)
        self.ns['delete']('a')
        saved=self.ns['_save_traffic'].call_args.args[0]
        self.assertEqual(saved['a']['up'],108) # reset counters
        self.assertEqual(saved['a']['down'],50)
        self.assertEqual(saved['native'],{'up':20})
        self.assertIs(self.ns['collect_traffic'],self.original['collect_traffic'])
        self.original['collect_traffic'].assert_not_called()
    def test_native_deletion_keeps_collector(self):
        self.data['users'][0]['protocol']='web'
        self.original['delete'].side_effect=lambda uid:self.ns['collect_traffic'](self.data)
        self.ns['delete']('a');self.original['collect_traffic'].assert_called_once()
    def test_exception_restores_collector(self):
        self.original['subscription_command'].side_effect=RuntimeError('failed')
        with self.assertRaises(RuntimeError):self.ns['subscription_command']()
        self.assertIs(self.ns['collect_traffic'],self.original['collect_traffic'])
    def test_pending_text_override_idempotent(self):
        ui="CSS='old'\n"
        patched=patch.patch_ui(ui)
        ns={};exec(patched,ns)
        self.assertIn('content:none!important',ns['CSS'])
        self.assertEqual(patch.patch_ui(patched),patched)

if __name__=='__main__':unittest.main()
