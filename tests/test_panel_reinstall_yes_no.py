"""Test the installed WPO yes/no reinstall gate in a disposable SSH terminal.

The actual prompt and staging code is extracted from install.sh. All network
commands and the destructive WPO cleanup are stubbed. No VPS files are touched.
"""
import errno
import os
from pathlib import Path
import pty
import select
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
INSTALLER=ROOT/"install.sh"
ANCHOR="WPO_REINSTALL_APPROVED=0\nwpo_offer_reinstall(){"
END="# Classic mode remains compatible with previous invocation patterns."


class TestWPOFreshReinstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src=INSTALLER.read_text(encoding="utf-8")
        assert src.count(ANCHOR)==1 and src.count(END)==1
        cls.entry=ANCHOR+src.split(ANCHOR,1)[1].split(END,1)[0]
        assert 'wpo_reinstall_stage "$SOURCE"' in src
        assert 'wpo_reinstall_stage "$LOCAL_BASE"' in src
        assert 'wpo_reinstall_stage "$WORK/source"' in src
        assert src.index('wpo_reinstall_stage "$SOURCE"') > src.index('ask_password')
        assert src.index('wpo_reinstall_stage "$SOURCE"') > src.index('[[ -s "$SOURCE/install-final.sh"')
        assert src.count('wpo_reinstall_stage "$SOURCE"')==1
        subprocess.run(["bash","-n",str(INSTALLER)],check=True)

    def run_gate(self,dir,state="installed",reply=b"yes\n",wiz=False,
                 source_ok=True,dns_good=True,interactive=True):
        root=Path(dir)
        package=root/"package"
        package.mkdir()
        for filename in ("install-final.sh","node-install.sh","uninstall-web-proxy.sh"):
            if filename=="uninstall-web-proxy.sh" and not source_ok:
                continue
            (package/filename).write_text("#!/bin/bash\nexit 0\n")
        trace=root/"cleanup_calls"
        progress=root/"progress"
        progress.touch()
        ip="192.0.2.42"
        dns_ip=ip if dns_good else "192.0.2.99"
        preamble=(
            "#!/usr/bin/env bash\n"
            "set -Eeuo pipefail\n"
            "blue='' cyan='' red='' ice='' reset='' success=''\n"
            "error(){ echo \"ERROR: $*\" >&2; exit 1; }\n"
            "USE_WIZARD="+("1" if wiz else "0")+"\n"
            "DOMAIN='fresh.example.net'\n"
            "PROGRESS="+repr(str(progress))+"\n"
            "wpo_install_state(){ printf '%s' "+repr(state)+"; }\n"
            "wpo_clean_partial(){ printf '%s\\n' \"${1:-partial}\" >> "+repr(str(trace))+"; }\n"
            "curl(){ printf '%s' '"+ip+"'; }\n"
            "getent(){ printf '%s\\n' '"+dns_ip+" STREAM fresh.example.net'; }\n"
        )
        postamble=(
            'printf "ACCEPTED=%s\\n" "$WPO_REINSTALL_APPROVED"\n'
            'wpo_reinstall_stage '+repr(str(package))+'\n'
            'printf "INSTALL_WOULD_START\\n"\n'
        )
        script=root/"simulated-reinstall.sh"
        script.write_text(preamble+self.entry+postamble)
        subprocess.run(["bash","-n",str(script)],check=True)
        if not interactive:
            proc=subprocess.run(
                ["bash",str(script)],stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,timeout=6,start_new_session=True,
            )
            output=proc.stdout
            return proc.returncode,output,trace.read_text() if trace.exists() else ""
        pid,fd=pty.fork()
        if pid==0:
            os.execv("/bin/bash",["bash",str(script)])
        try:
            if reply is not None:
                os.write(fd,reply)
            output=b""
            status=None
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                r,_,_=select.select([fd],[],[],0.2)
                if r:
                    try: chunk=os.read(fd,65536)
                    except OSError as exc:
                        if exc.errno==errno.EIO: break
                        raise
                    if not chunk: break
                    output+=chunk
                child,status_value=os.waitpid(pid,os.WNOHANG)
                if child:
                    status=os.waitstatus_to_exitcode(status_value)
                    break
            if status is None:
                child,status_value=os.waitpid(pid,os.WNOHANG)
                if child:
                    status=os.waitstatus_to_exitcode(status_value)
                else:
                    os.kill(pid,9)
                    os.waitpid(pid,0)
                    self.fail("Reinstall yes/no prompt stalled")
            return status,output.decode("utf-8","replace"),trace.read_text() if trace.exists() else ""
        finally:
            os.close(fd)

    def test_yes_proceeds_to_wpo_only_cleanup_and_new_install(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td)
            self.assertEqual(status,0,out)
            self.assertIn("Установить новую панель? (yes/no):",out)
            self.assertIn("ACCEPTED=1",out)
            self.assertIn("INSTALL_WOULD_START",out)
            self.assertEqual(trace,"installed\n")

    def test_no_leaves_panel_untouched_and_quits(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,reply=b"no\n")
            self.assertEqual(status,0,out)
            self.assertIn("прежняя панель и её данные сохранены",out)
            self.assertNotIn("INSTALL_WOULD_START",out)
            self.assertEqual(trace,"")

    def test_enter_defaults_to_no_without_changes(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,reply=b"\n")
            self.assertEqual(status,0,out)
            self.assertEqual(trace,"")

    def test_y_is_not_sufficient_consent(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,reply=b"y\nno\n")
            self.assertEqual(status,0,out)
            self.assertIn("Введите только yes или no.",out)
            self.assertEqual(trace,"")

    def test_missing_new_package_keeps_existing_panel(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,source_ok=False)
            self.assertNotEqual(status,0)
            self.assertIn("Новый пакет неполный",out)
            self.assertEqual(trace,"")

    def test_bad_dns_keeps_existing_panel(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,wiz=True,dns_good=False)
            self.assertNotEqual(status,0)
            self.assertIn("Старая панель сохранена",out)
            self.assertEqual(trace,"")

    def test_good_dns_allows_clean_reinstall_in_wizard(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,wiz=True)
            self.assertEqual(status,0,out)
            self.assertEqual(trace,"installed\n")
            self.assertIn("Очистка прежней панели",Path(td,"progress").read_text())

    def test_ambiguous_panel_is_never_automatically_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,state="protected",reply=None)
            self.assertNotEqual(status,0)
            self.assertIn("неизвестным состоянием",out)
            self.assertEqual(trace,"")

    def test_partial_still_uses_existing_recovery_path(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,state="partial",reply=None)
            self.assertEqual(status,0,out)
            self.assertEqual(trace,"partial\n")

    def test_clean_machine_installs_without_consent(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,state="clean",reply=None)
            self.assertEqual(status,0,out)
            self.assertEqual(trace,"")
            self.assertIn("INSTALL_WOULD_START",out)

    def test_without_tty_never_deletes_working_panel(self):
        with tempfile.TemporaryDirectory() as td:
            status,out,trace=self.run_gate(td,interactive=False)
            self.assertNotEqual(status,0)
            self.assertEqual(trace,"")
            self.assertNotIn("INSTALL_WOULD_START",out)


if __name__=="__main__":
    unittest.main()
