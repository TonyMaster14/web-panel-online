"""Regression: successful enrollment survives in-flight /nodes-status refreshes."""
import copy
import importlib.util
from pathlib import Path
import threading
import time
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/"scripts/wpo-node-registration-race-fix.py"
spec=importlib.util.spec_from_file_location("wpo_registry_race_patch",PATCH)
fix=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)


def fixture():
    # The actual controller feature is composed by node-install.sh v1/v13/v20.
    # Keep the critical source anchors in a syntactically valid mini-controller.
    first_enroll,second_enroll=fix.OLD_ENROLL.split("\n",1)
    return (
        "class Handler:\n"
        "    def poll(self):\n"
        "             "+fix.OLD_BEGIN+"\n"
        "             for node in current:\n"
        "                 node['status']='online'\n"
        "                 node['status_detail']='API отвечает'\n"
        "                 node['status_checked_at']=now\n"
        "                 changed=True\n"
        "             "+fix.OLD_SAVE+"\n"
        "             return current\n"
        "    def update(self):\n"
        "                 "+fix.OLD_PENDING+"\n"
        "    def enroll(self):\n"
        "                 with wpo_node_auto.registry_lock:\n"
        "                     "+first_enroll+"\n"
        +second_enroll+"\n"
    )


class FakeRegistry:
    def __init__(self):
        self.rows=[{"id":"existing","url":"https://se.example.net","name":"Sweden",
                    "status":"online","status_checked_at":0}]
        self.writes=0

    def load_nodes(self,path):
        return copy.deepcopy(self.rows)

    def save_nodes(self,path,rows):
        self.rows=copy.deepcopy(rows)
        self.writes+=1


class TestNodeEnrollmentRace(unittest.TestCase):
    def test_patcher_is_idempotent_and_checks_fingerprint(self):
        source=fixture()
        modified,changed=fix.patch(source)
        self.assertTrue(changed)
        self.assertIn(fix.MARKER,modified)
        self.assertNotIn("if changed: node_api.save_nodes(NODES_FILE,current)",modified)
        again,changed=fix.patch(modified)
        self.assertFalse(changed)
        self.assertEqual(again,modified)
        with self.assertRaises(ValueError):
            fix.patch(source.replace("node_api.save_nodes(NODES_FILE,current)",
                                     "print('unsafe change')"))

    def test_controller_alternative_enrollment_handler_still_updates_status(self):
        # Real controllers may have extra registration bookkeeping between
        # saving a node and clearing pending status. Earlier patch rejected it.
        source=fixture().replace(
            'pending.pop(digest,None); wpo_pending_save(pending)',
            'print("newer enrollment bookkeeping")\\n'
            '                 pending.pop(digest,None); wpo_pending_save(pending)'
        )
        # Match a modified implementation without relying on the fixture's
        # indentation across Python source revisions.
        source=fixture().replace(fix.OLD_ENROLL,
            'node_api.save_nodes(NODES_FILE,registered)\\n'
            '                     observed=node_api.load_nodes(NODES_FILE)\\n'
            '                 pending.pop(digest,None); wpo_pending_save(pending)')
        source=source.replace('\\n', '\n')
        # Exactly the mismatch encountered on the installed WPO controller.
        self.assertEqual(source.count(fix.OLD_ENROLL),0)
        modified,changed=fix.patch(source)
        self.assertTrue(changed)
        self.assertIn(fix.MARKER,modified)
        self.assertIn('observed=node_api.load_nodes(NODES_FILE)',modified)
        self.assertIn('current_live=node_api.load_nodes(NODES_FILE)',modified)
        compile(modified,"installed_controller.py","exec")

    def test_pending_handler_version_can_vary(self):
        source=fixture().replace(fix.OLD_PENDING,
              fix.OLD_PENDING.replace('payload=self.json_request(16384);',
                                      'payload=self.json_request(32768);'))
        self.assertNotIn(fix.OLD_PENDING,source)
        modified,changed=fix.patch(source)
        self.assertTrue(changed)
        self.assertIn(fix.MARKER,modified)
        compile(modified,"installed_controller.py","exec")

    def run_poll(self,scenario):
        source,_=fix.patch(fixture())
        registry=FakeRegistry()
        def enrich(current,now):
            current[0]["country_code"]="SE"
            current[0]["name"]="Швеция"
            if scenario=="enroll":
                registry.rows.append({
                    "id":"new","url":"https://cooln.goodarielservice.xyz",
                    "name":"cooln","status":"online","status_checked_at":now})
            if scenario=="rename":
                registry.rows[0]["name"]="Моё имя"
            if scenario=="delete":
                registry.rows.clear()
            return True
        env={
            "node_api":registry,
            "wpo_node_geo":types.SimpleNamespace(enrich=enrich),
            "wpo_node_auto":types.SimpleNamespace(registry_lock=threading.RLock()),
            "time":time,
            "NODES_FILE":"/irrelevant/wpo-registry.json",
            "wpo_pending_load":lambda:{},
        }
        exec(compile(source,"panel.py","exec"),env)
        result=env["Handler"]().poll()
        return registry,result

    def test_newly_registered_node_is_never_lost(self):
        registry,current=self.run_poll("enroll")
        self.assertEqual({r["id"] for r in registry.rows},{"existing","new"})
        self.assertEqual(registry.rows[0]["country_code"],"SE")
        self.assertEqual({r["id"] for r in current},{"existing","new"})
        self.assertEqual(registry.writes,1)

    def test_manual_rename_during_status_check_is_not_clobbered(self):
        registry,_=self.run_poll("rename")
        self.assertEqual(registry.rows[0]["name"],"Моё имя")
        self.assertEqual(registry.rows[0]["country_code"],"SE")

    def test_deleted_node_is_not_resurrected(self):
        registry,current=self.run_poll("delete")
        self.assertEqual(registry.rows,[])
        self.assertEqual(current,[])

    def test_controller_rejects_success_before_registry_confirmation(self):
        source,_=fix.patch(fixture())
        self.assertIn("confirmed=node_api.load_nodes(NODES_FILE)",source)
        self.assertIn("Нода не сохранилась в реестре.",source)
        self.assertIn("with wpo_node_auto.registry_lock:",source)
        self.assertIn("pending.pop(digest,None); wpo_pending_save(pending)",source)


if __name__=="__main__":
    unittest.main()
