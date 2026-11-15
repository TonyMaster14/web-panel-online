"""Regression checks for compact WPO repository layout (offline; no VPS writes)."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/prepare-source-layout.sh"

class CompactLayoutTests(unittest.TestCase):
    def fixture(self, target):
        sample = {
            "src/wpp_demo.py": "def ready(): return True\n",
            "installers/install-final.sh": "#!/bin/bash\nexit 0\n",
            "nodes/wpo-node-eight-enable.sh": "#!/bin/bash\nexit 0\n",
            "docs/THIRD-PARTY-NOTICES.md": "Notices\n",
            "maintenance/other/wpo-site-zero-profiles-v6.sh": "#!/bin/bash\nexit 0\n",
            "maintenance/other/wpo-relay-zero-profiles-patch.py": "# archive\n",
            "nodes/README.md": "NODE DOCUMENTATION, NOT A ROOT LINK\n",
            "README.md": "MAIN PROJECT DOCUMENTATION\n",
        }
        for path, content in sample.items():
            file = target / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")

    def execute(self, target):
        return subprocess.run(["bash", str(BOOTSTRAP), str(target)],
                              capture_output=True, text=True)

    def test_flat_compatibility_links_are_idempotent_and_readme_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="wpo-layout-") as tmp:
            folder = Path(tmp)
            self.fixture(folder)
            for _ in range(2):
                result = self.execute(folder)
                self.assertEqual(result.returncode, 0, result.stderr)
            for name, relative in (
                ("wpp_demo.py", "src/wpp_demo.py"),
                ("install-final.sh", "installers/install-final.sh"),
                ("wpo-node-eight-enable.sh", "nodes/wpo-node-eight-enable.sh"),
                ("THIRD-PARTY-NOTICES.md", "docs/THIRD-PARTY-NOTICES.md"),
                ("wpo-site-zero-profiles-v6.sh", "maintenance/other/wpo-site-zero-profiles-v6.sh"),
                ("wpo-relay-zero-profiles-patch.py", "maintenance/other/wpo-relay-zero-profiles-patch.py"),
            ):
                link = folder / name
                self.assertTrue(link.is_symlink(), name)
                self.assertEqual(link.readlink().as_posix(), relative)
                self.assertEqual(link.read_text(), (folder / relative).read_text())
            self.assertFalse((folder / "README.md").is_symlink())
            self.assertEqual((folder / "README.md").read_text(), "MAIN PROJECT DOCUMENTATION\n")

    def test_conflicting_file_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="wpo-layout-conflict-") as tmp:
            folder = Path(tmp)
            self.fixture(folder)
            original = folder / "wpp_demo.py"
            original.write_text("important user file\n")
            result = self.execute(folder)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite", result.stderr)
            self.assertEqual(original.read_text(), "important user file\n")

    def test_installer_and_updater_restore_the_layout(self):
        for name in ("install.sh", "node-install.sh", "update.sh"):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("scripts/prepare-source-layout.sh", content, name)
        updater = (ROOT / "update.sh").read_text(encoding="utf-8")
        self.assertEqual(updater.count('cp -aL "$LOCAL_SOURCE/$file" "$TEMP_DIR/source/$file"'), 2)
        self.assertTrue((ROOT / "installers/install-panel.sh").is_file())
        self.assertTrue((ROOT / "nodes/wpo-node-agent-install-v2.sh").is_file())

if __name__ == "__main__":
    unittest.main()
