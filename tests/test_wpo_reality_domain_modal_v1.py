"""WPO node-aware REALITY modal regression tests."""
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import wpo_reality_ui as ui


def load_updater():
    path=ROOT/"scripts/wpo-reality-domain-modal-v1.py"
    spec=importlib.util.spec_from_file_location("reality_domain_ui_v1",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RealityDomainModeUiTests(unittest.TestCase):
    def setUp(self):
        profile={"preset":"nvidia","sni":"www.nvidia.com","fingerprint":"firefox",
                 "address":"192.0.2.10","public_key":"p"*43,"short_id":"aabb"}
        p=patch.object(ui.reality,"read_profile",return_value=profile)
        p.start();self.addCleanup(p.stop)

    def rendered(self):
        html=ui.editor("/panel-abc","csrf",nodes=[
            {"id":"abcdef1234567890","name":"Швеция"},
            {"id":"aaaabbbbccccdddd","name":"Польша"}])
        self.assertTrue(html)
        return html

    def test_selected_node_legacy_and_managed_are_both_rendered_safely(self):
        html=self.rendered()
        self.assertIn("Сайт для REALITY",html)
        self.assertIn("www.nvidia.com",html)
        self.assertIn("Домен ноды · SNI",html)
        self.assertIn("function presentMode(p)",html)
        self.assertIn("managedNodeReadonly=!fleet&&p.managed_readonly===true",html)
        self.assertIn("f.querySelector('[data-reality-legacy-target]').hidden=direct",html)
        self.assertIn("f.elements.fingerprint.disabled=direct",html)
        self.assertIn("f.elements.sni.readOnly=direct",html)
        self.assertIn("if(!cancelRequested){managedNodeReadonly=true",html)
        self.assertIn('read_only:\'1\'',html)
        self.assertNotIn("managedNodeReadonly=true;f.elements.sni.value='www.nvidia.com'",html)

    @unittest.skipUnless(shutil.which("node"),"NodeJS unavailable")
    def test_real_modal_js_parses_as_javascript(self):
        html=self.rendered()
        match=re.search(r"<script>(.*?)</script>",html,re.S)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"dialog.js"
            target.write_text(match.group(1),encoding="utf-8")
            check=subprocess.run(["node","--check",str(target)],
                                 capture_output=True,text=True,timeout=10)
        self.assertEqual(check.returncode,0,check.stderr)

    def test_safe_installer_rejects_unknown_or_custom_file_hash(self):
        updater=load_updater()
        original=(ROOT/"src/wpo_reality_ui.py").read_bytes()
        self.assertNotEqual(updater.blob(original),updater.OLD_BLOB)
        self.assertEqual(len(updater.OLD_BLOB),40)
        source=(ROOT/"scripts/wpo-reality-domain-modal-v1.py").read_text()
        self.assertIn("if blob(installed)!=OLD_BLOB:",source)
        self.assertIn("def rollback():",source)
        self.assertNotIn("restart wpo-node-xray",source)
        self.assertNotIn("restart caddy",source)


if __name__=="__main__":unittest.main()
