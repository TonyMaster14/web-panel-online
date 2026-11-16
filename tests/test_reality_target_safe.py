"""Node REALITY target switch: no writes before true tunnel proof, rollback on failure."""
import importlib.util
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wpo_safe_target",ROOT/"scripts/wpo-reality-target-safe.py")
target=importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)

PROFILE={"preset":"microsoft","sni":"www.microsoft.com",
         "public_key":"P"*43,"short_id":"1234567890abcdef",
         "fingerprint":"firefox","address":"192.145.28.78"}
CLIENT={"id":"11111111-1111-4111-8111-111111111111","flow":"xtls-rprx-vision"}
INBOUND={"listen":"127.0.0.1","port":19444,"protocol":"vless",
 "settings":{"clients":[CLIENT],"decryption":"none"},
 "streamSettings":{"security":"reality","network":"tcp",
   "realitySettings":{"target":"www.microsoft.com:443",
       "serverNames":["www.microsoft.com"],"privateKey":"S"*43,
       "shortIds":["1234567890abcdef"]}}}


class FakeReality:
    def __init__(self):
        self.profile=dict(PROFILE)
        self.events=[]
        self.PUBLIC=Path("/unused/profile.json")
        self.ROOT=Path("/unused")

    def check_target(self,sni):
        self.events.append(("target",sni))

    def configure(self,request,apply):
        self.events.append(("configure",request["sni"]))
        self.profile.update(request)
        apply()
        return {"ok":True}

    def read_profile(self):
        return dict(self.profile)


class FakeVPN:
    STATE=Path("/unused/state.json")
    def __init__(self):
        self.applies=0
    def read_json(self,path,default):
        return {"profiles":{"untouched":{"protocol":"reality"}}}
    def apply(self,profiles):
        assert "untouched" in profiles
        self.applies+=1


class TargetTests(TestCase):
    def setUp(self):
        self.reality=FakeReality()
        self.vpn=FakeVPN()
        self.events=[]

    def test_isolated_probe_failure_never_touches_running_settings(self):
        with patch.object(target,"backups",side_effect=AssertionError("No backups before proof")):
            with self.assertRaises(target.TargetError):
                target.change(self.reality,self.vpn,"www.nvidia.com",PROFILE,INBOUND,CLIENT,
                              probe=lambda *args,**kw: False)
        self.assertEqual(self.reality.profile,PROFILE)
        self.assertEqual(self.vpn.applies,0)

    def test_success_proves_isolated_and_live_443_without_new_keys(self):
        ports=[]
        def test_probe(sni,profile,client,inbound,port=None):
            ports.append(port)
            self.assertEqual(profile["short_id"],PROFILE["short_id"])
            self.assertEqual(profile["public_key"],PROFILE["public_key"])
            self.assertEqual(client,CLIENT)
            return True
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(target,"backups",return_value=Path(folder)), \
                 patch.object(target,"verify_services",return_value=None):
                result=target.change(self.reality,self.vpn,"www.nvidia.com",
                                     PROFILE,INBOUND,CLIENT,probe=test_probe)
        self.assertTrue(result)
        self.assertEqual(ports,[None,443])
        self.assertEqual(self.reality.profile["sni"],"www.nvidia.com")
        self.assertEqual(self.reality.profile["public_key"],PROFILE["public_key"])
        self.assertEqual(self.reality.profile["short_id"],PROFILE["short_id"])
        self.assertEqual(self.vpn.applies,1)

    def test_failed_live_tunnel_always_rolls_back(self):
        events=[]
        def test_probe(sni,profile,client,inbound,port=None):
            events.append(("probe",port))
            return port is None
        def fake_revert(reality,vpn,backup):
            events.append(("rollback",str(backup)))
            reality.profile=dict(PROFILE)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(target,"backups",return_value=Path(folder)), \
                 patch.object(target,"verify_services",return_value=None), \
                 patch.object(target,"revert",side_effect=fake_revert):
                with self.assertRaisesRegex(target.TargetError,"Изменения отменены"):
                    target.change(self.reality,self.vpn,"www.nvidia.com",
                                  PROFILE,INBOUND,CLIENT,probe=test_probe)
        self.assertEqual(events[0],("probe",None))
        self.assertEqual(events[1],("probe",443))
        self.assertEqual(events[2][0],"rollback")
        self.assertEqual(self.reality.profile,PROFILE)

    def test_failed_service_check_rolls_back_without_live_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(target,"backups",return_value=Path(folder)), \
                 patch.object(target,"verify_services",side_effect=target.TargetError("offline")), \
                 patch.object(target,"revert") as rollback:
                with self.assertRaises(target.TargetError):
                    target.change(self.reality,self.vpn,"www.nvidia.com",
                                  PROFILE,INBOUND,CLIENT,probe=lambda *args,**kw: True)
                rollback.assert_called_once()

    def test_copies_and_preserves_original_real_node_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            root=base/"reality"
            root.mkdir()
            xray=base/"xray.json"
            (root/"profile.json").write_text("old-profile")
            (root/"haproxy.cfg").write_text("old-router")
            xray.write_text("old-xray")
            with patch.object(target,"SYSREALITY",root),patch.object(target,"XRAY_FILE",xray):
                backup=target.backups()
                self.assertEqual((backup/"profile.json").read_text(),"old-profile")
                self.assertEqual((backup/"haproxy.cfg").read_text(),"old-router")
                self.assertEqual((backup/"xray.json").read_text(),"old-xray")
                self.assertEqual(backup.stat().st_mode & 0o777,0o700)

    def test_shell_has_no_reinstall_or_token_regeneration(self):
        text=(ROOT/"scripts/wpo-reality-target-safe.py").read_text()
        self.assertNotIn("secrets.token_",text)
        self.assertNotIn("apt-get",text)
        self.assertNotIn("install.sh",text)
        self.assertIn("www.nvidia.com",text)
        self.assertIn("--socks5-hostname",text)
        self.assertIn("HTTP",text)

if __name__=="__main__":
    import unittest
    unittest.main()
