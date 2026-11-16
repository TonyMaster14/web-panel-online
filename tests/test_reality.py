import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
import wpo_reality as reality
import wpo_reality_apply as migration
import wpp_connections as connections
import wpp_subscriptions as subscriptions
import wpp_routing as routing
import wpo_user_v28 as ui

ROOT=Path(__file__).resolve().parents[1]
class RealityTests(unittest.TestCase):
    def test_client_server_and_routing_agree(self):
        profile=dict(reality.DEFAULT,address='203.0.113.2',public_key='a'*43,short_id='0123456789abcdef')
        secret='11111111-1111-4111-8111-111111111111'
        uri=reality.link(secret,'test',profile)
        q=parse_qs(urlparse(uri).query)
        self.assertEqual(q['fp'],['firefox']);self.assertEqual(q['sni'],[profile['sni']])
        config=routing._vless_outbound(uri)
        self.assertEqual(config['streamSettings']['network'],'tcp')
        self.assertEqual(config['streamSettings']['realitySettings']['shortId'],profile['short_id'])
        self.assertEqual(config['settings']['vnext'][0]['users'][0]['flow'],'xtls-rprx-vision')
        self.assertNotIn('xhttpSettings',config['streamSettings'])
    def test_default_and_migration_order_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'connections.json')
            old=connections.defaults();old=[x for x in old if x['protocol']!='reality']
            connections.save(path,{'connections':old})
            state=connections.ensure(path)
            self.assertEqual(state['connections'][1]['protocol'],'reality')
            connections.remove(path,'reality-primary',[])
            self.assertNotIn('reality',[x['protocol'] for x in connections.ensure(path)['connections']])
    def test_subscription_provisions_real_uuid_and_port(self):
        state={'users':[]}
        sub={'id':'a'*16,'name':'Test','enabled':True,'connections':[{'id':'reality-primary','name':'Reality','protocol':'reality'}]}
        subscriptions.provision(state,sub,{'id':'b'*16,'name':'Device'})
        self.assertEqual(state['users'][0]['backend_port'],443)
        self.assertEqual(state['users'][0]['protocol'],'reality')
        self.assertEqual(len(state['users'][0]['secret']),36)
    def test_invalid_sni_and_fingerprint(self):
        for bad in ('localhost','127.0.0.1','x.com\nbackend evil','https://apple.com'):
            with self.assertRaises(ValueError):reality.normalize({'preset':'custom','sni':bad})
        with self.assertRaises(ValueError):reality.normalize({'fingerprint':'unknown'})
    def test_caddy_and_sni_front(self):
        caddy='{\n auto_https disable_redirects\n}\nnode.example.com {\n respond "ok"\n}\n'
        actual=reality.caddy_internal(caddy)
        self.assertEqual(actual,reality.caddy_internal(actual))
        self.assertIn('https_port 19443',actual)
        router=reality.haproxy_config('www.nvidia.com')
        self.assertIn('default_backend website',router)
        self.assertIn('server reality 127.0.0.1:19444',router)
        self.assertNotIn('ssl crt',router)
    def test_existing_servers_options_are_preserved_without_duplicate(self):
        original='{\n admin off\n servers {\n  protocols h1 h2 h3\n  max_header_size 2MB\n }\n}\nnode.example.com {\n respond "ok"\n}\n'
        actual=reality.caddy_internal(original)
        self.assertEqual(actual.count('servers {'),1)
        self.assertIn('max_header_size 2MB',actual)
        self.assertNotIn('protocols h1 h2 h3',actual)
        self.assertEqual(actual,reality.caddy_internal(actual))
    def test_legacy_duplicate_fragment_is_repaired(self):
        old='{\n    # wpo-reality-front\n    https_port 19443\n    default_bind 127.0.0.1\n    servers {\n        protocols h1 h2\n    }\n servers {\n max_header_size 2MB\n }\n}\nnode.example.com { respond "ok" }\n'
        actual=reality.caddy_internal(old)
        self.assertEqual(actual.count('servers {'),1)
        self.assertIn('max_header_size 2MB',actual)
        self.assertEqual(actual,reality.caddy_internal(actual))
    def test_installed_python_migrations_compile_and_repeat(self):
        src=(ROOT/'installers/install-panel.sh').read_text()
        for anchor,fn in [('cat > "$MANAGER"',migration.patch_manager),('cat > "$APP_FILE"',migration.patch_panel)]:
            original=src.split(anchor+" <<'PY'\n",1)[1].split('\nPY\n',1)[0]
            changed=fn(original);ast.parse(changed)
            self.assertEqual(changed,fn(changed))
        changed=migration.patch_ui((ROOT/'src/wpp_ui.py').read_text());ast.parse(changed)
        self.assertEqual(changed,migration.patch_ui(changed))
    def test_form_order(self):
        html=ui.form('/panel','csrf',connections.defaults())
        self.assertLess(html.index('data-protocol="reality"'),html.index('data-protocol="web"'))
        self.assertGreater(html.index('data-protocol="hysteria"'),html.index('data-protocol="mieru"'))
        self.assertIn('wpo-reality-hysteria',html)

if __name__=='__main__':unittest.main()
