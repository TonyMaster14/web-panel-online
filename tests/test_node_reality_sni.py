"""Regression: Nodes Lab REALITY SNI is bound to live local Xray, remote is planned."""
import ast
import html
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]


def synthetic_ui(node_install_source):
    marker='new_nodes=r"""def nodes_ui(nodes, local, connection_token, path, csrf, pending_nodes=None, presets=None):'
    assert node_install_source.count(marker)==1
    part='def nodes_ui(nodes, local, connection_token, path, csrf, pending_nodes=None, presets=None):'+node_install_source.split(marker,1)[1].split('"""',1)[0]
    # Mimic the changes to these exact fragments made by Nodes Lab v18 and
    # v25; keep the v2 function otherwise intact for focused patch testing.
    start,end=part.index('    cards.append(f'),part.index('    for n in nodes:',part.index('    cards.append(f'))
    head=part[start:end]
    assert head.count('</a></div>')==1
    head=head.replace('</a></div>',
        '</a><div class="wpo-node-meta-row"><p class="wpo-node-template wpo-main-node-label">Основная нода</p></div></div>')
    part=part[:start]+head+part[end:]
    before='<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p>'
    after='<p class="wpo-node-template" title="Шаблон: {esc(site_name)}">{icon("settings")} Шаблон: {esc(site_name)}</p>'
    assert part.count(before)==1
    part=part.replace(before,after)
    return ('import json\nimport html\nimport wpp_routing as routing_store\n'
            'CSS=""\n'
            'def esc(v): return html.escape(str(v),quote=True)\n'
            'def icon(name): return ""\n'
            'def node_flag(code): return "NODE"\n'
            +part+'\n\nCSS += """stub"""\n')


def synthetic_panel():
    return """import wpp_reality as reality
def render():
    body=nodes_ui([],{},DOMAIN,PANEL_PATH,csrf,pending_rows,all_presets())
def handler(form):
                operation=form.get("operation")
                if operation=="noop":
                    pass
                elif operation=="edit":
                    with wpo_node_auto.registry_lock:
                        nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")
                        selected=next((n for n in nodes if n.get("id")==uid),None)
                        new_name=node_api.clean_text(form.get("name",""),"Название ноды",80)
                        template_id=str(form.get("site_template","")).strip()
                        selected["name"]=new_name
                        node_api.save_nodes(NODES_FILE,nodes)
                elif operation=="rename":
                    pass
"""


class NodeSniPatchTests(unittest.TestCase):
    def test_embedded_node_sni_postpatch_changes_ui_and_node_registry(self):
        install=(PROJECT/"node-install.sh").read_text(encoding="utf-8")
        marker='python3 - "$UI" "$PANEL" <<\'PY_NODE_REALITY_SNI\'\n'
        self.assertEqual(install.count(marker),1)
        source=install.split(marker,1)[1].split("\nPY_NODE_REALITY_SNI\n",1)[0]
        ast.parse(source)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            ui=root/"wpp_ui.py"
            panel=root/"panel.py"
            ui.write_text(synthetic_ui(install),encoding="utf-8")
            panel.write_text(synthetic_panel(),encoding="utf-8")
            result=subprocess.run([sys.executable,"-c",
                "import sys;sys.argv=['node-sni-patch.py',sys.argv[1],sys.argv[2]]\n"
                +source,str(ui),str(panel)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,
                result.stdout+"\n"+result.stderr)
            patched_ui=ui.read_text(encoding="utf-8")
            patched_panel=panel.read_text(encoding="utf-8")
            compile(patched_ui,str(ui),"exec")
            compile(patched_panel,str(panel),"exec")
            self.assertIn('selected["reality_sni"]=requested_sni',patched_panel)
            self.assertIn("reality_connection=connection_store.get(",patched_panel)
            self.assertIn("reality.DEFAULT_SNI",patched_panel)
            scope={"__name__":"node_sni_fixture"}
            exec(compile(patched_ui,str(ui),"exec"),scope)
            item={"id":"node-test","name":"Test node","country_name":"Czechia",
                  "url":"https://node.example.net","enabled":True}
            real={"id":"vless-reality-primary","name":"VLESS REALITY · TCP Vision",
                  "config":{"route":"reality","port":443,"sni":"www.microsoft.com",
                            "fingerprint":"chrome","address":""}}
            page=scope["nodes_ui"]([item],{"country_name":"Finland"},
                "panel.example.net","/panel-test","csrf",
                [],[],reality_connection=real)
            # Node cards stay clean: SNI lives in pencil dialogs, not
            # visible card text. The local pencil keeps the entrypoint.
            cards=page.split("</section>",1)[0]
            self.assertNotIn("REALITY SNI:",cards)
            self.assertNotIn("запланирован",cards)
            self.assertIn("Основная нода</p>",cards)
            self.assertIn("data-wpo-local-sni",cards)
            self.assertIn("www.microsoft.com",page)
            self.assertIn("data-wpo-local-sni",page)
            self.assertIn("data-node-sni=",page)
            self.assertIn('name="reality_sni"',page)
            self.assertIn("Node Agent 0.2",page)
            self.assertIn("Microsoft",page)
            self.assertIn("Amazon",page)
            self.assertIn("/connection-action",page)
            self.assertIn("/node-action",page)

    def test_registered_node_gets_persistent_microsoft_sni(self):
        import wpp_nodes as nodes
        with tempfile.TemporaryDirectory() as directory:
            registry=str(Path(directory)/"nodes.json")
            agent_reply={"domain":"node.example.net","location":{"country_code":"CZ"},
                         "version":"0.2","capabilities":["site-template"]}
            with patch.object(nodes,"request",return_value=agent_reply):
                created=nodes.add_node(registry,{"url":"https://node.example.net",
                                                 "token":"x"*43})
            self.assertEqual(created["reality_sni"],"www.microsoft.com")
            self.assertEqual(nodes.load_nodes(registry)[0]["reality_sni"],
                             "www.microsoft.com")

    def test_sni_defaults_are_shared(self):
        import wpp_reality as reality
        import wpp_connections as connections
        self.assertEqual(reality.DEFAULT_SNI,"www.microsoft.com")
        self.assertEqual(connections.defaults()[-1]["config"]["sni"],reality.DEFAULT_SNI)
        self.assertEqual(connections.defaults()[-1]["config"]["port"],443)
        names=[value for value,_ in reality.SNI_CANDIDATES]
        self.assertNotIn("www.cloudflare.com",names)
        self.assertNotIn("www.mozilla.org",names)


if __name__=="__main__":
    unittest.main()
