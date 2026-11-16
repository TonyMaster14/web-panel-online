"""Fleet REALITY UI and end-to-end verification regressions."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import wpo_reality
import wpo_reality_probe as probe
import wpo_reality_ui as ui

ROOT=Path(__file__).resolve().parents[1]
PROFILE=dict(wpo_reality.DEFAULT,address="203.0.113.2",public_key="a"*43,
             short_id="0123456789abcdef")

class FleetUI(unittest.TestCase):
    def render(self, fleet=True):
        with patch.object(ui.reality,"read_profile",return_value=PROFILE):
            return ui.editor("/panel","csrf",[
                {"id":"node001","name":"Нидерланды 2"},
                {"id":"node002","name":"Швеция"}],fleet=fleet)

    def test_fleet_scope_lists_all_nodes_and_has_accurate_labels(self):
        html=self.render()
        self.assertIn("Вся сеть · основная и 2 дополнительных нод",html)
        self.assertIn('name="node_id" value="local"',html)
        self.assertIn('"node001"',html)
        self.assertIn('"node002"',html)
        self.assertIn("REALITY Vision",html)
        self.assertIn("HTTP 204",html)
        self.assertIn("TLS 1.3",html)
        self.assertIn('data-reality-check>Проверить цель',html)
        self.assertIn('type="submit" class="primary">Сохранить</button>',html)
        self.assertNotIn("Проверить и сохранить",html)
        self.assertIn("Сохранение прервано",html)
        self.assertIn("const actual=await send(n.id,{read_only:'1'})",html)
        self.assertIn("const oldPreset=(presets[old.preset]",html)
        self.assertIn("Сохранение отменено",html)

    def test_dedicated_node_pencil_is_not_global(self):
        html=self.render(fleet=False)
        self.assertIn('<select name="node_id">',html)
        self.assertIn('fleet=false',html)
        self.assertIn("data-reality-open",html)

    def test_aligned_custom_dropdown_with_accessibility(self):
        html=self.render()
        self.assertIn('class="wpo-reality-picker-menu"',html)
        self.assertIn('role="listbox"',html)
        self.assertIn('role="option"',html)
        self.assertIn('aria-expanded="false"',html)
        self.assertIn('aria-selected="true"',html)
        self.assertNotIn('<select name="preset">',html)
        self.assertIn("position:absolute;top:calc(100% + 5px);left:0;right:0",html)

    def test_no_unsafe_html_injection_from_node_labels(self):
        with patch.object(ui.reality,"read_profile",return_value=PROFILE):
            html=ui.editor("/panel","csrf",[{"id":"n1","name":"<script>alert(1)</script>"}],fleet=True)
        self.assertNotIn('"name": "<script>',html)
        self.assertIn("\\u003cscript",html)

    @unittest.skipUnless(shutil.which("node"),"Node.js not installed")
    def test_script_parses_as_javascript(self):
        for fleet in (True,False):
            html=self.render(fleet)
            script=re.search(r"<script>(.*?)</script>",html,re.S)
            self.assertIsNotNone(script)
            outcome=subprocess.run(["node","--check"],input=script.group(1),
                                   capture_output=True,text=True,timeout=6)
            self.assertEqual(outcome.returncode,0,outcome.stderr)

    def test_connections_settings_populates_real_federated_nodes(self):
        source=(ROOT/"src/wpo_reality_ui.py").read_text()
        self.assertIn("wpp_nodes.load_nodes('/var/lib/tproxy-panel/nodes.json')",source)
        self.assertIn("editor(path,csrf,public_nodes,fleet=True)",source)
        self.assertIn("await send(n.id,{...request,check_only:'1'},{signal:activeAbort.signal})",source)
        self.assertIn("await send(n.id,{...request,check_only:'0'})",source)
        self.assertIn("for(const n of attempted.reverse())",source)
        self.assertIn("Нода не подтвердила настоящий REALITY-туннель",source)
        self.assertIn("const reuse=save&&verified?.key===key",source)
        self.assertIn("function requestStop()",source)
        self.assertIn("d.querySelector('[data-reality-close]').disabled=false",source)
        self.assertIn("if(closeAfterStop&&!restoreFailed)d.close()",source)
        self.assertIn("height:min(700px,calc(100dvh - 30px))",source)
        self.assertIn("overflow-y:auto;overscroll-behavior:contain",source)
        self.assertNotIn("outline:2px solid var(--accent)",source)

class RealTunnelVerification(unittest.TestCase):
    def test_server_requires_actual_tunnel_not_only_tls(self):
        with patch.object(wpo_reality,"check_target",return_value=True), \
             patch.object(probe,"probe",return_value={
                  "ok":True,"checks":[{"name":"REALITY Vision","status":"ok"},
                    {"name":"HTTPS через туннель","status":"ok"}],"latency_ms":108}) as verify:
            result=wpo_reality.configure({"preset":"nvidia","sni":"www.nvidia.com",
                                          "fingerprint":"firefox","check_only":True},lambda:None)
        self.assertTrue(result["ok"])
        self.assertEqual(result["latency_ms"],108)
        verify.assert_called_once()
        self.assertTrue(result["checks"])
    def test_failed_real_tunnel_rejects_even_with_valid_tls(self):
        with patch.object(wpo_reality,"check_target",return_value=True), \
             patch.object(probe,"probe",side_effect=probe.ProbeError("TLS есть, REALITY нет")):
            with self.assertRaisesRegex(ValueError,"REALITY нет"):
                wpo_reality.configure({"preset":"nvidia","sni":"www.nvidia.com",
                                       "fingerprint":"firefox","check_only":True},lambda:None)

    def test_probe_only_runs_ephemeral_xray_and_http_204(self):
        local_port=iter([47001,47002])
        procs=[]
        class FakeProcess:
            def poll(self):return None
            def terminate(self):pass
            def wait(self,timeout=None):return 0
        def fake_popen(args,**kwargs):
            self.assertEqual(args[0],probe.XRAY)
            self.assertIn("run",args)
            procs.append(args)
            return FakeProcess()
        expected=SimpleNamespace(returncode=0,stdout="204 0.193",stderr="")
        fake=SimpleNamespace(read_profile=lambda:PROFILE,
          PRIVATE=Path("/fake/private"),
          inbound=lambda clients,p:{
            "settings":{"clients":clients},
            "streamSettings":{"realitySettings":{"privateKey":"redacted"}}})
        with patch.object(probe,"local_port",side_effect=lambda:next(local_port)), \
             patch.object(probe,"subprocess") as sub, \
             patch.object(probe,"grp") as g, \
             patch.object(probe,"time") as timer:
            g.getgrnam.side_effect=KeyError("xray")
            sub.Popen.side_effect=fake_popen
            sub.run.return_value=expected
            timer.sleep.return_value=None
            with patch.object(Path,"is_file",return_value=True):
                result=probe.probe("www.nvidia.com","firefox",fake)
            self.assertEqual(sub.Popen.call_count,2)
            self.assertIn("--socks5-hostname",sub.run.call_args.args[0])
            self.assertEqual(result["latency_ms"],193)
            self.assertEqual(result["checks"][-1]["name"],"HTTPS через туннель")

    def test_live_node_updater_pins_same_verified_source(self):
        shell=(ROOT/"nodes/wpo-reality-probe-update.sh").read_text()
        subprocess.run(["bash","-n"],input=shell,text=True,check=True,timeout=4)
        self.assertIn("wpo_reality_probe.py",shell)
        self.assertIn("wpo-node-vpn.service",shell)
        self.assertIn("BACKUP",shell)
        self.assertNotIn("rm -rf /etc/wpp-node-vpn",shell)

if __name__=="__main__":
    unittest.main()
