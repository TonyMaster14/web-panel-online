"""Reattach is safe: parse a generated command as data, never reinstall a VPS."""
import importlib.util
from pathlib import Path
import shlex
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/"scripts/wpo-node-reattach.py"
spec=importlib.util.spec_from_file_location("wpo_node_reattach",PATCH)
reattach=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reattach)

DOMAIN="cooln.goodarielservice.xyz"
KEY="k"*43
TOKEN="t"*43
PANEL="https://panel.example.com/secret-admin-route"

def generated_command(token=TOKEN):
    inner=(f'curl -4fsSL "{PANEL}/node-agent-installer.sh" '
           f'-o /tmp/wpo-node-install.sh && bash /tmp/wpo-node-install.sh "{token}"; '
           'code=$?; rm -f /tmp/wpo-node-install.sh; exit $code')
    return "sudo -i bash -c "+shlex.quote(inner)

class TestSafeReattach(unittest.TestCase):
    def test_copy_paste_command_parsed_without_execution(self):
        enroll,token=reattach.parse_command(generated_command())
        self.assertEqual(enroll,PANEL+"/node-enroll")
        self.assertEqual(token,TOKEN)

    def test_rejects_malformed_or_external_commands(self):
        for cmd in (
            "sudo bash -c 'curl evil'",
            generated_command().replace(" -o /tmp/", " ; rm -rf / ; -o /tmp/"),
            generated_command().replace("https://panel.example.com","http://panel.example.com"),
            generated_command().replace('"'+TOKEN+'"','"bad"'),
        ):
            with self.subTest(cmd=cmd[:70]), self.assertRaises(reattach.ReattachError):
                reattach.parse_command(cmd)

    def test_existing_node_reenrolled_using_the_same_key(self):
        calls=[]
        def fake_transport(url,method,headers=None,payload=None):
            calls.append((url,method,headers,payload))
            if method=="GET":
                return {"ok":True,"domain":DOMAIN}
            return {"ok":True,"node_id":"deadbeef00112233"}
        result=reattach.reattach(
            {"domain":DOMAIN,"api_key":KEY},
            {"registered":True,"domain":DOMAIN},
            generated_command(),fake_transport
        )
        self.assertEqual(result,DOMAIN)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][0],"https://"+DOMAIN+"/wpp-api/v1/status")
        self.assertEqual(calls[1][0],PANEL+"/node-enroll")
        self.assertEqual(calls[1][3],{
            "token":TOKEN,"url":"https://"+DOMAIN,
            "api_key":KEY,"name":"cooln"})

    def test_prevents_reenroll_on_incomplete_node(self):
        def no_network(*args):
            self.fail("No network should be used")
        with self.assertRaises(reattach.ReattachError):
            reattach.reattach(
                {"domain":DOMAIN,"api_key":KEY},
                {"registered":False,"domain":DOMAIN},
                generated_command(),no_network)

    def test_rejects_failed_node_status_and_failed_controller(self):
        state={"domain":DOMAIN,"api_key":KEY}
        receipt={"registered":True,"domain":DOMAIN}
        with self.assertRaises(reattach.ReattachError):
            reattach.reattach(state,receipt,generated_command(),
                lambda *a,**kw: {"ok":False,"domain":DOMAIN})
        def bad_controller(url,*args):
            return {"ok":True,"domain":DOMAIN} if url.startswith("https://"+DOMAIN) else {"ok":False}
        with self.assertRaises(reattach.ReattachError):
            reattach.reattach(state,receipt,generated_command(),bad_controller)

if __name__=="__main__":
    unittest.main()
