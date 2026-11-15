"""Validate production subscription auto-selection and explicit routing policy."""
import unittest
from unittest.mock import patch
import wpp_routing as routing

class AutoSelect(unittest.TestCase):
    def links(self):
        return [link for host in ('nl.example','pl.example','se.example') for link in (
            f'vless://11111111-1111-4111-8111-111111111111@{host}:443?type=xhttp&security=tls&path=%2Ftest',
            f'hysteria2://secret@{host}:8443/?sni={host}')]

    def test_all_six_connections_are_observed(self):
        config=routing.failover_xray_config(self.links())
        candidates=[o for o in config['outbounds'] if o['tag'].startswith('proxy-')]
        self.assertEqual(len(candidates),6)
        self.assertEqual({o['tag'] for o in candidates},{f'proxy-{i}' for i in range(1,7)})
        self.assertEqual(config['routing']['balancers'][0]['strategy'],{'type':'leastPing'})
        self.assertEqual(config['routing']['balancers'][0]['selector'],config['observatory']['subjectSelector'])
        self.assertTrue(config['observatory']['enableConcurrency'])
        self.assertEqual(config['observatory']['probeInterval'],'10s')

    def test_all_down_fallback_is_block_not_first_node_or_direct(self):
        config=routing.failover_xray_config(self.links())
        fallback=config['routing']['balancers'][0]['fallbackTag']
        target=next(o for o in config['outbounds'] if o['tag']==fallback)
        self.assertEqual(target['protocol'],'blackhole')

    def test_bad_or_non_vpn_links_do_not_leave_missing_tags(self):
        config=routing.failover_xray_config(['https://example.com','vless://bad']+self.links()[:1])
        self.assertEqual(config['outbounds'][0]['tag'],'proxy-1')
        self.assertEqual(config['outbounds'][0]['settings']['vnext'][0]['address'],'nl.example')

    def test_custom_direct_and_block_rules_keep_their_meaning(self):
        profile={'enabled':True,'private_direct':True,'block_bittorrent':True,
                 'direct_domains':['domain:example.org'],'proxy_domains':['domain:example.net']}
        original=profile.copy()
        config=routing.failover_xray_config(self.links(),profile)
        rules=config['routing']['rules']
        self.assertTrue(any(r.get('outboundTag')=='direct' for r in rules))
        self.assertTrue(any(r.get('outboundTag')=='block' for r in rules))
        self.assertTrue(any(r.get('balancerTag')=='auto' for r in rules))
        self.assertFalse(any(r.get('outboundTag')=='proxy' for r in rules))
        self.assertEqual(profile,original)

    def test_no_supported_links_is_an_error(self):
        with self.assertRaises(routing.RoutingError):
            routing.failover_xray_config(['https://example.com'])
