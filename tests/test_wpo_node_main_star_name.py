"""WPO Nodes Lab: primary ★ follows country name instead of flag."""
import ast
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "wpo_primary_star_patch", ROOT / "maintenance/nodes/wpo-node-main-star-name-patch.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class MainNodeStarTests(unittest.TestCase):
    def test_future_installer_produces_correct_mark_and_yellow_css(self):
        installer = (ROOT / "node-install.sh").read_text(encoding="utf-8")
        self.assertEqual(installer.count(patcher.NEW_MARKUP), 1)
        self.assertEqual(installer.count(patcher.NEW_CSS), 1)
        self.assertNotIn(patcher.OLD_MARKUP, installer)
        self.assertNotIn(patcher.OLD_CSS, installer)
        self.assertIn('h3><span class="wpo-node-main-name">{esc(lname)}</span> <span', installer)
        self.assertIn('color:#facc15', installer)

    def test_surgical_existing_ui_patch(self):
        old = ("def nodes_ui():\n"
               "    local_card = " + patcher.OLD_MARKUP + "\n"
               "CSS = '''" + patcher.OLD_CSS + "'''\n")
        ast.parse(old)
        new = patcher.patch(old)
        ast.parse(new)
        self.assertIn(patcher.NEW_MARKUP, new)
        self.assertIn(patcher.NEW_CSS, new)
        self.assertNotIn(patcher.OLD_MARKUP, new)
        self.assertNotIn(patcher.OLD_CSS, new)
        self.assertEqual(patcher.patch(new), new)
        self.assertEqual(new.count('aria-label="Основная нода"'), 1)
        self.assertIn('{status("local","online")}', new)

    def test_refuse_partial_and_unrelated_versions(self):
        for source in ("def other():\n    return None\n",
                       "def nodes_ui():\n    name = " + repr(patcher.OLD_MARKUP) + "\n"):
            with self.assertRaises(ValueError):
                patcher.patch(source)


if __name__ == "__main__":
    unittest.main()
