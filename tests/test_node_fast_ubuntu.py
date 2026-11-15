"""Node installer fast Ubuntu APT path and terminal progress, no VPS changes."""
from pathlib import Path
import subprocess
import unittest

AGENT=Path("nodes/wpo-node-agent-install-v2.sh")
SRC=AGENT.read_text(encoding="utf-8")
START="if ! command -v caddy >/dev/null 2>&1; then\n"
END='PUBLIC_IP="$(curl -4fsS --max-time 10 https://api.ipify.org)"'


class TestNodeFastUbuntu(unittest.TestCase):
    def test_noninteractive_apt_and_progress_ui(self):
        self.assertIn("export DEBIAN_FRONTEND=noninteractive",SRC)
        self.assertIn("export NEEDRESTART_SUSPEND=1",SRC)
        self.assertIn('stty -echo < /dev/tty',SRC)
        self.assertIn('stty "$node_tty_original" < /dev/tty',SRC)
        self.assertIn('[[ "$current" != "$node_last_drawn" ]] || return 0',SRC)
        self.assertIn('verified_ceiling=$((node_confirmed+10))',SRC)
        subprocess.run(["bash","-n",str(AGENT)],check=True)

    def run_caddy_preflight(self,os_id):
        block=SRC.split(START,1)[1].split(END,1)[0]
        cleaned=[]
        for line in block.splitlines():
            if "dl.cloudsmith.io" in line or "chmod o+r" in line:
                cleaned.append("  : # mock external repo setup")
            else:
                cleaned.append(line)
        script=(
            'set -Eeuo pipefail\n'
            'ID='+os_id+'\n'
            'command(){ if [[ "@{1:-}" == -v && "@{2:-}" == caddy ]]; then return 1; fi; builtin command "$@"; }\n'
            'apt-get(){ printf "APT %s\\n" "$*"; }\n'
            +START+"\n".join(cleaned)+"\n"
        ).replace("@{","$"+"{")
        return subprocess.run(["bash","-c",script],capture_output=True,text=True,timeout=4)

    def test_ubuntu_does_not_download_debian_only_packages(self):
        result=self.run_caddy_preflight("ubuntu")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn("debian-keyring",result.stdout)
        self.assertNotIn("debian-archive-keyring",result.stdout)
        self.assertNotIn("apt-transport-https",result.stdout)
        self.assertIn("install -y --no-install-recommends caddy",result.stdout)

    def test_debian_keeps_legacy_prerequisites(self):
        result=self.run_caddy_preflight("debian")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn("debian-keyring",result.stdout)
        self.assertIn("debian-archive-keyring",result.stdout)
        self.assertIn("install -y --no-install-recommends caddy",result.stdout)


if __name__=="__main__":
    unittest.main()
