"""WPO live v2 star fix: rendered HTML and stylesheet must be correct."""
import ast
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "wpo_star_v2",ROOT/"wpo-node-main-star-v2-patch.py")
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def simulated_ui(markup):
    return (
        'import hashlib\n'
        'from html import escape\n'
        'CSS = ""\nCOMMON_JS = ""\n'
        'def esc(v): return escape(str(v), quote=True)\n'
        'def node_flag(v): return "🇳🇱"\n'
        'def nodes_ui(nodes, local, token, path, csrf):\n'
        '    lc=local.get("country_code","NL")\n'
        '    lname=local.get("country_name","Нидерланды")\n'
        '    def status(a,b):return \'<span data-node-status="local"></span>\'\n'
        '    return f\'<div class="wpo-node-card-head">'
        +markup+'{status("local","online")}</div>\'\n'
        '\nCSS += """base CSS"""\n'
        'ASSET_REV = hashlib.sha256((CSS + COMMON_JS).encode()).hexdigest()[:12]\n'
    )


class NodeStarV2Test(unittest.TestCase):
    def test_moves_flag_star_and_verifies_actual_html(self):
        source=simulated_ui(p.OLD_MARKUP)
        updated=p.patch(source)
        self.assertEqual(p.patch(updated),updated)
        self.assertIn(p.MARKER,updated)
        self.assertIn(p.NEW_MARKUP,updated)
        self.assertNotIn(p.OLD_MARKUP,updated)
        self.assertTrue(p.verify(updated))
        ast.parse(updated)

    def test_repairs_css_on_previously_patched_html(self):
        updated=p.patch(simulated_ui(p.NEW_MARKUP))
        self.assertIn(p.MARKER,updated)
        self.assertTrue(p.verify(updated))

    def test_unrelated_source_refused(self):
        with self.assertRaises(ValueError):
            p.patch('def unrelated(): pass\n')

    def test_new_installation_has_primary_star_after_title(self):
        source=(ROOT/"node-install.sh").read_text(encoding="utf-8")
        self.assertIn(p.NEW_MARKUP,source)
        self.assertIn('color:#facc15',source)


if __name__=='__main__':
    unittest.main()
