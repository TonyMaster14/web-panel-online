"""Regression: safely recover stale VPN settings from a failed Node Agent installation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT/"nodes/wpo-node-agent-install-v2.sh"
BEGIN="python3 - \"$DOMAIN\" <<'PY_NODE_STALE_DOMAIN'\n"
END="\nPY_NODE_STALE_DOMAIN"


class TestNodeStaleVPNDomain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=AGENT.read_text(encoding="utf-8")
        assert source.count(BEGIN)==1
        cls.source=source.split(BEGIN,1)[1].split(END,1)[0]

    def run_repair(self, root, requested="baba.goodarielservice.xyz", active=False):
        directory=Path(root)
        executable=directory/"systemctl"
        executable.write_text(
            "#!/bin/sh\n"
            + ("[ \"$1\" = is-active ] && exit 0\n" if active
               else "exit 3\n"),
            encoding="utf-8",
        )
        executable.chmod(0o700)
        script=self.source.replace(
            "root=Path('/etc/wpp-node-vpn')",
            "root=Path("+repr(str(directory/"vpn"))+")"
        )
        env=os.environ.copy()
        env["PATH"]=str(directory)+os.pathsep+env.get("PATH","")
        return subprocess.run(
            ["python3","-c",script,requested],
            text=True,capture_output=True,timeout=5,env=env,
        )

    def setup_settings(self, directory, domain="old.example.net", profiles=None):
        root=Path(directory)/"vpn"
        root.mkdir()
        settings=root/"settings.json"
        body={"domain":domain,"xhttp_path":"/wpo-xhttp-"+"a"*24}
        settings.write_text(json.dumps(body),encoding="utf-8")
        settings.chmod(0o600)
        if profiles is not None:
            (root/"profiles.json").write_text(
                json.dumps({"profiles":profiles}),encoding="utf-8"
            )
        return settings,body

    def test_orphaned_domain_creates_backup_and_allows_new_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,data=self.setup_settings(tmp,profiles={})
            result=self.run_repair(tmp)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(path.exists())
            backups=list(path.parent.glob("orphaned-domain-backup-*/settings.json"))
            self.assertEqual(len(backups),1)
            self.assertEqual(json.loads(backups[0].read_text()),data)
            self.assertEqual(backups[0].stat().st_mode & 0o777,0o600)
            self.assertIn("New domain: baba.goodarielservice.xyz",result.stdout)

    def test_active_vpn_refuses_domain_change_without_modifications(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,data=self.setup_settings(tmp)
            result=self.run_repair(tmp,active=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("active VPN service",result.stderr)
            self.assertEqual(json.loads(path.read_text()),data)
            self.assertFalse(list(path.parent.glob("orphaned-domain-backup-*")))

    def test_existing_clients_must_not_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,data=self.setup_settings(tmp,profiles={"client": {"name":"Someone"}})
            result=self.run_repair(tmp)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("existing profile data",result.stderr)
            self.assertEqual(json.loads(path.read_text()),data)

    def test_same_domain_keeps_settings_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,data=self.setup_settings(tmp,domain="baba.goodarielservice.xyz")
            result=self.run_repair(tmp)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(path.read_text()),data)
            self.assertFalse(list(path.parent.glob("orphaned-domain-backup-*")))

    def test_malformed_state_or_settings_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,data=self.setup_settings(tmp)
            (path.parent/"profiles.json").write_text("{not json")
            result=self.run_repair(tmp)
            self.assertNotEqual(result.returncode,0)
            self.assertTrue(path.exists())
            self.assertIn("profile data must be preserved",result.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            path,data=self.setup_settings(tmp)
            path.write_text("{not json")
            result=self.run_repair(tmp)
            self.assertNotEqual(result.returncode,0)
            self.assertTrue(path.exists())
            self.assertIn("settings are unreadable",result.stderr)


if __name__=="__main__":
    unittest.main()
