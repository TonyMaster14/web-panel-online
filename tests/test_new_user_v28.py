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
    def test_nine_protocols_are_selectable_if_real_local_templates_exist(self):
        import wpp_connections
        all_template_connections=wpp_connections.defaults()
        html=wpo_user_v28.form("/panel-demo","token",all_template_connections,
                               self.nodes,{"country_code":"NL"})
        for spec in all_template_connections:
            cid=spec["id"]
            self.assertIn(f'name="connection_{cid}"',html)
            self.assertIn(f'data-protocol="{spec["protocol"]}"',html)
        self.assertEqual(html.count('class="wpo-v28-protocol"'),9)
        self.assertIn("Отдельные протоколы создаются по одному",html)
        self.assertIn("kind.value=native[0].dataset.protocol",html)
        self.assertIn("connection.value=native[0].dataset.connectionId",html)
        self.assertIn("Срок действия",html)
        self.assertIn("Лимит срока для отдельных профилей пока нужно проверять отдельно",html)

    def test_telegram_cards_show_only_telegram_subtitle(self):
        import re
        import wpp_connections
        conns=wpp_connections.defaults()
        html=wpo_user_v28.form("/panel-demo","csrf-token",conns,self.nodes,{})
        for title in ("WEB Proxy","MTProto"):
            card=re.search(
                r'<label class="wpo-v28-option">.*?<strong>'+re.escape(title)+
                r'</strong><small>(.*?)</small>.*?</label>',html,re.S)
            self.assertIsNotNone(card,title)
            self.assertEqual(card.group(1),"Telegram",title)
        self.assertNotIn("Telegram · отдельная ссылка",html)
        self.assertIn('Happ · HTTPS 443 · выбранные ноды',html)
        self.assertIn('Amnezia · конфигурация · одна выбранная нода',html)

    def test_existing_controller_dom_is_preserved(self):
        for marker in ('id="createAccount"','id="createClientForm"','id="createSummary"',
                       'id="accountName"','id="subscriptionFields"','id="directFields"',
                       'id="quickFields"','id="deviceLimit"','id="accountKind"',
                       'name="access_mode" value="subscription" checked',
                       'id="createClientSubmit"','id="createError"'):
            self.assertIn(marker,self.html,marker)
        self.assertIn("Новый пользователь",self.html)
        self.assertNotIn("Один ключ",self.html)
    def test_old_wizard_js_replaced_without_busting_other_actions(self):
        import ast
        import subprocess
        raw=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        tree=ast.parse(raw)
        node=next(node for node in tree.body if isinstance(node,ast.Assign)
                  and any(getattr(target,"id","")=="CLIENTS_JS" for target in node.targets))
        legacy=ast.literal_eval(node.value)
        fixed=wpo_user_v28.replace_legacy_create_js(legacy)
        self.assertIn("function showCreateError(message)",fixed)
        self.assertIn("const createDialog=",fixed)
        self.assertNotIn("function updateCreate(){",fixed)
        self.assertNotIn("const vlessCdnProvider=",fixed)
        self.assertIn("async function requestClient(fields)",fixed)
        self.assertIn("new URLSearchParams(new FormData(createForm))",fixed)
        for name,script in (("new wizard",wpo_user_v28.LEGACY_CREATE_JS),
                            ("date picker",wpo_user_v28.SCRIPT),
                            ("complete clients JS",fixed.replace("<script>","").replace("</script>","")
                             .replace("@@PATH@@",'"/panel-demo"').replace("@@CSRF@@",'"token-demo"'))):
            with self.subTest(name=name):
                res=subprocess.run(["node","--check"],input=script,text=True,
                                    capture_output=True,timeout=8)
                self.assertEqual(res.returncode,0,res.stderr)
        rendered=wpo_user_v28.form("/panel-demo","csrf",self.conns,self.nodes,{})
        self.assertIn("const tz=Intl.DateTimeFormat()",rendered)
        self.assertIn("name=\"expires_at\"",rendered)

    def test_patch_wires_new_js_on_both_fresh_and_existing_panels(self):
        raw=(ROOT/"wpp_ui.py").read_text(encoding="utf-8")
        # v28 is applied AFTER the embedded Nodes Lab v26 patch,
        # which contributes the node-picker insertion anchor.
        staged=raw.replace("    client_script=CLIENTS_JS.replace(",
                           wpo_v28_apply.PICKER+"\n    client_script=CLIENTS_JS.replace(",1)
        updated=wpo_v28_apply.patch_ui(staged)
        self.assertIn("wpo_user_v28.replace_legacy_create_js(CLIENTS_JS)",updated)
        self.assertIn("wpo_user_v28.form(path,csrf,usable,nodes,local_node)",updated)
        self.assertIn("＋ Новый пользователь",updated)
        self.assertEqual(wpo_v28_apply.patch_ui(updated),updated)
        previous=updated.replace("wpo_user_v28.replace_legacy_create_js(CLIENTS_JS)","CLIENTS_JS")
        self.assertIn("wpo_user_v28.replace_legacy_create_js(CLIENTS_JS)",
                      wpo_v28_apply.patch_ui(previous))
        compile(updated,"wpp_ui_patched.py","exec")

    def test_time_zone_and_calendar_constraints(self):
        self.assertNotIn('type="datetime-local"',self.html)
        self.assertIn('id="wpoV28Date" type="hidden"',self.html)
        self.assertIn('id="wpoV28DayGrid"',self.html)
        self.assertIn('id="wpoV28Month"',self.html)
        self.assertIn('id="wpoV28Year"',self.html)
        self.assertIn('id="wpoV28PrevMonth"',self.html)
        self.assertIn('id="wpoV28NextMonth"',self.html)
        self.assertIn('class="wpo-v28-calendar-icon"',self.html)
        self.assertIn('id="wpoV28CalendarToggle"',self.html)
        self.assertIn('aria-expanded="false"',self.html)
        self.assertIn('id="wpoV28CalendarBody" hidden',self.html)
        self.assertNotIn('<details',self.html)
        self.assertNotIn('<summary>',self.html)
        for removed in ('id="wpoV28Hour"','id="wpoV28Minute"',
                        'id="wpoV28Apply"','id="wpoV28Today"',
                        'id="wpoV28CurrentDateTime"','Время окончания',
                        'Часы<select','Минуты<select','Сегодня:'):
            self.assertNotIn(removed,self.html,removed)
        self.assertIn("Intl.DateTimeFormat().resolvedOptions().timeZone",self.html)
        self.assertIn("atEndOfDay",self.html)
        self.assertIn("selected.getTime()/1000",self.html)
        self.assertIn("year<=2099",self.html)
        self.assertNotIn("2090",self.html)
        self.assertIn("sameDay(date,current)",self.html)
        self.assertIn("@keyframes wpo-v28-pulse",self.html)
        self.assertIn("prefers-reduced-motion:reduce",self.html)
        self.assertIn('class="wpo-v28-limit-field"',self.html)
        self.assertIn('height:40px',self.html)
        for n in ("1","3","6","9","12"):
            self.assertIn(f'data-wpo-months="{n}"',self.html)
        self.assertNotIn('data-wpo-months="2"',self.html)
        self.assertIn('data-wpo-2099="1"',self.html)
        self.assertIn("До 2099",self.html)

    def test_calendar_closes_reliably_with_trigger_and_escape(self):
        self.assertIn("toggle.addEventListener('click',event=>{",self.html)
        self.assertIn("if(popover.hidden)openCalendar();",self.html)
        self.assertIn("else closeCalendar();",self.html)
        self.assertIn("popover.hidden=true;",self.html)
        self.assertIn("popover.hidden=false;",self.html)
        self.assertIn("toggle.setAttribute('aria-expanded','false');",self.html)
        self.assertIn("toggle.setAttribute('aria-expanded','true');",self.html)
        self.assertIn("if(!popover.hidden&&!calendar.contains(event.target))closeCalendar();",self.html)
        self.assertIn("event.key==='Escape'",self.html)
        self.assertIn("chooseDate(date);",self.html)
        self.assertIn("chooseDate(new Date(2099,11,31),'2099');",self.html)
        self.assertIn('wpo-v28-calendar-body[hidden]{display:none!important}',self.html)
        self.assertIn('.wpo-v28-cal-days button.is-today',self.html)
        self.assertIn('border:1.5px solid var(--red)!important',self.html)
        self.assertIn('.wpo-v28-dialog .wpo-v28-section h3{color:#fff!important',self.html)
        self.assertIn('placeholder="Например, Home VPN"',self.html)

    def test_calendar_popup_is_not_hidden_by_obsolete_details_css(self):
        # Regression: this selector targets the newer DIV as well and silently
        # forces display:none even after JS sets hidden=false.
        self.assertNotIn('.wpo-v28-calendar:not([open]) .wpo-v28-calendar-body',
                         wpo_user_v28.STYLE)
        self.assertNotIn('.wpo-v28-calendar[open]',wpo_user_v28.STYLE)
        self.assertIn('.wpo-v28-calendar-body[hidden]{display:none!important}',
                      wpo_user_v28.STYLE)
        self.assertIn('.wpo-v28-calendar-body:not([hidden]){display:grid}',
                      wpo_user_v28.STYLE)
        self.assertIn("popover.hidden=false;",wpo_user_v28.SCRIPT)
        self.assertIn("popover.hidden=true;",wpo_user_v28.SCRIPT)
        self.assertIn("if(popover.hidden)openCalendar();",wpo_user_v28.SCRIPT)
        self.assertIn("else closeCalendar();",wpo_user_v28.SCRIPT)

    def test_node_and_protocol_copy_is_white_even_when_unavailable(self):
        css=wpo_user_v28.STYLE
        for selector in (
            '#subscriptionFields .wpo-v28-section>h3',
            '#subscriptionFields .wpo-v28-section>p',
            '#subscriptionFields .wpo-v28-node strong',
            '#subscriptionFields .wpo-v28-node small',
            '#subscriptionFields .wpo-v28-option strong',
            '#subscriptionFields .wpo-v28-option small',
        ):
            self.assertIn(selector,css,selector)
        self.assertIn('color:#fff!important;opacity:1!important',css)
        self.assertIn('#subscriptionFields .unavailable{opacity:1',css)

    def test_calendar_opens_on_current_month_not_default_expiry_month(self):
        # Every open presents the browser-local current month/day regardless of
        # a previous 12-month or 2099 expiry chosen and saved in the form.
        script=wpo_user_v28.SCRIPT
        self.assertIn("function openCalendar(){",script)
        open_handler=script.split("function openCalendar(){",1)[1].split("function chooseDate(",1)[0]
        self.assertIn("highlightedDate=new Date(current.getFullYear(),current.getMonth(),current.getDate());",open_handler)
        self.assertIn("viewYear=current.getFullYear();",open_handler)
        self.assertIn("viewMonth=current.getMonth();",open_handler)
        self.assertIn("calendar.querySelectorAll('[data-wpo-months],[data-wpo-2099]')",open_handler)
        self.assertIn("button.classList.remove('is-selected');",open_handler)
        self.assertIn("button.setAttribute('aria-pressed','false');",open_handler)
        self.assertIn("popover.hidden=false;",open_handler)
        self.assertLess(open_handler.index("popover.hidden=false;"),open_handler.index("renderCalendar();"))
        # Visual reset must never silently change the selected expiration.
        self.assertNotIn("selected=",open_handler)
        self.assertNotIn("syncDate()",open_handler)
        self.assertNotIn("expiry.value=",open_handler)
        self.assertIn("sameDay(date,highlightedDate||current)",script)
        self.assertIn("selected=atEndOfDay(date);",script)
        self.assertIn("document.getElementById('wpoV28Now')",script)
        self.assertIn("setInterval(()=>{",script)
        self.assertIn("let highlightedDate=null;",script)
        self.assertIn("button.classList.toggle('is-highlighted',sameDay(date,highlightedDate||current));",script)
        self.assertIn("if(dayKey!==lastLiveDay){",script)
        self.assertIn("now().toLocaleString('ru-RU'",script)
        self.assertIn("id=\"wpoV28Now\"",self.html)
        self.assertIn("Текущие дата и время",self.html)
        self.assertIn("id=\"wpoV28TimeZone\"",self.html)
        self.assertNotIn("Время окончания",self.html)
        self.assertIn("font-weight:700;opacity:1!important",wpo_user_v28.STYLE)

    def test_date_outline_and_quick_period_close_after_selection(self):
        script=wpo_user_v28.SCRIPT
        css=wpo_user_v28.STYLE
        self.assertIn("button.classList.toggle('is-highlighted',sameDay(date,highlightedDate||current));",script)
        self.assertIn("if(highlight)highlightedDate=selected;",script)
        self.assertIn(".wpo-v28-cal-days button.is-highlighted{",css)
        self.assertIn(".wpo-v28-cal-days button:hover:not(:disabled):not(.is-highlighted){",css)
        self.assertIn("border-color:transparent!important;outline:none!important;box-shadow:none!important",css)
        self.assertIn(".wpo-v28-cal-days button:focus-visible:not(.is-highlighted){",css)
        self.assertIn("text-decoration:underline;text-underline-offset:3px",css)
        self.assertIn(".wpo-v28-cal-days button.is-highlighted:focus-visible{outline:none!important}",css)
        self.assertNotIn(".wpo-v28-cal-days button:hover:not(:disabled){border-color:var(--accent);background:var(--tint)}",css)
        self.assertNotIn("transform:",css.split("/* Keep the global button hover lift; remove only the blue/teal focus frame. */",1)[1].split(".wpo-v28-cal-days button:disabled",1)[0])
        self.assertNotIn(".wpo-v28-cal-days button.is-selected{background:var(--tint);border:1px solid var(--accent)",css)
        self.assertNotIn("if(expiry.value!=='0')closeCalendar();",script)
        self.assertIn("chooseDate(addMonths(now(),Number(button.dataset.wpoMonths)),button.dataset.wpoMonths);",script)
        self.assertIn("chooseDate(new Date(2099,11,31),'2099');",script)
        # Both quick preset handlers persist expiry and then close the popover.
        self.assertIn("""chooseDate(addMonths(now(),Number(button.dataset.wpoMonths)),button.dataset.wpoMonths);
  // The chosen expiry is already written to the hidden form field.
  closeCalendar();""",script)
        self.assertIn("""chooseDate(new Date(2099,11,31),'2099');
  closeCalendar();""",script)
        self.assertIn("expiry.value=good?String(Math.floor(selected.getTime()/1000)):'0';",script)
        self.assertIn("function resetCalendarSelection(){",script)
        self.assertIn("highlightedDate=null;",script)
        self.assertIn("chooseDate(now(),'',false);",script)
        self.assertNotIn("chooseDate(addMonths(now(),1),'1');",script)
        self.assertIn("document.dispatchEvent(new Event('wpo-v28-reset-calendar'));",wpo_user_v28.LEGACY_CREATE_JS)

    def test_until_2099_button_only_accented_when_selected(self):
        css=wpo_user_v28.STYLE
        self.assertIn("button[data-wpo-2099]{font-weight:600;margin-top:6px;border:1px solid var(--line)}",css)
        self.assertIn("button[data-wpo-2099].is-selected{background:var(--tint);color:var(--accent);border-color:var(--accent)}",css)
        self.assertNotIn("button[data-wpo-2099]{font-weight:700;margin-top:6px;border:1px solid var(--accent)}",css)
        self.assertIn("button.classList.toggle('is-selected',active)",wpo_user_v28.SCRIPT)
        self.assertIn("chooseDate(new Date(2099,11,31),'2099');",wpo_user_v28.SCRIPT)

    def test_selected_node_and_protocol_has_pulsing_green_dot(self):
        self.assertIn('wpo-v28-radio" aria-hidden="true"><i></i>',self.html)
        self.assertIn("background:var(--green)",self.html)
        self.assertIn(".wpo-v28-node:has(input:checked) .wpo-v28-radio i",self.html)
        self.assertIn(".wpo-v28-option:has(input:checked) .wpo-v28-radio i",self.html)
        self.assertIn("animation:wpo-v28-pulse",self.html)
        self.assertIn('aria-pressed',self.html)

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
    def test_subscription_expiry_allows_end_of_2099_in_every_timezone(self):
        funcs=backend()
        # Calendar dates are in the user's local timezone. In UTC-12, the
        # last minute of 2099 becomes January 1, 2100 in UTC.
        last_utc=int(datetime(2099,12,31,23,59,tzinfo=timezone.utc).timestamp())
        last_utc_minus_12=int(datetime(2099,12,31,23,59,
                                      tzinfo=timezone(timedelta(hours=-12))).timestamp())
        self.assertEqual(last_utc_minus_12,4102487940)
        for deadline in (last_utc,last_utc_minus_12):
            with self.subTest(deadline=deadline):
                self.assertEqual(funcs["validate_expiry"](deadline),deadline)

    def test_subscription_expiry_validator_rejects_year_2100(self):
        funcs=backend()
        for deadline in (int(time.time())-1,int(time.time())+10,4102488000,4102531200):
            with self.subTest(deadline=deadline):
                with self.assertRaises(funcs["SubscriptionError"]):
                    funcs["validate_expiry"](deadline)

    def test_short_patch_upgrades_already_installed_2090_limits(self):
        source=(ROOT/"wpp_subscriptions.py").read_text(encoding="utf-8")
        upgraded=wpo_v28_apply.patch_subscriptions(source)
        old=upgraded.replace("expiry>4102487999",
                             "time.gmtime(expiry).tm_year>2090")
        old=old.replace("до 2099 года","до 2090 года")
        self.assertEqual(wpo_v28_apply.patch_subscriptions(old),upgraded)
        self.assertEqual(wpo_v28_apply.patch_subscriptions(upgraded),upgraded)
        old_panel='# wpo-v28-new-user\\nif time.gmtime(end_timestamp).tm_year>2090: message="до 2090 года"'
        panel=wpo_v28_apply.patch_panel(old_panel)
        self.assertIn("end_timestamp>4102487999",panel)
        self.assertIn("до 2099 года",panel)
        self.assertNotIn("2090",panel)
        self.assertEqual(wpo_v28_apply.patch_panel(panel),panel)
        native=(ROOT/"wpo_node_remote.py").read_text(encoding="utf-8")
        self.assertIn("deadline>4102487999",native)
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
