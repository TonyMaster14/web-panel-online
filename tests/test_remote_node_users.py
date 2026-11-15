"""Controller integration: native remote user profiles are real node links."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import wpo_node_remote as remote
import wpo_node_remote_patch as patch

NODE = {"id": "a"*16, "name": "Швеция", "enabled":True,
        "url":"https://se.example.net", "api_key":"secret"}
CAPS = ["federation","vless","hysteria","web","mtproto",
        "awg20","awg31","naive","mieru"]


class RemoteNodeUserTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory(prefix="wpo-remote-users-")
        self.addCleanup(d.cleanup)
        patcher=mock.patch.object(remote,"DATA",Path(d.name)/"users.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.status=mock.patch.object(remote.nodes,"request",
            return_value={"ok":True,"capabilities":CAPS})
        # POST and GET share the same authenticated request helper; the
        # side-effect mock below handles both paths.
        self.status.start()
        self.addCleanup(self.status.stop)
        self.sync=mock.patch.object(remote.nodes,"request",side_effect=self.generate_request)
        self.mock_sync=self.sync.start()
        self.addCleanup(self.sync.stop)
        self.delete=mock.patch.object(remote.nodes,"delete_profile",
                                      return_value={"ok":True,"deleted":True})
        self.mock_delete=self.delete.start()
        self.addCleanup(self.delete.stop)

    @staticmethod
    def generate_request(node,method,path,payload=None,timeout=0):
        if method=="GET":
            return {"ok":True,"capabilities":CAPS}
        assert method=="POST" and path.endswith("/federation/sync")
        p=payload["protocols"][0]
        if p in ("awg20","awg31"):
            return {"ok":True,"profiles":[{"protocol":p,"config":"[Interface]\nPrivateKey = test"}]}
        return {"ok":True,"profiles":[{"protocol":p,"link":
                       "https://t.me/proxy?server=se.example.net&secret=example"}]}

    def test_six_real_native_protocols_can_be_provisioned(self):
        for p in sorted(remote.NATIVE):
            with self.subTest(protocol=p):
                result=remote.create("a"*16,"Sweden "+p,p,[NODE])
                self.assertEqual(result["protocol"],p)
                self.assertEqual(result["node_id"],"a"*16)
        self.assertEqual(len(remote.load()["users"]),6)
        self.assertEqual(self.mock_sync.call_count,12)

    def test_no_nonexistent_node_or_cached_only_capability(self):
        with self.assertRaises(ValueError):
            remote.create("b"*16,"Unknown","web",[NODE])
        with mock.patch.object(remote.nodes,"request",
              return_value={"ok":True,"capabilities":["site-template"]}):
            with self.assertRaisesRegex(remote.nodes.NodeError,"не готов"):
                remote.create("a"*16,"Offline","awg20",[NODE])
        self.assertFalse(remote.DATA.exists())

    def test_native_awg_config_can_be_downloaded_only_from_admin_route(self):
        item=remote.create("a"*16,"Amnezia","awg31",[NODE])
        config,filename=remote.config(item["id"])
        self.assertIn("[Interface]",config)
        self.assertTrue(filename.endswith(".conf"))
        self.assertIn("Скачать конфигурацию .conf",remote.cards("/panel-demo","csrf"))
        self.assertNotIn('data-remote-copy="[Interface]',remote.cards("/panel-demo","csrf"))

    def test_delete_calls_real_node_before_removing_registry(self):
        item=remote.create("a"*16,"Telegram","mtproto",[NODE])
        self.assertTrue(remote.remove(item["id"],[NODE]))
        self.assertEqual(remote.load()["users"],[])
        self.mock_delete.assert_called_once()
        self.assertEqual(self.mock_delete.call_args.args[1],
                         self.mock_sync.call_args.kwargs["payload"]["external_id"]
                         if "payload" in self.mock_sync.call_args.kwargs
                         else self.mock_sync.call_args.args[3]["external_id"])

    def test_failed_revoke_preserves_credentials_for_retry(self):
        item=remote.create("a"*16,"Telegram","web",[NODE])
        self.mock_delete.side_effect=remote.nodes.NodeError("offline")
        with self.assertRaises(remote.nodes.NodeError):
            remote.remove(item["id"],[NODE])
        self.assertEqual(len(remote.load()["users"]),1)

    def test_wrong_protocol_answer_never_looks_successful(self):
        self.mock_sync.side_effect=lambda n,method,path,payload=None,timeout=0: (
            {"ok":True,"capabilities":CAPS} if method=="GET" else
            {"ok":True,"profiles":[{"protocol":"hysteria","link":"wrong"}]}
        )
        with self.assertRaises(remote.nodes.NodeError):
            remote.create("a"*16,"Bad","web",[NODE])
        self.assertEqual(self.mock_delete.call_count,1)
        self.assertFalse(remote.DATA.exists())

    def test_panel_route_patch_stages_real_user_actions(self):
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/"install-panel.sh").read_text()
        panel=source.split('cat > "$APP_FILE" <<\'PY\'\n',1)[1].split("\nPY\n",1)[0]
        updated=patch.patch(panel)
        self.assertIn("# wpo-remote-native-v04",updated)
        self.assertIn('wpo_node_remote.create(chosen[0],name,kind,',updated)
        self.assertIn('wpo_node_remote.remove(uid,node_api.load_nodes(NODES_FILE))',updated)
        self.assertIn('wpo_node_remote.cards(PANEL_PATH,self.csrf())',updated)
        self.assertIn('PANEL_PATH+"/remote-user-config"',updated)
        self.assertEqual(patch.patch(updated),updated)
        compile(updated,"panel.py","exec")


if __name__=="__main__":
    unittest.main()
