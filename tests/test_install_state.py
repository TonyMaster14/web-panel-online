"""WPO installer first-run, incomplete-run and already-installed protection.

These tests execute the real shell state detector with every managed path
remapped into temporary fixtures. They never touch host WPO services or data.
"""
from pathlib import Path
import subprocess
import tempfile
import re
import unittest

SOURCE = Path("install.sh").read_text(encoding="utf-8")
FINAL = Path("install-final.sh").read_text(encoding="utf-8")
UNINSTALL = Path("uninstall-web-proxy.sh").read_text(encoding="utf-8")
begin = SOURCE.index("wpo_install_state() {")
end = SOURCE.index("\nwpo_clean_partial() {", begin)
DETECTOR = SOURCE[begin:end]

def isolated_script(tmp):
    s = DETECTOR
    for root in ("/var/lib/tproxy-panel", "/etc/systemd/system",
                 "/etc/web-proxy-panel", "/opt/tproxy-panel",
                 "/usr/local/sbin", "/etc/tproxy-server"):
        s = s.replace(root, str(tmp) + root)
    return "set -Eeuo pipefail\n" + s + "\nwpo_install_state\n"

class InstallStateTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(prefix="wpo-state-test-")
        self.addCleanup(self.d.cleanup)
        self.root = Path(self.d.name)
    def f(self, path, text="x"):
        p = self.root / path.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    def state(self):
        result = subprocess.run(["bash", "-c", isolated_script(self.root)],
                                text=True, capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout
    def test_clean_vps(self):
        self.assertEqual(self.state(), "clean")
    def test_interrupted_with_marker_and_data(self):
        self.f("/var/lib/tproxy-panel/.wpo-install-in-progress")
        self.f("/var/lib/tproxy-panel/data.json", '{"admin":{}}')
        self.f("/etc/systemd/system/tproxy-panel.service")
        self.assertEqual(self.state(), "partial")
    def test_interrupted_early_with_only_wpo_files(self):
        self.f("/etc/web-proxy-panel/version", "3.0.0")
        self.assertEqual(self.state(), "partial")
    def test_completed_vps_preserves_login_data(self):
        self.f("/var/lib/tproxy-panel/.wpo-install-complete")
        self.f("/var/lib/tproxy-panel/data.json", '{"admin":{"user":"operator"}}')
        self.f("/etc/systemd/system/tproxy-panel.service")
        self.assertEqual(self.state(), "installed")
    def test_inconsistent_completion_is_protected(self):
        self.f("/var/lib/tproxy-panel/.wpo-install-complete")
        self.assertEqual(self.state(), "protected")
    def test_legacy_v26_is_installed_not_cleaned(self):
        self.f("/var/lib/tproxy-panel/data.json", '{"admin":{"user":"operator"}}')
        self.f("/etc/systemd/system/tproxy-panel.service",
               "Environment=WEBPROXY_PANEL_PATH=/panel-abc123\n")
        self.f("/etc/web-proxy-panel/version", "3.0.0")
        self.f("/opt/tproxy-panel/panel.py", "controller")
        self.f("/opt/tproxy-panel/wpp_ui.py", "/* wpo-node-spinner-center-v26 */")
        self.assertEqual(self.state(), "installed")
    def test_ambiguous_legacy_data_is_not_erased(self):
        self.f("/var/lib/tproxy-panel/data.json", '{"admin":{}}')
        self.f("/etc/systemd/system/tproxy-panel.service", "incomplete")
        self.assertEqual(self.state(), "protected")

class SafetyContractTests(unittest.TestCase):
    def test_completed_run_cannot_auto_update(self):
        head = SOURCE.index("WPO_INSTALL_STATE=")
        classic = SOURCE.index("if (( ! USE_WIZARD ))")
        wizard = SOURCE.index("\nUPDATE=0", classic)
        self.assertLess(head, classic)
        self.assertLess(classic, wizard)
        self.assertIn("installed)", SOURCE[head:classic])
        self.assertIn("exit 0", SOURCE[head:classic])
        self.assertIn("ask_domain", SOURCE[wizard:wizard+500])
        self.assertNotIn("Найдена установленная панель: обновляем", SOURCE)
    def test_install_markers_straddle_all_critical_checks(self):
        self.assertLess(FINAL.index('WPO_PENDING=/var/lib/tproxy-panel/.wpo-install-in-progress'),
                        FINAL.index("Installing proxy services..."))
        self.assertLess(FINAL.index('bash "$BASE/node-install.sh"'),
                        FINAL.index('WPO_SUCCESS_TMP='))
        self.assertLess(FINAL.index('xray run -test -config'),
                        FINAL.index('WPO_SUCCESS_TMP='))
        self.assertLess(FINAL.index('WPO_SUCCESS_TMP='),
                        FINAL.index('wpp_progress 100 "Установка завершена"'))
        self.assertIn('rm -f -- "$WPO_PENDING"', FINAL)
    def test_partial_removal_is_locked_and_checks_success(self):
        cleaner = SOURCE.split("wpo_clean_partial() {",1)[1].split("\nWPO_INSTALL_STATE=",1)[0]
        self.assertIn("flock -n 7", cleaner)
        self.assertIn('bash -n "$removal_script"', cleaner)
        self.assertIn('bash "$removal_script"', cleaner)
        self.assertIn('[[ "$after" == clean ]]', cleaner)
        self.assertIn("error 'Очистка незавершённой установки", cleaner)
    def test_remover_stops_component_update_timers(self):
        self.assertIn("web-panel-proxy-component-auto-update.timer web-panel-proxy-component-auto-update.service", UNINSTALL)
        self.assertIn("/etc/systemd/system/web-panel-proxy-component-auto-update.timer", UNINSTALL)

if __name__ == "__main__":
    unittest.main()
