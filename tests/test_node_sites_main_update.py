"""Regression: one main WPO command can repair sites on registered nodes."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/"wpo-node-sites-main-update.sh").read_text()
START="python3 - \"$REGISTRY\" > \"$WORK/nodes.tsv\" <<'PY_NODES'\n"
END="\nPY_NODES"
assert SRC.count(START)==1
DISCOVER=SRC.split(START,1)[1].split(END,1)[0]


class MainPanelSiteUpdate(unittest.TestCase):
    def test_single_command_scopes_fixes_to_external_nodes(self):
        for s in (
            "PANEL=/opt/tproxy-panel/panel.py",
            "! -e /etc/wpp-node-agent/config.json",
            "wpo-nodes-routing-update.sh",
            "wpo-node-site-template-fix.sh",
            "ssh -T",
            "root@$host",
            "test \\"\\$(python3 -c",
            "bash -s",
            'while IFS=$\'\\t\' read -r node_id host;',
            "ServerAliveInterval=5",
        ):
            self.assertIn(s,SRC)
        self.assertNotIn("systemctl restart wpo-node-xray",SRC)
        self.assertNotIn("systemctl restart xray",SRC)
        self.assertNotIn("sshpass",SRC)
        self.assertNotIn("StrictHostKeyChecking=no",SRC)
        self.assertNotIn('curl -k',SRC)

    def test_registry_discovers_only_public_https_registered_nodes(self):
        with tempfile.TemporaryDirectory(prefix="wpo-main-site-tests-") as t:
            root=Path(t)
            (root/"nodes.json").write_text(json.dumps([
                {"id":"a"*16,"url":"https://de.example.net","token":"SENSITIVE"},
                {"id":"b"*16,"url":"https://se.example.net","enabled":False,"token":"SENSITIVE2"},
                {"id":"c"*16,"url":"https://de.example.net","token":"SENSITIVE3"},
                {"id":"d"*16,"url":"http://insecure.example.net","token":"wrong"},
                {"id":"e"*16,"url":"https://127.0.0.1","token":"wrong"}
            ]))
            # No file should be modified, and secrets must not be printed.
            run=subprocess.run([sys.executable,"-c",DISCOVER,str(root)],
                                capture_output=True,text=True,timeout=5)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(run.stdout,"a"*16+"\tde.example.net\n")
            self.assertNotIn("SENSITIVE",run.stdout)
            self.assertEqual(json.loads((root/"nodes.json").read_text())[0]["token"],"SENSITIVE")


if __name__=="__main__":
    unittest.main()
