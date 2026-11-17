"""One-command read-only SSH Happ diagnosis, preserving password secrecy."""
import ast
import contextlib
import importlib.util
import io
import json
import subprocess
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_fleet_ssh_diagnose",
    ROOT/"scripts/wpo-happ-fleet-ssh-diagnose.py")
diag=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

class FleetSshTests(unittest.TestCase):
    def test_local_and_remote_code_compile(self):
        compile((ROOT/"scripts/wpo-happ-fleet-ssh-diagnose.py").read_text(),
                "wpo-happ-fleet-ssh-diagnose.py","exec")
        compile(diag.REMOTE,"remote-probe.py","exec")

    def test_hosts_only_from_registered_https_addresses(self):
        self.assertEqual(diag.hostname({"url":"https://baby.goodarielservice.xyz"}),
                         "baby.goodarielservice.xyz")
        for uri in ("http://example.com","https://-attacker.example",
                    "https://root:secret@example.com","", "https://localhost"):
            with self.subTest(uri=uri),self.assertRaises(ValueError):
                diag.hostname({"url":uri})

    def test_ssh_does_not_request_a_password_in_code_or_expose_secret(self):
        fake=SimpleNamespace(returncode=0,stdout='{"ok":true,"client_secret":"sensitive-data"}\n')
        capture=io.StringIO()
        with patch.object(diag.subprocess,"run",return_value=fake) as run, \
             contextlib.redirect_stdout(capture):
            result=diag.ssh_check("swejeep.goodarielservice.xyz",["a"*64])
        argv=run.call_args.args[0]
        self.assertIn("-T",argv)
        self.assertIn("StrictHostKeyChecking=ask",argv)
        self.assertTrue(any(x.startswith("root@") for x in argv))
        self.assertNotIn("sshpass",str(argv))
        self.assertNotIn("sensitive-data",capture.getvalue())
        self.assertEqual(result["client_secret"],"sensitive-data")

    def test_diagnostic_does_not_modify_profiles_or_restart_daemons(self):
        src=(ROOT/"scripts/wpo-happ-fleet-ssh-diagnose.py").read_text()
        for forbidden in ("systemctl restart","systemctl reload",
            "sshpass", "curl -k", "StrictHostKeyChecking=no", "api.request(",
            "atomic_json(", "xray.apply(", "write_text('/etc/"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,src)
        self.assertIn("TemporaryDirectory(",src)
        self.assertIn("flow':'xtls-rprx-vision",src)
        self.assertIn("REALITY подписок",src)
        self.assertIn("HAProxy→Xray",src)
        self.assertIn("SSH-пароли" if "SSH-пароли" in src else "Пароли, UUID",src)

    def test_remote_static_routes_collect_kernel_policy_and_direct_outbound(self):
        tree=ast.parse(diag.REMOTE)
        defs=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.Import,ast.ImportFrom))]
        fixture=ast.fix_missing_locations(ast.Module(body=defs,type_ignores=[]))
        namespace={}
        exec(compile(fixture,"remote-static-probe","exec"),namespace)
        def fake_ip(*args):
            if args==('route','show','table','all'):
                return [
                    {'dst':'default','dev':'ens3','gateway':'192.0.2.1','table':'main'},
                    {'dst':'10.20.0.0/16','dev':'wg0','gateway':'192.0.2.2',
                     'table':100,'protocol':'static'},
                    {'dst':'198.51.100.0/24','dev':'ens3','protocol':'kernel','scope':'link'},
                ]
            if args==('rule','show'):
                return [
                    {'priority':0,'table':'local'},
                    {'priority':100,'table':100,'fwmark':'0x1'},
                    {'priority':32766,'table':'main'},
                    {'priority':32767,'table':'default'}]
            if args[:2]==('route','get'):
                return [{'dst':args[2],'dev':'wg0','gateway':'192.0.2.2','table':100}]
            raise AssertionError(args)
        namespace["ip_json"]=fake_ip
        result=SimpleNamespace(returncode=0,stdout='204 0.042')
        with patch.object(subprocess,"run",return_value=result), \
             patch.object(Path,"read_text",return_value="1"):
            routes=namespace["routes_snapshot"](
                {'outbounds':[{'protocol':'freedom'},{'protocol':'blackhole'}],
                 'routing':{'rules':[{'outboundTag':'direct'}]}})
        self.assertTrue(routes['available'])
        self.assertEqual(routes['static_count'],1)
        self.assertEqual(routes['static'][0]['dst'],'10.20.0.0/16')
        self.assertEqual(routes['policy_count'],1)
        self.assertEqual(routes['policy'][0]['fwmark'],'0x1')
        self.assertEqual(routes['get']['1.1.1.1']['dev'],'wg0')
        self.assertEqual(routes['rp_filter'],1)
        self.assertTrue(routes['xray_direct'])
        self.assertEqual(routes['xray_rules_count'],1)
        self.assertEqual(routes['direct_https204'],'42ms')

    def test_static_route_report_and_poland_comparison_are_separate(self):
        example={
            'available':True,'default':[{'dev':'ens3','gateway':'192.0.2.1'}],
            'get':{'1.1.1.1':{'dev':'ens3'},'8.8.8.8':{'dev':'ens3'}},
            'static_count':0,'static':[],'policy_count':0,'policy':[],
            'rp_filter':2,'xray_direct':True,'xray_rules_count':0,
            'direct_https204':'72ms'}
        captured=io.StringIO()
        with contextlib.redirect_stdout(captured):
            poland=diag.static_routes_view({'static_routes':example})
            sweden=diag.static_routes_view({'static_routes':{
                **example,'static_count':2,'policy_count':1,
                'rp_filter':1,'direct_https204':'FAIL'}})
            diag.routing_comparison([('Польша',poland),('Швеция',sweden)])
        report=captured.getvalue()
        self.assertIn('Статические маршруты и правила',report)
        self.assertIn('СРАВНЕНИЕ С ПОЛЬШЕЙ',report)
        self.assertIn('Швеция',report)
        self.assertIn('policy rules',report)
        self.assertIn('строгий rp_filter',report)
        self.assertIn('прямой HTTPS не прошёл',report)

    def test_route_diagnostics_cannot_alter_network_configuration(self):
        source=(ROOT/"scripts/wpo-happ-fleet-ssh-diagnose.py").read_text()
        for forbidden in ("ip route add","ip route del","ip route replace","ip rule add",
                          "ip rule del","ip route flush","iptables -A","nft add rule",
                          "sysctl -w","systemctl restart","systemctl reload",
                          "StrictHostKeyChecking=no"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden,source)
        self.assertIn("['ip','-j','-4',*args]",source)
        self.assertIn("('route','show','table','all')",source)
        self.assertIn("('rule','show')",source)
        self.assertIn("Xray direct/freedom",source)
        self.assertIn("Маршрут основной панели → нода",source)

    def test_real_haproxy_regex_matches_correct_target(self):
        router='''frontend wpo_tls
    use_backend reality if { req.ssl_sni -i www.nvidia.com }
backend reality
    server reality 127.0.0.1:19444
backend website
    server caddy 127.0.0.1:19443
'''
        sni="www.nvidia.com"
        pat=(r'(?im)^\s*use_backend\s+([a-zA-Z0-9_-]+)\s+if\s+\{\s*req\.ssl_sni\s+-i\s+'
             +re.escape(sni)+r'\s*\}')
        matched=re.search(pat,router)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.group(1),"reality")

if __name__=="__main__":
    unittest.main()
