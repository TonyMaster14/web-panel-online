"""Prove the node installer cannot destroy a registered node or user profiles.

Tests run the exact embedded preflight Python logic against temporary paths
with mocked systemd and nft; no host services or real directories touched.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
AGENT=ROOT/"nodes/wpo-node-agent-install-v2.sh"
BEGIN="python3 - \"$1\" <<'PY_WPO_NODE_STATE'\n"
END="\nPY_WPO_NODE_STATE"


class TestNodeInstallState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        content=AGENT.read_text(encoding="utf-8")
        assert content.count(BEGIN)==1
        assert content.count(END)==1
        cls.logic=content.split(BEGIN,1)[1].split(END,1)[0]
        cls.content=content
        assert content.index('PY_WPO_NODE_REGISTERED')>content.index('if ENROLL_RESULT=')
        assert content.index('wpo_node_install_state cleanup')<content.index('apt-get update')

    def sandbox(self,location,active=()):
        root=Path(location)
        (root/"bin").mkdir()
        (root/"etc/wpp-node-agent").mkdir(parents=True)
        (root/"opt/wpp-node-agent").mkdir(parents=True)
        (root/"etc/systemd/system").mkdir(parents=True)
        (root/"etc/caddy").mkdir(parents=True)
        (root/"etc/caddy/Caddyfile").write_text("node-old.example.net { respond OK }\n")
        script=root/"bin/systemctl"
        pattern="|".join("'"+x+"'" for x in active) or "'__never_active__'"
        script.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = is-active ]; then\n"
            "  case \"$3\" in "+pattern+")\n"
            "    [ -e \"$(dirname \"$0\")/stopped-$3\" ] || exit 0;;\n"
            "  esac\n"
            "  exit 3\n"
            "fi\n"
            "if [ \"$1\" = disable ] && [ \"$2\" = --now ]; then\n"
            "  touch \"$(dirname \"$0\")/stopped-$3\"\n"
            "fi\n"
            "exit 0\n"
        )
        script.chmod(0o755)
        nft=root/"bin/nft"
        nft.write_text("#!/bin/sh\nexit 0\n")
        nft.chmod(0o755)
        cfg=root/"etc/wpp-node-agent/config.json"
        cfg.write_text(json.dumps({"domain":"old.example.net","version":"0.2.0"}))
        (root/"opt/wpp-node-agent/agent.py").write_text("# mock WPO Agent\n")
        logic=self.logic
        mapping={
            "/etc/wpp-node-agent":str(root/"etc/wpp-node-agent"),
            "/opt/wpp-node-agent":str(root/"opt/wpp-node-agent"),
            "/etc/wpp-node-vpn":str(root/"etc/wpp-node-vpn"),
            "/etc/systemd/system":str(root/"etc/systemd/system"),
            "/opt/tproxy-panel":str(root/"opt/tproxy-panel"),
            "/etc/tproxy-server":str(root/"etc/tproxy-server"),
            "/etc/mtproxy":str(root/"etc/mtproxy"),
            "/etc/web-proxy-panel":str(root/"etc/web-proxy-panel"),
            "/var/www/wpp-node-site":str(root/"var/www/wpp-node-site"),
            "/var/backups":str(root/"backups"),
            "/var/log/web-panel-online":str(root/"logs"),
            "/etc/caddy/Caddyfile":str(root/"etc/caddy/Caddyfile"),
        }
        for old,new in sorted(mapping.items(),key=lambda pair: -len(pair[0])):
            logic=logic.replace(old,new)
        env=os.environ.copy()
        env["PATH"]=str(root/"bin")+os.pathsep+env.get("PATH","")
        return root,cfg,logic,env

    def run_preflight(self,code,env,mode="check"):
        return subprocess.run(
            ["python3","-c",code,mode],
            text=True,capture_output=True,env=env,timeout=10
        )

    def test_incomplete_is_cleaned_before_new_attempt_with_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"etc/wpp-node-vpn").mkdir(parents=True)
            (root/"etc/wpp-node-vpn/settings.json").write_text(
                json.dumps({"domain":"different.example.net"})
            )
            (root/"etc/wpp-node-vpn/profiles.json").write_text('{"profiles":{}}')
            (root/"etc/systemd/system/wpp-node-agent.service").write_text("Agent=1")
            self.assertEqual(self.run_preflight(code,env).returncode,0)
            clean=self.run_preflight(code,env,"cleanup")
            self.assertEqual(clean.returncode,0,clean.stderr)
            self.assertFalse(cfg.exists())
            self.assertFalse((root/"opt/wpp-node-agent/agent.py").exists())
            self.assertFalse((root/"etc/wpp-node-vpn/settings.json").exists())
            self.assertTrue((root/"etc/caddy/Caddyfile").exists())
            backups=list((root/"backups").glob("wpo-node-incomplete-*"))
            self.assertEqual(len(backups),1)
            self.assertTrue((backups[0]/"node-vpn/settings.json").exists())
            self.assertTrue((backups[0]/"node-config/config.json").exists())
            self.assertTrue((backups[0]/"wpp-node-agent.service").exists())

    def test_enrolled_node_is_never_reinstalled_even_when_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"etc/wpp-node-agent/registered.json").write_text(
                json.dumps({"domain":"old.example.net","registered":True})
            )
            for mode in ("check","cleanup"):
                result=self.run_preflight(code,env,mode)
                self.assertEqual(result.returncode,20,result.stderr)
                self.assertIn("Нода уже установлена",result.stdout)
                self.assertTrue(cfg.exists())
            self.assertFalse((root/"backups").exists())

    def test_active_services_after_failed_install_do_not_mean_registered(self):
        # This reproduces the VPS report: all services were active but the
        # installer failed at 45%, before controller enrollment and receipt.
        live=("wpp-node-agent.service","wpo-node-vpn.service","wpo-node-relay.service")
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp,live)
            cfg.write_text(json.dumps({"domain":"old.example.net","version":"0.4.0"}))
            (root/"etc/wpp-node-vpn").mkdir(parents=True)
            (root/"etc/wpp-node-vpn/settings.json").write_text(
                json.dumps({"domain":"old.example.net"})
            )
            (root/"etc/wpp-node-vpn/profiles.json").write_text('{"profiles":{}}')
            for name in live:
                (root/"etc/systemd/system"/name).write_text("Service=1")
            check=self.run_preflight(code,env,"check")
            self.assertEqual(check.returncode,0,check.stderr)
            self.assertIn("незавершена",check.stdout)
            self.assertNotIn("Нода уже установлена",check.stdout)
            clean=self.run_preflight(code,env,"cleanup")
            self.assertEqual(clean.returncode,0,clean.stderr)
            self.assertFalse(cfg.exists())
            self.assertFalse((root/"opt/wpp-node-agent/agent.py").exists())
            self.assertTrue(list((root/"backups").glob("wpo-node-incomplete-*")))
            for name in live:
                self.assertTrue((root/"bin"/("stopped-"+name)).exists(),name)

    def test_version_040_and_existing_units_before_enroll_are_incomplete(self):
        # Version 0.4.0 is set BEFORE the enroll request. It is not proof
        # that the node ever reached 100% of the installation.
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            cfg.write_text(json.dumps({"domain":"old.example.net","version":"0.4.0"}))
            (root/"etc/wpp-node-vpn").mkdir(parents=True)
            (root/"etc/wpp-node-vpn/settings.json").write_text(
                json.dumps({"domain":"old.example.net"})
            )
            for name in ("wpo-node-vpn.service","wpo-node-relay.service"):
                (root/"etc/systemd/system"/name).write_text("Service=1")
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(cfg.exists())
            self.assertTrue(list((root/"backups").glob("wpo-node-incomplete-*")))

    def test_successful_legacy_enrollment_log_prevents_reinstall(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"logs").mkdir()
            log=root/"logs/node-install-20261115T120000Z-1234.log"
            log.write_text(
                "Registration complete\n"
                "Готово: Node Agent зарегистрирован на https://old.example.net\n"
            )
            log.chmod(0o600)
            for mode in ("check","cleanup"):
                result=self.run_preflight(code,env,mode)
                self.assertEqual(result.returncode,20,result.stderr)
                self.assertIn("Нода уже установлена",result.stdout)
                self.assertTrue(cfg.exists())
            self.assertFalse((root/"backups").exists())

    def test_stale_success_log_does_not_hide_new_failed_install(self):
        # The server was previously enrolled, then a later attempt rewrote
        # config.json and failed at 45%. Historical success is NOT evidence
        # that the current node configuration was registered.
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"logs").mkdir()
            log=root/"logs/node-install-20261115T120000Z-1234.log"
            log.write_text("Готово: Node Agent зарегистрирован на https://old.example.net\\n")
            log.chmod(0o600)
            os.utime(log,(100,100))
            os.utime(cfg,(200,200))
            check=self.run_preflight(code,env,"check")
            self.assertEqual(check.returncode,0,check.stderr)
            self.assertIn("незавершена",check.stdout)
            cleanup=self.run_preflight(code,env,"cleanup")
            self.assertEqual(cleanup.returncode,0,cleanup.stderr)
            self.assertFalse(cfg.exists())

    def test_failed_legacy_enrollment_log_not_considered_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"logs").mkdir()
            log=root/"logs/node-install-20261115T120001Z-1234.log"
            log.write_text(
                "WEB Proxy relay did not become HTTP-ready\n"
                "Установка ноды прервана (код 4)\n"
            )
            log.chmod(0o600)
            result=self.run_preflight(code,env,"check")
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn("Нода уже установлена",result.stdout)

    def test_failed_post_check_temporary_identity_can_be_cleaned(self):
        # Actual 72% VPS failure: sync created this temporary two-protocol
        # identity; delete() crashed in _connection_map before committing.
        leftover={
            "a"*64: {
                "name":"WPO install check",
                "secrets":{
                    "vless":"cc98a634-bf01-42f0-8c9c-1fd3d5338e55",
                    "hysteria":"81899b7c-3a8d-4ea5-bbe0-22c45c03e2a4",
                },
                "native":{},
            }
        }
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            vpn=root/"etc/wpp-node-vpn"
            vpn.mkdir(parents=True)
            registry=vpn/"profiles.json"
            registry.write_text(json.dumps({"profiles":leftover}))
            check=self.run_preflight(code,env,"check")
            self.assertEqual(check.returncode,0,check.stderr)
            self.assertIn("служебные профили",check.stdout)
            cleanup=self.run_preflight(code,env,"cleanup")
            self.assertEqual(cleanup.returncode,0,cleanup.stderr)
            self.assertFalse(registry.exists())
            self.assertFalse(cfg.exists())
            backup=list((root/"backups").glob("wpo-node-incomplete-*"))
            self.assertEqual(len(backup),1)
            saved=json.loads((backup[0]/"node-vpn/profiles.json").read_text())
            self.assertEqual(saved["profiles"],leftover)

    def test_fake_install_profile_with_real_client_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            vpn=root/"etc/wpp-node-vpn"
            vpn.mkdir(parents=True)
            registry=vpn/"profiles.json"
            registry.write_text(json.dumps({"profiles":{
                "a"*64:{"name":"WPO install check",
                        "secrets":{"vless":"invalid"},
                        "native":{}},
                "b"*64:{"name":"real subscriber","secrets":{},"native":{}},
            }}))
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,30,result.stderr)
            self.assertIn("пользовательские VPN",result.stderr)
            self.assertTrue(cfg.exists())
            self.assertTrue(registry.exists())
            self.assertFalse((root/"backups").exists())

    def test_nonempty_vpn_profiles_block_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"etc/wpp-node-vpn").mkdir(parents=True)
            (root/"etc/wpp-node-vpn/profiles.json").write_text(
                json.dumps({"profiles":{"one":{"name":"User"}}})
            )
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,30,result.stderr)
            self.assertIn("пользовательские VPN",result.stderr)
            self.assertTrue(cfg.exists())

    def test_failed_install_with_active_services_and_real_profiles_is_preserved(self):
        # A genuinely used legacy node without a receipt must not lose data.
        active=("wpp-node-agent.service","wpo-node-vpn.service","wpo-node-relay.service")
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp,active)
            (root/"etc/wpp-node-vpn").mkdir(parents=True)
            (root/"etc/wpp-node-vpn/profiles.json").write_text(
                json.dumps({"profiles":{"existing-client":{"name":"User"}}})
            )
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,30,result.stderr)
            self.assertTrue(cfg.exists())
            self.assertFalse((root/"backups").exists())
            self.assertFalse(list((root/"bin").glob("stopped-*")))

    def test_real_web_proxy_profiles_block_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"etc/tproxy-server").mkdir(parents=True)
            (root/"etc/tproxy-server/profiles.json").write_text(json.dumps(
                {"profiles":[{"name":"node-bootstrap"},{"name":"customer-1"}]}
            ))
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,30,result.stderr)
            self.assertTrue(cfg.exists())

    def test_corrupt_profile_registry_blocks_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"etc/wpp-node-vpn").mkdir(parents=True)
            (root/"etc/wpp-node-vpn/profiles.json").write_text("{bad")
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,30,result.stderr)
            self.assertTrue(cfg.exists())

    def test_broken_receipt_blocks_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            (root/"etc/wpp-node-agent/registered.json").write_text("{bad")
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,30,result.stderr)
            self.assertTrue(cfg.exists())

    def test_no_node_does_not_touch_host(self):
        with tempfile.TemporaryDirectory() as temp:
            root,cfg,code,env=self.sandbox(temp)
            cfg.unlink()
            (root/"opt/wpp-node-agent/agent.py").unlink()
            (root/"opt/wpp-node-agent").rmdir()
            result=self.run_preflight(code,env,"cleanup")
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((root/"backups").exists())


if __name__=="__main__":
    unittest.main()
