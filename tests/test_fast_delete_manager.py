"""Regression checks for safely accelerated WPO direct VPN removal."""
import ast
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("fast_delete_patch",ROOT/"wpo-fast-delete-manager-patch.py")
patcher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

def manager_text():
    source=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
    return source.split('cat > "$MANAGER" <<\'PY\'\n',1)[1].split("\nPY\n",1)[0]

def compiled_delete():
    original=manager_text()
    changed=patcher.patch(original)
    assert patcher.patch(changed)==changed
    tree=ast.parse(changed)
    definition=next(x for x in tree.body if isinstance(x,ast.FunctionDef)
                    and x.name=="delete")
    return compile(ast.Module(body=[definition],type_ignores=[]),"<fast-delete>","exec")

DELETE=compiled_delete()

def profile(uid,protocol="vless",enabled=True,subscription_id=None):
    result={"id":uid,"protocol":protocol,"enabled":enabled,"secret":"secret-"+uid}
    if subscription_id is not None:
        result["subscription_id"]=subscription_id
    return result

def run_delete(users,uid,*,fail_on_xray=False):
    before={"users":copy.deepcopy(users),"subscriptions":[]}
    events=[]
    def on_xray(data):
        events.append(("xray",[u["id"] for u in data["users"]]))
        if fail_on_xray and len([e for e in events if e[0]=="xray"])==1:
            raise RuntimeError("fake Xray error")
    namespace={
       "load":lambda:copy.deepcopy(before),
       "collect_traffic":lambda d:events.append(("traffic",)),
       "sync_firewall":lambda d:events.append(("firewall",[u["id"] for u in d["users"]])),
       "sync_xray":on_xray,
       "save":lambda d:events.append(("save",[u["id"] for u in d["users"]])),
       "apply":lambda d,restart,previous:events.append(("apply",[u["id"] for u in d["users"]])),
       "copy":copy,
       "delete_primary_proxy":lambda:events.append(("primary",))
    }
    exec(DELETE,namespace)
    try:
        result=namespace["delete"](uid)
    except Exception as exc:
        return exc,events
    return result,events

class FastDelete(unittest.TestCase):
    def test_fast_vless_delete_does_not_rebuild_nft(self):
        result,events=run_delete([profile("one"),profile("two")],"two")
        self.assertIs(result,True)
        self.assertEqual(events,[("traffic",),("xray",["one"]),("save",["one"])])

    def test_hysteria_delete_with_other_hysteria_also_fast(self):
        result,events=run_delete([profile("one","hysteria"),profile("two","hysteria")],"two")
        self.assertIs(result,True)
        self.assertNotIn("firewall",[x[0] for x in events])
        self.assertNotIn("apply",[x[0] for x in events])

    def test_last_hysteria_delete_rebuilds_firewall(self):
        result,events=run_delete([profile("one","vless"),profile("two","hysteria")],"two")
        self.assertIs(result,True)
        self.assertEqual(events,[("traffic",),("firewall",["one"]),("xray",["one"]),("save",["one"])])

    def test_existing_non_vpn_user_keeps_standard_deletion(self):
        result,events=run_delete([profile("one","mtproto")],"one")
        self.assertIs(result,True)
        self.assertEqual(events,[("traffic",),("save",[]),("apply",[])])

    def test_subscription_user_cannot_be_deleted_directly(self):
        result,events=run_delete([profile("one","vless",subscription_id="sub")],"one")
        self.assertIsInstance(result,RuntimeError)
        self.assertEqual(events,[])

    def test_primary_route_untouched(self):
        result,events=run_delete([profile("one")],"primary")
        self.assertEqual(events,[("primary",)])

    def test_unknown_user_is_idempotent(self):
        result,events=run_delete([profile("one")],"missing")
        self.assertIs(result,False)
        self.assertEqual(events,[("traffic",)])

    def test_apply_failure_restores_without_committing_deleted_profile(self):
        result,events=run_delete([profile("one"),profile("two")],"two",fail_on_xray=True)
        self.assertIsInstance(result,RuntimeError)
        self.assertEqual(events,[("traffic",),("xray",["one"]),("xray",["one","two"])])
        self.assertFalse(any(x[0]=="save" for x in events))

    def test_unsupported_source_refused(self):
        with self.assertRaises(ValueError):
            patcher.patch("def delete(uid):\n    return 1\n")

if __name__=="__main__":
    unittest.main()
