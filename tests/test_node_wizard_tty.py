"""Pseudo-terminal tests for the WPO Node Agent installation wizard.

The actual terminal frontend runs in a disposable shell; long provisioning
is replaced by a fake worker. CI never modifies a VPS.
"""
import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import tempfile
import termios
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT/"nodes/wpo-node-agent-install-v2.sh"
BOUNDARY="# WPO_NODE_WIZARD_END"


class TestNodeWizardTTY(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=AGENT.read_text()
        assert cls.source.count(BOUNDARY)==1
        assert "sleep 2\n  printf '\\033[2J\\033[H'" in cls.source
        assert "node_box 'НОДА УСТАНОВЛЕНА' \"$nyellow\"" in cls.source
        subprocess.run(["bash","-n",str(AGENT)],check=True)

    def exercise(self,root,failed=False,interactive=True):
        root=Path(root)
        head=self.source.split(BOUNDARY,1)[0]+BOUNDARY+"\n"
        head=head.replace(
            "[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }",
            ": # disposable test only"
        )
        head=head.replace("/var/log/web-panel-online",str(root/"logs"))
        head=head.replace("/run/wpo-node-progress.",str(root/"progress."))
        head=head.replace("sleep 2\n  printf '\\033[2J\\033[H'",
                          "sleep 0.04\n  printf '\\033[2J\\033[H'")
        head=head.replace("sleep 0.08","sleep 0.001")
        head=head.replace("sleep 0.2","sleep 0.01")
        head+=r'''
if [[ "@{WPO_NODE_WIZARD_WORKER:-0}" != 1 ]]; then
  echo CLASSIC_WORKER_INTACT
  exit 0
fi
IFS= read -r d
IFS= read -r e
[[ "$d" == "se.example.net" ]] || exit 22
[[ "$e" == "node@example.net" ]] || exit 23
printf '52\tVPN ready\n' > "$WPO_NODE_PROGRESS_FILE"
sleep 0.03
if [[ "@{WPO_NODE_FAKE_FAILURE:-0}" == 1 ]]; then
  echo "ERROR: simulated failure"
  exit 7
fi
printf '94\tRegistration ready\n' > "$WPO_NODE_PROGRESS_FILE"
exit 0
'''.replace("@{","$"+"{")
        script=root/"node-agent-wizard.sh"
        script.write_text(head)
        script.chmod(0o700)
        env=os.environ.copy()
        env["TERM"]="xterm-256color"
        env["WPO_NODE_FAKE_FAILURE"]="1" if failed else "0"
        command=["bash",str(script),"a"*43]
        if not interactive:
            p=subprocess.run(command,input="se.example.net\nnode@example.net\n",
                             text=True,capture_output=True,env=env,timeout=10)
            return p.returncode,p.stdout+p.stderr
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack("HHHH",28,90,0,0))
        proc=subprocess.Popen(command,stdin=slave,stdout=slave,stderr=slave,
                              env=env,start_new_session=True)
        os.close(slave)
        os.write(master,b"\nse.example.net\nnode@example.net\n")
        chunks=[]
        deadline=time.monotonic()+12
        try:
            while time.monotonic()<deadline:
                readable,_,_=select.select([master],[],[],0.15)
                if readable:
                    try: data=os.read(master,8192)
                    except OSError as exc:
                        if exc.errno==errno.EIO: break
                        raise
                    if not data: break
                    chunks.append(data)
                elif proc.poll() is not None:
                    break
            if proc.poll() is None:
                proc.kill()
                self.fail("Wizard did not exit")
            return proc.wait(),b"".join(chunks).decode("utf-8","replace")
        finally:
            os.close(master)

    def test_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            code,out=self.exercise(tmp)
            self.assertEqual(code,0,out[-1400:])
            for string in ["УСТАНОВКА НОДЫ","WEB PANEL ONLINE 3.0",
                           "НОДА УСТАНОВЛЕНА","100%","00:00:","\x1b[1;38;5;226m"]:
                self.assertIn(string,out)
            self.assertNotIn("Логин:",out)
            self.assertNotIn("Пароль:",out)

    def test_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            code,out=self.exercise(tmp,failed=True)
            self.assertEqual(code,7,out[-1000:])
            self.assertIn("Установка ноды прервана",out)
            self.assertIn("Подробности:",out)
            self.assertNotIn("НОДА УСТАНОВЛЕНА",out)

    def test_classic_no_tty(self):
        with tempfile.TemporaryDirectory() as tmp:
            code,out=self.exercise(tmp,interactive=False)
            self.assertEqual(code,0,out)
            self.assertIn("CLASSIC_WORKER_INTACT",out)
            self.assertNotIn("УСТАНОВКА НОДЫ",out)


if __name__=="__main__":
    unittest.main()
