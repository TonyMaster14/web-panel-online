"""Make sure the Node bootstrap installs the FIXED pinned native module.

This reproduces the actual downloaded-eight-engine patch using the shipped
eight-engine template, but never fetches, starts or modifies real services.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT/"nodes/wpo-node-agent-install-v2.sh"
EIGHT=ROOT/"nodes/wpo-node-eight-enable.sh"
SOURCE=ROOT/"src/wpo_node_eight.py"
START="python3 - \"$EIGHT_SETUP\" <<'PY_WPO_NODE_NATIVE_FIX'\n"
END="\nPY_WPO_NODE_NATIVE_FIX"


class TestNodeNativeModulePin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agent=AGENT.read_text(encoding="utf-8")
        assert agent.count(START)==1 and agent.count(END)==1
        cls.patch=agent.split(START,1)[1].split(END,1)[0]
        cls.agent=agent

    def test_pinned_downloads_fix_only_federation_engine(self):
        with tempfile.TemporaryDirectory(prefix="wpo-native-pin-") as td:
            file=Path(td)/"eight.sh"
            file.write_text(EIGHT.read_text(encoding="utf-8"))
            before=file.read_text()
            p=subprocess.run(["python3","-c",self.patch,str(file)],
                             capture_output=True,text=True,timeout=8)
            self.assertEqual(p.returncode,0,p.stderr)
            after=file.read_text()
            self.assertNotEqual(before,after)
            self.assertIn('module_url="$BASE/$module"',after)
            self.assertIn('if [[ "$module" == wpo_node_eight.py ]]; then',after)
            self.assertIn('src/wpo_node_eight.py"',after)
            self.assertIn('b424110fedc4940854e3d93eaa4f026df544bf8a',after)
            self.assertIn('grep -Fq',after)
            self.assertIn('native_changed = assemble(old) != assemble(new)',after)
            self.assertIn('"$module_url" -o "$TEMP/$module"',after)
            self.assertIn('wpp_awg.py wpp_extra_protocols.py wpo_node_eight.py',after)
            # Full all-eight bootstrap remains unchanged except one module URL.
            self.assertIn('download_prebuilt tproxy-server-linux-amd64',after)
            self.assertIn('download_prebuilt mtproto-proxy-linux-amd64',after)
            self.assertEqual(before.count("systemctl restart wpo-node-vpn.service"),
                             after.count("systemctl restart wpo-node-vpn.service"))
            subprocess.run(["bash","-n",str(file)],check=True)
            subprocess.run(["python3","-m","py_compile",str(SOURCE)],check=True)

    def test_source_has_exact_schema_and_vless_removal_safeguards(self):
        contents=SOURCE.read_text(encoding="utf-8")
        self.assertIn("return list(GROUPED_CONNECTIONS.values())",contents)
        self.assertIn("native_changed = assemble(old) != assemble(new)",contents)
        self.assertIn("if native_changed:\n                    native_apply",contents)
        self.assertIn("if assemble(old):\n                native_apply",contents)

    def test_unexpected_original_script_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"not-eight.sh"
            path.write_text("#!/bin/bash\nexit 0\n")
            output=subprocess.run(["python3","-c",self.patch,str(path)],
                                  capture_output=True,text=True,timeout=6)
            self.assertNotEqual(output.returncode,0)
            self.assertIn("Pinned native engine layout changed",output.stderr)
            self.assertEqual(path.read_text(),"#!/bin/bash\nexit 0\n")


if __name__=="__main__":
    unittest.main()
