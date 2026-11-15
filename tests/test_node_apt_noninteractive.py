"""The WPO Node Agent installer must not open Ubuntu apt/needrestart dialogues."""
from pathlib import Path
import os
import subprocess
import unittest

AGENT=Path(__file__).resolve().parents[1]/"nodes/wpo-node-agent-install-v2.sh"

class TestNodeAPTNoninteractive(unittest.TestCase):
    def test_environment_set_before_shell_worker_and_apt(self):
        content=AGENT.read_text(encoding="utf-8")
        wanted={
            "DEBIAN_FRONTEND":"noninteractive",
            "DEBIAN_PRIORITY":"critical",
            "APT_LISTCHANGES_FRONTEND":"none",
            "NEEDRESTART_SUSPEND":"1",
        }
        for name,value in wanted.items():
            statement=f"export {name}={value}"
            self.assertEqual(content.count(statement),1)
            self.assertLess(content.index(statement),content.index("wpo_node_install_state check"))
            self.assertLess(content.index(statement),content.index("apt-get update"))
        self.assertLess(content.index("export NEEDRESTART_SUSPEND=1"),
                        content.index("WPO_NODE_WIZARD_START"))
        self.assertIn('WPO_NODE_WIZARD_WORKER=1 WPO_NODE_PROGRESS_FILE=',content)
        subprocess.run(["bash","-n",str(AGENT)],check=True)

    def test_export_inherited_by_background_bash_process(self):
        content=AGENT.read_text(encoding="utf-8")
        exports=[line for line in content.splitlines()
                 if line.startswith("export ") and any(
                   token in line for token in (
                     "DEBIAN_FRONTEND=","DEBIAN_PRIORITY=",
                     "APT_LISTCHANGES_FRONTEND=","NEEDRESTART_SUSPEND=",
                   ))]
        self.assertEqual(len(exports),4)
        sample="\n".join(exports)+"""
bash -c 'printf "%s/%s/%s/%s" "$DEBIAN_FRONTEND" "$DEBIAN_PRIORITY" "$APT_LISTCHANGES_FRONTEND" "$NEEDRESTART_SUSPEND"'
"""
        result=subprocess.run(["bash","-c",sample],text=True,
                              capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,"noninteractive/critical/none/1")

if __name__=="__main__":
    unittest.main()
