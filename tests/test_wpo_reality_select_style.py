"""UI-only select polish: the original REALITY picker is the visual reference."""
import ast
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
UI=ROOT/"src"/"wpp_ui.py"
PATCH=ROOT/"scripts"/"wpo-reality-select-ui-only.sh"
START="# WPO_REALITY_SELECT_STYLE_BEGIN"
END="# WPO_REALITY_SELECT_STYLE_END"
IDS=("#connectionProtocol","#clientFilter","#protocolFilter","#clientSort",
     '#wpoEditNodeDialog select[name="site_template"]',
     "#panelRelease","#xrayRelease","#openfluxRelease")

class RealitySelectStyleTests(unittest.TestCase):
    def test_syntax_and_no_functional_changes(self):
        source=UI.read_text(encoding="utf-8")
        ast.parse(source)
        css=source.split(START,1)[1].split(END,1)[0]
        for selector in IDS:
            self.assertIn(selector,css)
        self.assertEqual(source.count(START),1)
        self.assertEqual(source.count(END),1)
        self.assertIn("appearance:none",css)
        self.assertIn("-webkit-appearance:none",css)
        self.assertIn("border:1px solid var(--line)",css)
        self.assertIn("height:41px",css)
        self.assertIn("background-color:var(--input)",css)
        self.assertIn("background-image:url(",css)
        self.assertIn("#connectionProtocol:disabled",css)
        self.assertNotIn("pointer-events:none",css)
        self.assertNotIn("select.disabled=",css)
        self.assertNotIn("addEventListener(",css)

    def test_script_matches_canonical_style_and_is_syntax_valid(self):
        script=PATCH.read_text(encoding="utf-8")
        result=subprocess.run(["bash","-n",str(PATCH)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        canonical=UI.read_text(encoding="utf-8")
        source_style=canonical.split(START,1)[1].split(END,1)[0].strip()
        updater_style=script.split(START,1)[1].split(END,1)[0].strip()
        self.assertEqual(source_style,updater_style)
        self.assertIn("systemctl restart \"$SERVICE\"",script)
        self.assertIn("SERVICE=tproxy-panel.service",script)
        for forbidden in ("systemctl restart xray","systemctl restart haproxy",
                          "systemctl restart caddy","ip route add",
                          "iptables -A","nft add","rm -rf /etc"):
            self.assertNotIn(forbidden,script)

    def test_updater_is_idempotent_and_preserves_existing_node_ui(self):
        script=PATCH.read_text(encoding="utf-8")
        marker="python3 - \"$UI\" \"$STAGE/style.pyfrag\" \"$STAGE/wpp_ui.py\" <<'WPO_PATCH_PY'\n"
        self.assertIn(marker,script)
        python_src=script.split(marker,1)[1].split("\nWPO_PATCH_PY",1)[0]
        style=(START+script.split(START,1)[1].split(END,1)[0]+END)
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)
            original=root/"live.py"
            style_path=root/"style.txt"
            output=root/"updated.py"
            original.write_text(
                "import hashlib\nCOMMON_JS='script'\nCSS='base'\n"
                "def nodes_ui():\n    return '<dialog id=\"wpoEditNodeDialog\"></dialog>'\n",
                encoding="utf-8")
            style_path.write_text(style,encoding="utf-8")
            cmd=[sys.executable,"-",str(original),str(style_path),str(output)]
            first=subprocess.run(cmd,input=python_src,text=True,capture_output=True)
            self.assertEqual(first.returncode,0,first.stderr)
            updated=output.read_text(encoding="utf-8")
            self.assertIn('<dialog id="wpoEditNodeDialog">',updated)
            self.assertIn("#wpoEditNodeDialog",updated)
            self.assertEqual(updated.count(START),1)
            ast.parse(updated)
            original.write_text(updated,encoding="utf-8")
            second=subprocess.run(cmd,input=python_src,text=True,capture_output=True)
            self.assertEqual(second.returncode,77,second.stderr)
            self.assertIn("Изменений нет",second.stdout)

if __name__=="__main__":
    unittest.main()
