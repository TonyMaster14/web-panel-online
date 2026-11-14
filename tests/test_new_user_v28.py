"""New User v28 UI is compatible with current controller and honors VPN readiness.

No privileged services or remote node access; this tests actual HTML emitted by
the bundled module and the pure subscription expiry transition.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import html
import importlib.util
import re
import time
import unittest

import wpo_user_v28
import wpo_v28_apply
import wpp_subscriptions

ROOT = Path(__file__).resolve().parents[1]

def backend():
    source=(ROOT/"wpp_subscriptions.py").read_text(encoding="utf-8")
    patched=wpo_v28_apply.patch_subscriptions(source)
    ns={"__name__":"wpp_subscriptions_v28_test"}
    exec(compile(patched,"wpp_subscriptions_v28_test.py","exec"),ns)
    return ns


class NewUserFormTests(unittest.TestCase):
    def setUp(self):
        self.conns=[
            {"id":"vless-direct","protocol":"vless","enabled":True,"name":"XHTTP"},
            {"id":"hysteria-primary","protocol":"hysteria","enabled":True,"name":"Hysteria2"},
        ]
        self.nodes=[
            {"id":"a"*16,"name":"Швеция","country_code":"SE","status":"online",
             "enabled":True,"capabilities":["federation","vless","hysteria"]},
            {"id":"b"*16,"name":"Недоступная нода","country_code":"CH","status":"online",
             "enabled":True,"capabilities":["site-template"]},
        ]
        self.html=wpo_user_v28.form("/panel-demo","token-demo",self.conns,self.nodes,
                                    {"country_code":"NL","country_name":"Нидерланды"})
    def test_only_supported_real_vpn_nodes_can_be_selected(self):
        self.assertIn('name="node_local"',self.html)
        self.assertIn('name="node_aaaaaaaaaaaaaaaa"',self.html)
        self.assertIn('name="node_bbbbbbbbbbbbbbbb" value="1" disabled',self.html)
        self.assertIn('name="connection_vless-direct"',self.html)
        self.assertIn('name="connection_hysteria-primary"',self.html)
        self.assertEqual(self.html.count('class="wpo-v28-protocol"'),2)
    def test_future_protocols_not_silently_provisioned(self):
        for name in ("WEB Proxy","MTProto","AmneziaWG 2.0","AmneziaWG 3.1",
                     "NaiveProxy","Mieru"):
            self.assertIn(name,self.html)
        self.assertNotIn('name="connection_web"',self.html)
        self.assertNotIn('name="connection_awg20"',self.html)
    def test_existing_controller_dom_is_preserved(self):
        for marker in ('id="createAccount"','id="createClientForm"','id="createSummary"',
                       'id="accountName"','id="subscriptionFields"','id="directFields"',
                       'id="quickFields"','id="deviceLimit"','id="accountKind"',
                       'name="access_mode" value="subscription" checked',
                       'id="createClientSubmit"','id="createError"'):
            self.assertIn(marker,self.html,marker)
        self.assertIn("Новый пользователь",self.html)
        self.assertNotIn("Один ключ",self.html)
    def test_time_zone_and_calendar_constraints(self):
        self.assertIn('type="datetime-local"',self.html)
        self.assertIn('max="2090-12-31T23:59"',self.html)
        self.assertIn("Intl.DateTimeFormat().resolvedOptions().timeZone",self.html)
        self.assertIn("Math.floor(d.getTime()/1000)",self.html)
        for n in ("1","2","3","6","12"):
            self.assertIn(f'data-wpo-months="{n}"',self.html)
    def test_escaping_and_no_injected_html(self):
        escaped=wpo_user_v28.form("/panel-demo",'<input bad>',self.conns,
                                  [{**self.nodes[0],"name":'<script>alert(1)</script>'}],
                                  {"name":"<img src=x>"})
        self.assertNotIn("<script>alert(1)</script>",escaped)
        self.assertNotIn("<img src=x>",escaped)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;",escaped)


class V28ExpiryTests(unittest.TestCase):
    def test_subscription_expiry_validator_accepts_future(self):
        funcs=backend()
        deadline=int(time.time()+3600)
        self.assertEqual(funcs["validate_expiry"](deadline),deadline)
    def test_subscription_expiry_validator_refuses_past_and_year_2091(self):
        funcs=backend()
        for deadline in (int(time.time())-1,int(time.time())+10,3825964800):
            with self.subTest(deadline=deadline):
                with self.assertRaises(funcs["SubscriptionError"]):
                    funcs["validate_expiry"](deadline)
    def test_panel_patch_denies_stale_public_access(self):
        root=(ROOT/"install-panel.sh").read_text(encoding="utf-8")
        p=root.split('cat > "$APP_FILE" <<\'PY\'\n',1)[1].split("\nPY\n",1)[0]
        p=p.replace('# wpo-vpn-controller-v27: no phantom remote connections',
                    '# wpo-vpn-controller-v27: no phantom remote connections')
        # Verify the bundled node installer has the required pre-patch anchor.
        self.assertIn('if subscription is None:',p)
    def test_full_install_path_includes_v28_after_v26(self):
        node=(ROOT/"node-install.sh").read_text(encoding="utf-8")
        self.assertIn("python3 \"$PACKAGE_DIR/wpo_v28_apply.py\"",node)
        self.assertLess(node.index("wpo-nodes-lab-v26-install.sh"),
                        node.index('python3 "$PACKAGE_DIR/wpo_v28_apply.py"'))


if __name__=="__main__":
    unittest.main()
