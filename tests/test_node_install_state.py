"""Run the exact node cleanup against disposable paths and fake system services."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT/'nodes/wpo-node-agent-install-v2.sh'
BEGIN='python3 - "$1" <<\'PY_WPO_NODE_STATE\'\n'

class TestNodeInstallState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content=AGENT.read_text()
        cls.logic=cls.content.split(BEGIN,1)[1].split('\nPY_WPO_NODE_STATE',1)[0]
    def sandbox(self,temp):
        root=Path(temp)
        for name in ('bin','etc/wpp-node-agent','opt/wpp-node-agent','etc/systemd/system','etc/caddy'):
            (root/name).mkdir(parents=True)
        cfg=root/'etc/wpp-node-agent/config.json';cfg.write_text('{"domain":"old.example.net"}')
        (root/'opt/wpp-node-agent/agent.py').write_text('# WPO')
        (root/'etc/caddy/Caddyfile').write_text('old.example.net {}')
        system=root/'bin/systemctl'
        system.write_text('''#!/bin/sh
base=$(dirname "$0")
echo "$*" >> "$base/calls"
case "$1" in
 is-active) test -f "$base/active-$3" && test ! -f "$base/stopped-$3"; exit $?;;
 disable) touch "$base/stopped-$3";;
 stop) touch "$base/stopped-$2";;
 list-units|list-unit-files) echo 'web-panel-proxy-awg@abcdef.service loaded active'; echo 'wpo-node-mtproxy-abcdef.service loaded active';;
esac
exit 0
''');system.chmod(0o755)
        nft=root/'bin/nft';nft.write_text('#!/bin/sh\nexit 0\n');nft.chmod(0o755)
        logic=self.logic
        for prefix in ('/etc/','/opt/','/var/','/usr/local/'):
            logic=logic.replace(prefix,str(root)+prefix)
        env=dict(os.environ,PATH=str(root/'bin')+':'+os.environ['PATH'])
        env.pop('WPO_NODE_REINSTALL_APPROVED',None)
        return root,cfg,logic,env
    def run_state(self,code,env,mode='check',approved=False):
        env=dict(env)
        if approved:env['WPO_NODE_REINSTALL_APPROVED']='1'
        return subprocess.run(['python3','-c',code,mode],text=True,capture_output=True,env=env,timeout=10)
    def test_detects_registered_incomplete_and_corrupt_without_writes(self):
        for kind in ('registered','partial','corrupt'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root,cfg,code,env=self.sandbox(temp)
                if kind=='registered':(cfg.parent/'registered.json').write_text('{"registered":true}')
                if kind=='partial':cfg.unlink()
                if kind=='corrupt':cfg.write_text('{invalid')
                before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                r=self.run_state(code,env);self.assertEqual(r.returncode,20,r.stderr)
                for path,body in before.items():self.assertEqual(Path(path).read_bytes(),body)
                self.assertNotIn('disable',(root/'bin/calls').read_text())
    def test_cleanup_requires_explicit_yes(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            r=self.run_state(code,env,'cleanup');self.assertEqual(r.returncode,30)
            self.assertTrue(cfg.exists());self.assertNotIn('disable',(root/'bin/calls').read_text())
    def test_yes_removes_registered_profiles_reality_and_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            files={'etc/wpp-node-agent/registered.json':'{"registered":true}',
                'etc/wpp-node-vpn/profiles.json':'{"profiles":{"real-user":{"secret":"old"}}}',
                'etc/web-proxy-panel/reality/private.key':'old-reality-secret',
                'etc/web-proxy-panel/awg/abcdef.json':'{}',
                'etc/systemd/system/wpp-node-agent.service':'Service=1',
                'etc/systemd/system/wpo-tls-router.service':'Service=1',
                'etc/systemd/system/wpo-node-mtproxy-abcdef.service':'Service=1',
                'usr/local/sbin/web-panel-proxy-awg-down':'old helper',
                'opt/web-panel-proxy/xray/xray':'old binary'}
            for name,body in files.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
            for name in ('wpp-node-agent.service','wpo-tls-router.service','caddy.service','web-panel-proxy-awg@abcdef.service'):
                (root/'bin'/('active-'+name)).touch()
            foreign=root/'etc/other-project';foreign.write_text('KEEP')
            r=self.run_state(code,env,'cleanup',True);self.assertEqual(r.returncode,0,r.stderr)
            self.assertFalse(cfg.exists())
            for name in files:self.assertFalse((root/name).exists(),name)
            self.assertEqual(foreign.read_text(),'KEEP')
            self.assertNotIn('old.example.net',(root/'etc/caddy/Caddyfile').read_text())
            calls=(root/'bin/calls').read_text()
            self.assertIn('disable --now web-panel-proxy-awg@abcdef.service',calls)
            self.assertIn('disable --now wpo-tls-router.service',calls)
    def test_yes_handles_partial_without_config_or_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp);cfg.unlink();(root/'opt/wpp-node-agent/agent.py').unlink()
            r=self.run_state(code,env,'cleanup',True);self.assertEqual(r.returncode,0,r.stderr)
            self.assertFalse(cfg.parent.exists())
    def test_main_panel_is_protected_even_with_yes(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            p=root/'opt/tproxy-panel/panel.py';p.parent.mkdir();p.write_text('KEEP')
            r=self.run_state(code,env,'cleanup',True);self.assertEqual(r.returncode,30)
            self.assertTrue(cfg.exists());self.assertEqual(p.read_text(),'KEEP')
    def test_symlink_parent_cannot_remove_foreign_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            target=root/'foreign';target.mkdir();(target/'secret').write_text('KEEP')
            (root/'etc/web-proxy-panel').symlink_to(target,target_is_directory=True)
            r=self.run_state(code,env,'cleanup',True);self.assertEqual(r.returncode,30)
            self.assertTrue(cfg.exists());self.assertEqual((target/'secret').read_text(),'KEEP')
    def test_failed_service_stop_preserves_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            system=root/'bin/systemctl'
            system.write_text(system.read_text().replace('disable) touch "$base/stopped-$3";;','disable) exit 1;;'))
            (root/'bin/active-wpp-node-agent.service').touch()
            r=self.run_state(code,env,'cleanup',True);self.assertEqual(r.returncode,30)
            self.assertTrue(cfg.exists());self.assertTrue((root/'opt/wpp-node-agent/agent.py').exists())
    def test_clean_host_needs_no_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            import shutil
            shutil.rmtree(cfg.parent);shutil.rmtree(root/'opt/wpp-node-agent')
            for mode in ('check','cleanup'):
                self.assertEqual(self.run_state(code,env,mode).returncode,0)
    def test_cleanup_only_after_validated_input(self):
        source=self.content
        pos=source.index('wpo_node_install_state cleanup')
        self.assertGreater(pos,source.index('Некорректный домен.'))
        self.assertGreater(pos,source.index('неверный email.'))
        self.assertLess(pos,source.index('apt-get update'))

if __name__=='__main__':unittest.main()
