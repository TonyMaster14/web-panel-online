"""WPO Node APT fast-path regression tests. No host packages are changed."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT/"nodes/wpo-node-agent-install-v2.sh"
SRC=AGENT.read_text(encoding="utf-8")
START="report installing 'Установка Caddy и подготовка сайта ноды.'\n"
END='PUBLIC_IP="$(curl -4fsS --max-time 10 https://api.ipify.org)"'


class TestNodeFastUbuntu(unittest.TestCase):
    def test_noninteractive_apt_and_progress_ui(self):
        self.assertIn("export DEBIAN_FRONTEND=noninteractive",SRC)
        self.assertIn("export NEEDRESTART_SUSPEND=1",SRC)
        self.assertIn('stty -echo < /dev/tty',SRC)
        self.assertIn('stty "$node_tty_original" < /dev/tty',SRC)
        self.assertIn('[[ "$current" != "$node_last_drawn" ]] || return 0',SRC)
        self.assertNotIn('node_percent=$node_confirmed',SRC)
        self.assertIn('node_last_move_us="@{EPOCHREALTIME/./}"'.replace("@{","$"+"{"),SRC)
        self.assertIn('interval=650000',SRC)
        self.assertIn('(( node_percent == 100 )) || sleep 0.012',SRC)
        self.assertIn('curl -fsS --connect-timeout 2 --max-time 4',SRC)
        self.assertIn('for i in $(seq 1 180); do',SRC)
        self.assertIn('curl ca-certificates gnupg python3 unzip openssl',SRC)
        subprocess.run(["bash","-n",str(AGENT)],check=True)

    def run_prep(self,os_id="ubuntu",fresh=True,has_caddy=True,
                 force_update=False,fail_first=False):
        with tempfile.TemporaryDirectory(prefix="wpo-apt-test-") as temp:
            lists=Path(temp)/"lists"
            lists.mkdir()
            if fresh:
                (lists/"mock_ubuntu_InRelease").touch()
                (lists/"mock_ubuntu_Packages.lz4").touch()
            block=SRC.split(START,1)[1].split(END,1)[0]
            cleaned=[]
            for line in block.splitlines():
                if any(marker in line for marker in ("dl.cloudsmith.io","chmod o+r")):
                    cleaned.append("  : # mocked external repository")
                else:
                    cleaned.append(line)
            block="\n".join(cleaned).replace("/var/lib/apt/lists",str(lists))
            script=(
                "set -Eeuo pipefail\n"
                "ID="+os_id+"\n"
                "HAVE_CADDY_BINARY=0\n"
                "WPO_HAS_CADDY="+("1" if has_caddy else "0")+"\n"
                "WPO_NODE_FORCE_APT_UPDATE="+("1" if force_update else "0")+"\n"
                "WPO_FAIL_FIRST_INSTALL="+("1" if fail_first else "0")+"\n"
                "WPO_APT_ATTEMPTS=0\n"
                "report(){ :; }\n"
                "command(){ if [[ \"@{1:-}\" == -v && \"@{2:-}\" == caddy ]]; then "
                "  [[ \"$HAVE_CADDY_BINARY\" == 1 ]]; return; "
                "fi; builtin command \"$@\"; }\n"
                "apt-cache(){ if [[ \"@{1:-}\" == show && \"@{2:-}\" == caddy ]]; then "
                "  [[ \"$WPO_HAS_CADDY\" == 1 ]]; return; "
                "fi; return 0; }\n"
                "apt-get(){ "
                " printf 'APT %s\\n' \"$*\"; "
                " if [[ \"@{1:-}\" == install ]]; then "
                "   WPO_APT_ATTEMPTS=$((WPO_APT_ATTEMPTS+1)); "
                "   if [[ \"$WPO_FAIL_FIRST_INSTALL\" == 1 && \"$WPO_APT_ATTEMPTS\" == 1 ]]; then return 41; fi; "
                "   for arg in \"$@\"; do [[ \"$arg\" == caddy ]] && HAVE_CADDY_BINARY=1; done; "
                " fi; return 0; }\n"
                +START+block+"\n"
            ).replace("@{","$"+"{")
            return subprocess.run(["bash","-c",script],capture_output=True,
                                  text=True,timeout=8)

    def test_fresh_ubuntu_reuses_signed_indexes_and_one_caddy_transaction(self):
        p=self.run_prep()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("apt-index: reused validated recent metadata",p.stdout)
        self.assertEqual(p.stdout.count("APT install"),1,p.stdout)
        self.assertNotIn("APT update",p.stdout)
        self.assertIn("procps caddy",p.stdout)
        self.assertNotIn("debian-keyring",p.stdout)
        self.assertIn("preparation-total:",p.stdout)

    def test_stale_cache_refreshes_before_package_install(self):
        p=self.run_prep(fresh=False)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.count("APT update"),1,p.stdout)
        self.assertEqual(p.stdout.count("APT install"),1,p.stdout)

    def test_force_update_works_even_if_cache_is_fresh(self):
        p=self.run_prep(force_update=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.count("APT update"),1,p.stdout)

    def test_cached_package_failure_refreshes_and_retries(self):
        p=self.run_prep(fail_first=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.count("APT update"),1,p.stdout)
        self.assertEqual(p.stdout.count("APT install"),2,p.stdout)
        self.assertIn("APT cache was stale",p.stderr)

    def test_debian_missing_distro_caddy_keeps_external_fallback(self):
        p=self.run_prep(os_id="debian",has_caddy=False)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("debian-keyring",p.stdout)
        self.assertIn("debian-archive-keyring",p.stdout)
        self.assertEqual(p.stdout.count("APT update"),1,p.stdout)
        self.assertEqual(p.stdout.count("APT install"),3,p.stdout)
        self.assertIn("caddy-external:",p.stdout)


if __name__=="__main__":
    unittest.main()
