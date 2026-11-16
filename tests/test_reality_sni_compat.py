"""Regression: changing REALITY target must not strand existing Happ URIs.

Each supported SNI has its OWN matching upstream/HAProxy backend, so clients
already imported from Happ can use old SNI until they refresh subscriptions.
Existing UUID, short ID and key stay identical across inbounds.
"""
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlparse
import wpo_reality as r
import wpo_node_vpn as vpn

UUID="11111111-1111-4111-8111-111111111111"
CLIENTS=[{"id":UUID,"flow":"xtls-rprx-vision","level":0}]
PROFILE=dict(r.DEFAULT,address="203.0.113.5",public_key="a"*43,short_id="0123456789abcdef")

class RealitySniCompatibility(unittest.TestCase):
    def test_preset_transitions_keep_unique_matching_backend_for_every_sni(self):
        for chosen in ("www.nvidia.com","www.apple.com","www.yahoo.com","www.amazon.com"):
            with self.subTest(current=chosen):
                profile=dict(PROFILE,sni=chosen,preset="custom")
                with patch.object(r,"PRIVATE",Mock(read_text=lambda: "p"*43)):
                    items=r.inbounds(CLIENTS,profile)
                names=[item["streamSettings"]["realitySettings"]["serverNames"][0] for item in items]
                self.assertEqual(names[0],chosen)
                self.assertEqual(set(names),{x[1] for x in r.PRESETS.values()})
                self.assertEqual(len(names),len(set(names)))
                self.assertEqual([item["port"] for item in items],list(range(r.PORT,r.PORT+len(items))))
                self.assertEqual(len({item["tag"] for item in items}),len(items))
                for inbound in items:
                    settings=inbound["streamSettings"]["realitySettings"]
                    self.assertEqual(settings["target"],settings["serverNames"][0]+":443")
                    self.assertEqual(settings["privateKey"],"p"*43)
                    self.assertEqual(settings["shortIds"],[PROFILE["short_id"]])
                    self.assertEqual(inbound["settings"]["clients"],CLIENTS)
                    self.assertEqual(inbound["listen"],"127.0.0.1")
                hap=r.haproxy_config(chosen)
                for host,port in r.reality_routes(profile):
                    backend="reality" if port==r.PORT else "reality_"+str(port)
                    self.assertIn("use_backend "+backend+" if { req.ssl_sni -i "+host+" }",hap)
                    self.assertIn("server "+backend+" 127.0.0.1:"+str(port),hap)
                self.assertIn("default_backend website",hap)
                self.assertNotIn("microsoft.com",hap)

    def test_new_links_include_only_selected_sni(self):
        for host in (x[1] for x in r.PRESETS.values()):
            p=dict(PROFILE,sni=host,preset="custom")
            q=parse_qs(urlparse(r.link(UUID,"WPO",p)).query)
            self.assertEqual(q["sni"],[host])
            self.assertEqual(q["pbk"],[PROFILE["public_key"]])
            self.assertEqual(q["sid"],[PROFILE["short_id"]])

    def test_main_manager_extends_inbounds_for_all_supported_sni(self):
        source=Path("src/wpo_reality.py").read_text()
        self.assertIn("config['inbounds'].extend(inbounds(clients))",source)
        self.assertNotIn("config['inbounds'].append(inbound(clients))",source)

    def test_node_agent_generates_matching_inbounds_without_changing_secrets(self):
        with patch.object(vpn,"REALITY_READY",True), \
             patch.object(r,"PRIVATE",Mock(read_text=lambda: "p"*43)), \
             patch.object(r,"read_profile",return_value=dict(PROFILE)), \
             patch.object(vpn,"SUPPORTED",frozenset(("vless","hysteria","reality"))):
            state={"f"*64:{"secrets":{"reality":UUID},"name":"test"}}
            data=vpn.render_xray(state,{"domain":"node.example.com","xhttp_path":"/xhttp"})
        realities=[x for x in data["inbounds"] if x.get("streamSettings",{}).get("security")=="reality"]
        self.assertEqual(len(realities),len(r.PRESETS))
        for item in realities:
            self.assertEqual(item["settings"]["clients"][0]["id"],UUID)

    def test_safe_compat_updaters_validate_and_rollback(self):
        root=Path(__file__).resolve().parents[1]
        for name in ("wpo-reality-sni-compat-node.sh","wpo-reality-sni-compat-controller.sh"):
            with self.subTest(name=name):
                script=root/"scripts"/name
                shell=script.read_text()
                result=subprocess.run(["bash","-n",str(script)],capture_output=True,text=True,timeout=6)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn("REV=1d165774d088978a60fb2366e298a93a3e73af48",shell)
                self.assertIn("BACKUP",shell)
                self.assertIn("INSTALLED=1",shell)
                self.assertIn("haproxy -c -f",shell)
                self.assertIn("run -test -config",shell)
                self.assertNotIn("xray x25519",shell)
                self.assertNotIn("apt-get",shell)
                self.assertNotIn("secrets.token",shell)

    def test_custom_target_also_keeps_supported_default_domains(self):
        p=dict(PROFILE,sni="custom.example.org",preset="custom")
        routes=r.reality_routes(p)
        self.assertEqual(len(routes),len(r.PRESETS)+1)
        self.assertEqual(routes[0],("custom.example.org",r.PORT))
        self.assertNotIn("www.microsoft.com",[h for h,_ in routes])

if __name__=="__main__":
    unittest.main()
