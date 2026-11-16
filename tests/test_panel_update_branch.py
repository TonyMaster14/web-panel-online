"""Regression: test-branch WPO controller updates reach Reality installation."""
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
UPDATER=ROOT/"update.sh"
SOURCE=UPDATER.read_text(encoding="utf-8")
START="RELEASE_KIND=tag\n"
END='echo "Selected WPO $RELEASE_KIND: $RELEASE_REF"\n'

class TestPanelTestBranchUpdate(unittest.TestCase):
    def test_main_updater_shell_syntax_and_entrypoint(self):
        subprocess.run(["bash","-n",str(UPDATER)],check=True,timeout=5)
        self.assertIn('REQUESTED_REF="@{WEB_PANEL_PROXY_REF:-}"'.replace("@{","$"+"{"),SOURCE)
        self.assertIn('git clone --depth 1 --branch "$RELEASE_REF"',SOURCE)

    def simulate(self, requested, exists=True):
        block=SOURCE.split(START,1)[1].split(END,1)[0]
        script=(
            'set -Eeuo pipefail\n'
            'REQUESTED_REF='+repr(requested)+'\n'
            'RELEASE_REF="$REQUESTED_REF"\n'
            'REPOSITORY="https://github.com/TonyMaster14/web-panel-online.git"\n'
            'RELEASE_KIND=tag\n'
            'die(){ printf "ERROR %s\\n" "$*" >&2; exit 44; }\n'
            'git(){ case "$1" in\n'
            '  check-ref-format) [[ "$2" == --branch && -n "$3" ]];;\n'
            '  ls-remote) [[ "$2" == --exit-code && "$3" == --heads && "$5" == "refs/heads/$REQUESTED_REF" ]] && '+
              ('true' if exists else 'false')+';;\n'
            '  *) return 43;; esac; }\n'
            +START+block+END
        )
        return subprocess.run(["bash","-c",script],capture_output=True,text=True,timeout=5)

    def test_explicit_test_ref_is_accepted(self):
        r=self.simulate("test/wpo-smooth-progress-v1")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("Selected WPO branch: test/wpo-smooth-progress-v1",r.stdout)

    def test_invalid_test_branch_is_rejected(self):
        for ref in ("test/-flag","test/with space","test/foo/../bar","test/foo;rm","test/"):
            with self.subTest(ref=ref):
                r=self.simulate(ref)
                self.assertNotEqual(r.returncode,0)

    def test_nonexistent_test_branch_is_rejected(self):
        r=self.simulate("test/wpo-smooth-progress-v1",exists=False)
        self.assertEqual(r.returncode,44)
        self.assertIn("branch not found",r.stderr)

    def test_stable_tags_still_supported(self):
        r=self.simulate("v3.0.0")
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("Selected WPO tag: v3.0.0",r.stdout)

    def test_reality_and_enrollment_fix_are_applied_after_nodes(self):
        nodes=SOURCE.index('bash "$TEMP_DIR/source/node-install.sh"')
        reality=SOURCE.index('bash "$TEMP_DIR/source/install-reality.sh"')
        registry=SOURCE.index('Restoring WPO node enrollment safety after controller update')
        self.assertLess(nodes,reality)
        self.assertLess(reality,registry)
        self.assertIn('--panel /opt/tproxy-panel/panel.py --out "$REGISTRY_STAGE"',SOURCE)
        self.assertIn('python3 -m py_compile "$REGISTRY_STAGE"',SOURCE)

    def test_test_versions_do_not_get_saved_as_slash_containing_branches(self):
        self.assertIn("3.0.0+test.%s",SOURCE)
        self.assertIn("/etc/web-proxy-panel/source-ref",SOURCE)

if __name__=="__main__":
    unittest.main()
