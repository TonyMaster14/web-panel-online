"""Main-only WPO update: preserve site templates without any SSH/VPN changes."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=(ROOT/"wpo-node-templates-panel-only.sh").read_text()
INSTALLER=(ROOT/"wpo-node-agent-install-v2.sh").read_text()
EIGHT=(ROOT/"wpo-node-eight-enable.sh").read_text()
SITE=(ROOT/"wpo-node-site-template-fix.sh").read_text()
CORE=(ROOT/"node-install.sh").read_text()


class PanelOnlyTemplates(unittest.TestCase):
    def test_script_is_syntax_valid_and_no_remote_access(self):
        p=subprocess.run(["bash","-n",str(ROOT/"wpo-node-templates-panel-only.sh")],
                         capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        for banned in (
            "ssh -", "sshpass", "root@$host",
            "systemctl restart", "systemctl reload", "wpo-node-sites-main-update.sh",
            "apt-get", "wpo-node-vpn-enable.sh",
        ):
            self.assertNotIn(banned,SCRIPT)
        self.assertIn('TARGET="$APP/wpp-node-agent-install.sh"',SCRIPT)
        self.assertIn('cmp -s "$WORK/installer" "$TARGET"',SCRIPT)
        self.assertIn('cp -a "$TARGET" "$BACKUP/wpp-node-agent-install.sh"',SCRIPT)
        self.assertIn('cp -a "$BACKUP/wpp-node-agent-install.sh" "$TARGET"',SCRIPT)

    def test_immutable_pin_chain_proves_site_fix_in_next_installer(self):
        m=re.search(r'^ENGINE_REV=([a-f0-9]{40})$',SCRIPT,re.M)
        self.assertIsNotNone(m)
        self.assertIn('ENGINE_REV='+m.group(1),INSTALLER)
        self.assertIn('"$BASE/wpo-node-site-template-fix.sh"',EIGHT)
        self.assertIn('bash "$TEMP/site-template-fix.sh"',EIGHT)
        self.assertIn("doc['public_upstream']='http://127.0.0.1:18082'",SITE)
        self.assertIn('header Cache-Control "no-store"',SITE)
        self.assertIn('bind 127.0.0.1',SITE)
        self.assertIn('expected={"federation","vless","hysteria"',SCRIPT)

    def test_main_panel_serves_installer_from_disk(self):
        # No tproxy-panel restart is needed after replacing this source file.
        self.assertIn('with open(NODE_AGENT_INSTALLER_FILE,encoding="utf-8") as stream: body=stream.read()',CORE)

    def test_new_agent_keeps_the_template_upload_api(self):
        self.assertIn("if self.path=='/wpp-api/v1/site-template':",INSTALLER)
        self.assertIn("C['site_template_id']=template_id",INSTALLER)
        self.assertIn("atomic_write(os.path.join(SITE,'index.html'),page.encode('utf-8'))",INSTALLER)
        self.assertIn("wpo_node_auto.start(NODES_FILE,lambda: all_presets(),node_api)",CORE)


if __name__=="__main__":
    unittest.main()
