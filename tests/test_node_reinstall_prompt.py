"""Exercise the real yes/no gate in a pseudo-terminal without touching a VPS."""
import os
from pathlib import Path
import pty
import select
import subprocess
import tempfile
import time
import unittest

SOURCE=(Path(__file__).resolve().parents[1]/'nodes/wpo-node-agent-install-v2.sh').read_text()
GATE=SOURCE.split('# WPO_NODE_REINSTALL_GATE:',1)[1].split('# WPO_NODE_REINSTALL_GATE_END',1)[0]
GATE=GATE[GATE.index('\n'):]

class NodeReinstallPrompt(unittest.TestCase):
    def exercise(self,reply=None,tty=True,worker=False):
        with tempfile.TemporaryDirectory() as td:
            trace=Path(td)/'cleaned';script=Path(td)/'gate.sh'
            script.write_text('set -Eeuo pipefail\nwpo_node_install_state(){ if [[ "$1" == check ]]; then return 20; fi; printf cleaned > "$TRACE"; }\n'+GATE+'\nwpo_node_install_state cleanup\n')
            env=dict(os.environ,TRACE=str(trace),WPO_NODE_REINSTALL_APPROVED='1')
            env['WPO_NODE_WIZARD_WORKER']='1' if worker else '0'
            if not tty:
                result=subprocess.run(['bash',str(script)],input=reply or '',text=True,capture_output=True,env=env,timeout=5)
                return result.returncode,result.stdout+result.stderr,trace.exists()
            master,slave=pty.openpty();proc=subprocess.Popen(['bash',str(script)],stdin=slave,stdout=slave,stderr=slave,env=env)
            os.close(slave);out=b'';sent=False
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    ready,_,_=select.select([master],[],[],.05)
                    if ready:
                        try:chunk=os.read(master,8192)
                        except OSError:break
                        if not chunk:break
                        out+=chunk
                        if b'(yes/no):' in out and not sent:
                            os.write(master,(reply or '').encode());sent=True
                    if proc.poll() is not None:break
                proc.wait(timeout=2)
                return proc.returncode,out.decode(errors='replace'),trace.exists()
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
                os.close(master)
    def test_no_preserves_node(self):
        code,out,clean=self.exercise('no\n');self.assertEqual(code,0);self.assertFalse(clean);self.assertIn('сохранена',out)
    def test_blank_preserves_node(self):
        self.assertFalse(self.exercise('\n')[2])
    def test_yes_continues_after_one_prompt(self):
        code,out,clean=self.exercise('yes\n');self.assertEqual(code,0);self.assertTrue(clean);self.assertEqual(out.count('(yes/no):'),1)
    def test_invalid_then_no_does_not_clean(self):
        code,out,clean=self.exercise('maybe\nno\n');self.assertEqual(code,0);self.assertFalse(clean);self.assertIn('Введите yes или no',out)
    def test_piped_yes_cannot_approve(self):
        code,out,clean=self.exercise('yes\n',tty=False);self.assertNotEqual(code,0);self.assertFalse(clean)
    def test_worker_inherits_explicit_answer_without_second_prompt(self):
        code,out,clean=self.exercise(tty=False,worker=True);self.assertEqual(code,0);self.assertTrue(clean);self.assertNotIn('(yes/no):',out)

if __name__=='__main__':unittest.main()
