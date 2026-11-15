"""Regression for WPO create-first / prepare-remote-later workflow."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

live=load("wpo-federation-live-create-patch.py","live_previous")
queue=load("wpo-happ-queue-create-patch.py","happ_queue")

def fixture():
    # Exactly the installed create handler indentation.
    return (
        "def create(chosen_nodes, connection_specs):\n"
        "    if True:\n"
        "        if True:\n"
        "            if True:\n"
        +live.AFTER+"\n"
        "# wpo-happ-fast-feed-v1:\n"
        "# wpo-happ-prewarm-on-create-v2:\n"
        "# len(distinct_nodes)>1\n"
        "# wpo_happ_async_feed.enqueue(\n"
    )

class QueueCreateTests(unittest.TestCase):
    def test_gating_migrates_from_existing_live_patch(self):
        raw=fixture()
        ast.parse(raw)
        updated=queue.patch(raw)
        ast.parse(updated)
        self.assertEqual(queue.patch(updated),updated)
        self.assertEqual(updated.count(queue.MARKER),1)
        self.assertNotIn('node_api.API_PREFIX+"/federation/status"',updated)
        self.assertNotIn('node_api.request(node,"GET"',updated)
        self.assertIn('if any(uid not in available_nodes',updated)
        self.assertIn('if any(not available_nodes[uid].get("enabled",True)',updated)
        self.assertIn('wanted_protocols.issubset({"vless","hysteria"})',updated)
        self.assertIn('wpo-happ-prewarm-on-create-v2:',updated)

    def test_remote_api_failure_does_not_prevent_new_user_creation(self):
        src=queue.patch(fixture())
        node_api=SimpleNamespace(load_nodes=lambda _: [
            {"id":"a"*16,"enabled":True,"url":"https://pl.example.net"},
            {"id":"b"*16,"enabled":True,"url":"https://se.example.net"},
        ], request=lambda *a,**kw: self.fail("GET must never block creation"))
        errors=[]
        scope={"node_api":node_api,"NODES_FILE":"fake",
               "create_error":lambda *a: errors.append(a)}
        exec(compile(src,"queue-create-test.py","exec"),scope)
        scope["create"](["local","a"*16,"b"*16],
                        [{"protocol":"vless"},{"protocol":"hysteria"}])
        self.assertEqual(errors,[])

    def test_deleted_or_disabled_node_is_not_accepted(self):
        src=queue.patch(fixture())
        node_api=SimpleNamespace(load_nodes=lambda _: [
            {"id":"a"*16,"enabled":False}
        ])
        errors=[]
        scope={"node_api":node_api,"NODES_FILE":"fake",
               "create_error":lambda *a: errors.append(a)}
        exec(compile(src,"queue-create-test.py","exec"),scope)
        scope["create"](["local","a"*16],[{"protocol":"vless"}])
        self.assertEqual(errors[0][1],409)
        errors.clear()
        scope["create"](["local","b"*16],[{"protocol":"vless"}])
        self.assertEqual(errors[0][1],409)

    def test_missing_async_dependencies_refuse_mutation(self):
        with self.assertRaisesRegex(ValueError,"Missing asynchronous Happ"):
            queue.patch("def x():\n    if True:\n        if True:\n            if True:\n"+live.AFTER)

    def test_installer_main_only_and_restores_previous_panel(self):
        installer=(ROOT/"wpo-happ-queue-create-install.sh").read_text()
        command=subprocess.run(["bash","-n"],input=installer,capture_output=True,text=True)
        self.assertEqual(command.returncode,0,command.stderr)
        for needle in ('! -e /etc/wpp-node-agent/config.json',
                       'cp -a "$BACKUP" "$PANEL"',
                       'systemctl restart tproxy-panel.service',
                       'wpo_happ_preparer.py',
                       'wpo-happ-readonly-diagnostic.py',
                       'wpo-happ-queue-create-patch.py'):
            self.assertIn(needle,installer)
        for forbidden in ("ssh root@","sshpass","curl -k",
                          "systemctl restart caddy.service",
                          "systemctl restart wpo-node-xray.service",
                          "apt-get"):
            self.assertNotIn(forbidden,installer)

if __name__=="__main__":
    unittest.main()
