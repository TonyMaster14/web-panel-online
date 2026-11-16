import tempfile
import unittest
from pathlib import Path
import wpp_ui
import wpp_connections as connections
import wpp_routing as routing
import wpo_reality as reality
import wpo_fast_actions_apply as patch

class RealityRoutingTests(unittest.TestCase):
    def test_reality_second_and_selectable_with_saved_state(self):
        items=connections.defaults()
        target=next(x for x in items if x['protocol']=='reality')
        html=wpp_ui.routing_ui(items,{'profiles':{target['id']:{'enabled':True}}},'/panel','token')
        self.assertIn('data-routing-choice="'+target['id']+'"',html)
        self.assertIn('data-routing-form="'+target['id']+'"',html)
        self.assertLess(html.index('<b>VLESS XHTTP</b>'),html.index('<b>VLESS TCP REALITY Vision</b>'))
        self.assertLess(html.index('<b>VLESS TCP REALITY Vision</b>'),html.index('<b>Hysteria2</b>'))
    def test_saved_rules_reach_reality_client(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'routing.json')
            routing.update_selected(path,'reality-connection',{'direct_domains_delta':'example.org'})
            profiles=routing.load(path)['profiles']
            profile=dict(reality.DEFAULT,address='203.0.113.2',public_key='a'*43,short_id='0123456789abcdef')
            user={'id':'a','protocol':'reality','connection_id':'reality-connection','name':'Test'}
            link=reality.link('11111111-1111-4111-8111-111111111111','Test',profile)
            result=routing.routed_configs([user],lambda _:link,profiles)
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['outbounds'][0]['streamSettings']['security'],'reality')
            self.assertTrue(any('domain:example.org' in r.get('domain',[]) for r in result[0]['routing']['rules']))
    def test_already_migrated_ui_gets_missing_tab_idempotently(self):
        old=Path('src/wpp_ui.py').read_text().replace("('reality','VLESS TCP REALITY Vision'),",'')
        new=patch.patch_ui(old)
        self.assertIn("('reality','VLESS TCP REALITY Vision')",new)
        self.assertEqual(new,patch.patch_ui(new))
    def test_existing_fast_patch_also_accepts_reality(self):
        source=patch.MARKER+'\nallowed=("vless","hysteria","awg20","awg31")\n'
        self.assertIn('"reality"',patch.patch_panel(source))

if __name__=='__main__':unittest.main()
