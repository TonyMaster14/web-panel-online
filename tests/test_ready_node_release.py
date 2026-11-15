"""Regressions from the confirmed November multi-node failure."""
import ast
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import wpp_routing
import wpo_node_status_patch

ROOT=Path(__file__).resolve().parents[1]
class NodeRelease(unittest.TestCase):
    def test_generated_installer_uses_fixed_backend_snapshot(self):
        installer=(ROOT/'wpo-node-agent-install-v2.sh').read_text()
        rev=re.search(r'^ENGINE_REV=([a-f0-9]{40})$',installer,re.M).group(1)
        self.assertEqual(rev,'007c4c1cddc86c900b841c1c0360127eb94c03d7')
        self.assertIn('native_changed = assemble(old) != assemble(new)',(ROOT/'wpo_node_eight.py').read_text())
        self.assertIn('os.chmod(tmp, 0o640)',(ROOT/'wpo_node_vpn.py').read_text())

    def test_recovered_node_becomes_selectable_and_lost_caps_are_cleared(self):
        source='def refresh(node,state):\n    if True:\n        if True:\n            if True:\n                if True:\n'+wpo_node_status_patch.OLD+'\n'
        result=wpo_node_status_patch.patch(source)
        self.assertEqual(wpo_node_status_patch.patch(result),result)
        scope={};exec(result,scope)
        node={'capabilities':['node-agent'],'status':'offline'}
        scope['refresh'](node,{'capabilities':['federation','vless','hysteria']})
        self.assertEqual(node['status'],'online')
        self.assertEqual(node['capabilities'],['federation','vless','hysteria'])
        scope['refresh'](node,{'capabilities':None})
        self.assertEqual(node['capabilities'],[])

    def test_install_probe_checks_real_sync_and_always_deletes_its_own_identity(self):
        installer=(ROOT/'wpo-node-agent-install-v2.sh').read_text()
        code=installer.split("<<'PY_PROVISION_CHECK'\n",1)[1].split('\nPY_PROVISION_CHECK',1)[0]
        self.assertLess(installer.index('PY_PROVISION_CHECK'),installer.index("report registration 'Все 8"))
        class Response:
            def __init__(self,value):self.value=value
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(self.value).encode()
        for fail in (False,True):
            calls=[]
            class Opener:
                def open(self,req,timeout):
                    body=json.loads(req.data);calls.append((req.full_url,body))
                    if req.full_url.endswith('/delete'):return Response({'ok':True})
                    if fail:raise OSError('read-only filesystem')
                    return Response({'ok':True,'profiles':[
                        {'protocol':'vless','link':'vless://key@node.example:443'},
                        {'protocol':'hysteria','link':'hysteria2://key@node.example:8443'}]})
            with patch('pathlib.Path.read_text',return_value=json.dumps({'domain':'node.example','api_key':'test'})), \
                 patch('urllib.request.build_opener',return_value=Opener()):
                if fail:
                    with self.assertRaises(SystemExit):exec(code,{})
                else:exec(code,{})
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0][1]['external_id'],calls[1][1]['external_id'])
            self.assertRegex(calls[0][1]['external_id'],r'^[a-f0-9]{64}$')

