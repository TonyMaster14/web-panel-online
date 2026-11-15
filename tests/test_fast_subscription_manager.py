"""Regression coverage for fast, safe WPO account creation and Happ HWID claim."""
import ast
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "fast_subs_patch",ROOT/"maintenance/users/wpo-fast-subscription-manager-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

def manager_text(source):
    anchor='cat > "$MANAGER" <<\'PY\'\n'
    return source.split(anchor,1)[1].split("\nPY\n",1)[0]

def command_for_test():
    original=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
    changed=patcher.patch(original)
    assert patcher.patch(changed)==changed
    mgr=manager_text(changed)
    ast.parse(mgr)
    tree=ast.parse(mgr)
    fn=next(f for f in tree.body if isinstance(f,ast.FunctionDef)
            and f.name=="subscription_command")
    return compile(ast.Module(body=[fn],type_ignores=[]),"<wpo-subscription-command>","exec")

CODE=command_for_test()

def invoke(before,after,operation="create",fail_sync=False):
    calls=[]
    result={"ok":True}
    ns={"sys":mock.Mock(stdin=io.StringIO(json.dumps({"operation":operation}))),
        "json":json,"SubscriptionError":ValueError,
        "load":lambda:copy.deepcopy(before),
        "issue_subscription":lambda d,request:(copy.deepcopy(after),result),
        "mutate_subscription":lambda d,request:(copy.deepcopy(after),result),
        "XRAY_TLS_SYNC":"/usr/local/sbin/web-panel-proxy-sync-tls",
        "run":lambda *a,**kw:calls.append("tls"),
        "collect_traffic":lambda *a:calls.append("traffic"),
        "sync_firewall":lambda *a:calls.append("firewall"),
        "sync_xray":lambda *a:(calls.append("xray"),None)[1],
        "save":lambda *a:calls.append("save"),
        "print":lambda *a,**kw:None}
    if fail_sync:
        def error(*a):
            calls.append("xray")
            if calls.count("xray")==1:raise RuntimeError("synthetic Xray failure")
        ns["sync_xray"]=error
    exec(CODE,ns)
    ns["subscription_command"]()
    return calls

def user(uid,protocol="vless",name="Alice"):
    return {"id":uid,"name":name,"enabled":True,
            "protocol":protocol,"secret":"stable-secret","backend_port":443}

class FastSubscriptionTests(unittest.TestCase):
    def test_patch_runs_on_existing_manager_source(self):
        src=(ROOT/"install-panel.sh").read_text()
        original=manager_text(src)
        updated=patcher.patch(original)
        ast.parse(updated)
        self.assertEqual(updated,patcher.patch(updated))
        self.assertIn(patcher.MARKER,updated)
    def test_first_happ_claim_renames_without_restarting_vpn(self):
        before={"users":[user("a",name="Ожидает Happ")]}
        after={"users":[user("a",name="iPhone")]}
        self.assertEqual(invoke(before,after,operation="fetch"),["save"])
    def test_existing_happ_refresh_no_changes_no_reconfiguration(self):
        before={"users":[user("a")],"subscriptions":[{"last_seen":1}]}
        after={"users":[user("a")],"subscriptions":[{"last_seen":2}]}
        self.assertEqual(invoke(before,after,operation="fetch"),["save"])
    def test_vless_create_avoids_nft_firewall_rebuild(self):
        before={"users":[user("a")]}
        after={"users":[user("a"),user("b")]}
        self.assertEqual(invoke(before,after),["traffic","xray","save"])
    def test_existing_hysteria_create_avoids_nft_rebuild(self):
        before={"users":[user("a","hysteria")]}
        after={"users":[user("a","hysteria"),user("b","hysteria")]}
        self.assertEqual(invoke(before,after),["tls","traffic","xray","save"])
    def test_first_hysteria_create_preserves_firewall_activation(self):
        before={"users":[user("a")]}
        after={"users":[user("a"),user("b","hysteria")]}
        self.assertEqual(invoke(before,after),["tls","traffic","firewall","xray","save"])
    def test_native_or_port_change_preserves_firewall_apply(self):
        before={"users":[user("a")]}
        after={"users":[user("a"),user("n","mtproto")]}
        self.assertEqual(invoke(before,after),["traffic","firewall","xray","save"])
    def test_new_happ_credentials_still_require_xray_activation(self):
        before={"users":[user("a")]}
        after={"users":[{**user("a"),"secret":"new-secret"}]}
        self.assertEqual(invoke(before,after,operation="fetch"),["traffic","xray","save"])
    def test_xray_failure_rolls_back_and_does_not_save(self):
        before={"users":[user("a")]}
        after={"users":[user("a"),user("b")]}
        self.assertEqual(invoke(before,after,fail_sync=True),
                         ["traffic","xray","xray"])
    def test_unexpected_source_refused(self):
        with self.assertRaises(ValueError):
            patcher.patch("#!/usr/bin/env python3\npass\n")
if __name__=="__main__":
    unittest.main()
