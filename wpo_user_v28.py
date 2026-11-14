"""WPO v28: one user creation form with nodes and protocol capabilities.

The existing controller still enforces the selected backends. Disabled
protocols are deliberately not submitted until a REAL remote service exists.
"""
from datetime import datetime
from html import escape
import json

# The catalog is shared conceptually with the panel's native protocols. A
# node VPN capability is not implied just because a protocol is displayed.
CATALOG = (
    ("vless", "VLESS XHTTP", "Happ · HTTPS 443", "happ"),
    ("hysteria", "Hysteria2", "Happ · QUIC/UDP 8443", "happ"),
    ("web", "WEB Proxy", "Telegram · отдельная ссылка", "telegram"),
    ("mtproto", "MTProto", "Telegram · отдельная ссылка", "telegram"),
    ("awg20", "AmneziaWG 2.0", "Amnezia · конфигурация", "amnezia"),
    ("awg31", "AmneziaWG 3.1", "Amnezia · конфигурация", "amnezia"),
    ("naive", "NaiveProxy", "Naive · отдельный профиль", "other"),
    ("mieru", "Mieru", "Mieru · отдельный профиль", "other"),
)
VPN_SUPPORTED = ("vless", "hysteria")


def flag(code):
    code = str(code or "").upper()
    return "".join(chr(127397 + ord(ch)) for ch in code) if len(code) == 2 and code.isalpha() and code != "UN" else "🌐"


def form(path, csrf, connections, nodes=None, local=None):
    """Build HTML for one supported remote-VPN client and a future-ready catalog.

    UI stays consistent with existing WPO Clients JS and its authenticated
    /create-account handler. The form emits connection_ID checkboxes, never
    arbitrary strings that can bypass server-side connection validation.
    """
    h = lambda value: escape(str(value), quote=True)
    valid = [c for c in (connections or []) if isinstance(c, dict) and
             c.get("enabled", True) and c.get("protocol") in {v[0] for v in CATALOG}]
    choices = []
    for protocol, title, description, _kind in CATALOG:
        conn = next((item for item in valid if item.get("protocol") == protocol), None)
        if conn:
            cid = str(conn.get("id", ""))
            if not (3 <= len(cid) <= 64):
                continue
            native = protocol not in VPN_SUPPORTED
            subtitle = description + (" · одна выбранная нода" if native else " · выбранные ноды")
            choices.append(
                f'<label class="wpo-v28-option"><input class="wpo-v28-protocol" type="checkbox" '
                f'name="connection_{h(cid)}" value="1" data-connection-id="{h(cid)}" '
                f'data-protocol="{h(protocol)}" data-label="{h(title)}" '
                f'><span class="wpo-v28-radio" aria-hidden="true"><i></i></span>'
                f'<span><strong>{h(title)}</strong><small>{h(subtitle)}</small></span></label>'
            )
        else:
            choices.append(
                f'<label class="wpo-v28-option unavailable"><input type="checkbox" disabled>'
                f'<span class="wpo-v28-radio" aria-hidden="true"><i></i></span><span><strong>{h(title)}</strong>'
                '<small>Сначала добавьте подключение в разделе «Подключения»</small></span></label>'
            )
    location = local if isinstance(local, dict) else {}
    local_label = str(location.get("name") or location.get("country_name") or "Основная нода")
    local_card = (
        '<label class="wpo-v28-node"><input type="checkbox" name="node_local" value="1" checked>'
        '<span class="wpo-v28-radio" aria-hidden="true"><i></i></span>'
        f'<span class="wpo-v28-flag">{flag(location.get("country_code"))}</span>'
        f'<span><strong>{h(local_label)}</strong><small>Основная · VPN готов</small></span></label>'
    )
    node_cards = [local_card]
    for node in (nodes or []):
        if not isinstance(node, dict): continue
        node_id = str(node.get("id", ""))
        if len(node_id) != 16 or any(ch not in "0123456789abcdef" for ch in node_id):
            continue
        caps = set(str(s) for s in node.get("capabilities", []) if isinstance(s, str))
        ready = (node.get("enabled", True) and node.get("status", "offline") == "online" and
                 all(p in caps for p in VPN_SUPPORTED) and "federation" in caps)
        name = str(node.get("name") or node.get("country_name") or "Нода")
        state = "VPN готова" if ready else "VPN пока не готова"
        node_cards.append(
            f'<label class="wpo-v28-node{" unavailable" if not ready else ""}">'
            f'<input type="checkbox" name="node_{node_id}" value="1" {" " if ready else "disabled"}>'
            '<span class="wpo-v28-radio" aria-hidden="true"><i></i></span>'
            f'<span class="wpo-v28-flag">{flag(node.get("country_code"))}</span>'
            f'<span><strong>{h(name)}</strong><small>{h(state)}</small></span></label>'
        )
    # Existing Clients JS references these DOM ids and adds its own hidden
    # fields. Maintain compatibility; do not replace the existing JS.
    hidden_compat = (
        '<input type="radio" name="access_mode" value="subscription" checked hidden>'
        '<section class="create-step" id="directFields" hidden>'
        '<label hidden><input type="radio" name="direct_protocol" value="vless" checked></label></section>'
        '<section class="create-step" id="quickFields" hidden></section>'
    )
    return (
        '<dialog id="createAccount" class="create-dialog wpo-v28-dialog">'
        '<div class="dialog-head"><div><h2>Новый пользователь</h2>'
        '<small>Конфигурация · выбранные ноды и протоколы</small></div>'
        '<button type="button" data-close-dialog aria-label="Закрыть">×</button></div>'
        f'<form id="createClientForm" method="post" action="{h(path)}/create-account">'
        f'<input type="hidden" name="csrf" value="{h(csrf)}">'
        '<div id="createError" class="create-error" role="alert" hidden></div>'
        '<input type="hidden" id="accountKind" name="kind" value="subscription">'
        '<input type="hidden" id="wpoV28DirectConnection" name="connection_id" value="">'
        '<input type="hidden" id="wpoV28DirectDevices" name="direct_devices" value="1">'
        '<input type="hidden" name="nodes_selector_present" value="1">'
        '<input type="hidden" name="expires_at" id="wpoV28Expiry" value="0">'
        '<label for="accountName" class="wpo-v28-label">Имя конфигурации</label>'
        '<input id="accountName" name="name" placeholder="Например, Анна · iPhone" '
        'maxlength="80" autocomplete="off" required>'
        '<div class="wpo-v28-section wpo-v28-date-section">'
        '<details class="wpo-v28-calendar" id="wpoV28Calendar"><summary>'
        '<span class="wpo-v28-date-head"><b>Срок действия</b>'
        '<small id="wpoV28DateDisplay">Выбрать дату и время окончания</small></span>'
        '<svg class="wpo-v28-calendar-icon" width="23" height="23" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect x="3" y="5" width="18" height="16" rx="2.5"/>'
        '<path d="M7 3v4M17 3v4M3 10h18"/>'
        '<path d="M8 14h2M14 14h2M8 18h2"/></svg></summary>'
        '<div class="wpo-v28-calendar-body">'
        '<input id="wpoV28Date" type="hidden" value="">'
        '<aside class="wpo-v28-cal-aside" aria-label="Быстрый выбор срока">'
        '<b>Быстрый срок</b><div class="wpo-v28-months">'
        + "".join(f'<button type="button" data-wpo-months="{m}">{m} '
                  f'{"месяц" if m == 1 else "месяца" if m in (2, 3) else "месяцев"}</button>'
                  for m in (1, 2, 3, 6, 12))
        + '</div></aside>'
        '<div class="wpo-v28-cal-main">'
        '<div class="wpo-v28-cal-toolbar">'
        '<button type="button" id="wpoV28PrevMonth" class="wpo-v28-cal-nav" '
        'aria-label="Предыдущий месяц">&#8249;</button>'
        '<select id="wpoV28Month" aria-label="Месяц календаря">'
        + "".join(f'<option value="{i}">{h(month)}</option>'
                   for i, month in enumerate(("Январь", "Февраль", "Март", "Апрель",
                                              "Май", "Июнь", "Июль", "Август",
                                              "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")))
        + '</select>'
        '<select id="wpoV28Year" aria-label="Год календаря"></select>'
        '<button type="button" id="wpoV28NextMonth" class="wpo-v28-cal-nav" '
        'aria-label="Следующий месяц">&#8250;</button></div>'
        '<div class="wpo-v28-cal-weekdays" aria-hidden="true">'
        + "".join(f'<span>{day}</span>' for day in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"))
        + '</div><div id="wpoV28DayGrid" class="wpo-v28-cal-days" '
        'role="group" aria-label="Выбрать день"></div>'
        '<div class="wpo-v28-cal-live">'
        '<i class="wpo-v28-live-dot" aria-hidden="true"></i>'
        '<span>Сегодня: <time id="wpoV28CurrentDateTime"></time></span></div>'
        '<div class="wpo-v28-cal-time">'
        '<span class="wpo-v28-time-label">Время окончания</span>'
        '<label for="wpoV28Hour">Часы<select id="wpoV28Hour" aria-label="Часы">'
        + "".join(f'<option value="{i}">{i:02d}</option>' for i in range(24))
        + '</select></label><span class="wpo-v28-time-colon">:</span>'
        '<label for="wpoV28Minute">Минуты<select id="wpoV28Minute" aria-label="Минуты">'
        + "".join(f'<option value="{i}">{i:02d}</option>' for i in range(60))
        + '</select></label>'
        '<small id="wpoV28TimeZone"></small></div>'
        '<div class="wpo-v28-cal-actions">'
        '<button type="button" id="wpoV28Today">Сегодня</button>'
        '<button type="button" class="primary" id="wpoV28Apply">Применить</button>'
        '</div></div></div></details></div>'
        '<div class="wpo-v28-limits">'
        '<label class="wpo-v28-limit-field"><span>Устройств</span>'
        '<input id="deviceLimit" name="max_devices" type="number" min="0" max="20" value="2" required>'
        '<small>0 — без ограничения HWID</small></label>'
        '<label class="wpo-v28-limit-field"><span>Трафик, ГБ</span>'
        '<input id="wpoV28Traffic" name="traffic_limit_gb" type="number" '
        'min="0" max="100000" step="0.1" value="0" required>'
        '<small>0 — без лимита · общий учёт нод пока не подключён</small></label>'
        '</div><section id="subscriptionFields" class="create-step">'
        '<div class="wpo-v28-section"><h3>Ноды</h3><p>Выбери одну или несколько VPN-нод</p>'
        '<div class="wpo-v28-grid">' + "".join(node_cards) + '</div></div>'
        '<div class="wpo-v28-section"><h3>Протоколы</h3><p>Happ и остальные поддерживаемые приложения</p>'
        '<div id="subscriptionConnections" class="wpo-v28-grid">' + "".join(choices) +
        '</div><p>Happ объединяет выбранные ноды. Telegram, Amnezia, Naive и Mieru '
        'создаются отдельными профилями на одной выбранной ноде. '
        'Лимит срока для отдельных профилей пока нужно проверять отдельно.</p></div></section>'
        + hidden_compat +
        '<div class="create-summary"><span>Будет создано</span>'
        '<b id="createSummary">Подписка для Happ</b><small id="wpoV28Count"></small></div>'
        '<div class="actions create-actions"><button type="button" data-close-dialog>Отмена</button>'
        '<button class="primary" id="createClientSubmit">Создать пользователя</button></div>'
        '</form></dialog><style>' + STYLE + '</style><script>' + SCRIPT + '</script>'
    )


STYLE = """
.wpo-v28-dialog{width:min(680px,calc(100vw - 28px));max-height:92vh;overflow-y:auto}
.wpo-v28-dialog #createClientForm{display:grid;gap:13px;padding:15px 20px 20px}
.wpo-v28-label{font-weight:650}
.wpo-v28-section{display:grid;gap:9px;min-width:0}
.wpo-v28-section h3{margin:0;font-size:13px}
.wpo-v28-section p{margin:0;color:var(--muted);font-size:11px}
.wpo-v28-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;align-items:stretch}
.wpo-v28-node,.wpo-v28-option{position:relative;display:flex;align-items:center;gap:10px;padding:12px;
 border:1px solid var(--line);border-radius:12px;min-width:0;min-height:62px;
 margin:0;background:var(--surface);cursor:pointer;transition:background .18s,border-color .18s}
.wpo-v28-node input,.wpo-v28-option input{position:absolute;opacity:0;pointer-events:none;width:18px;height:18px}
.wpo-v28-radio{display:grid;place-items:center;flex:0 0 19px;width:19px;height:19px;
 border:1.5px solid var(--muted);border-radius:50%;background:transparent;transition:border-color .18s}
.wpo-v28-radio i{display:block;width:9px;height:9px;border-radius:50%;background:transparent}
.wpo-v28-node:has(input:checked),.wpo-v28-option:has(input:checked){border-color:var(--accent);
 background:var(--tint)}
.wpo-v28-node:has(input:checked) .wpo-v28-radio,.wpo-v28-option:has(input:checked) .wpo-v28-radio{
 border-color:var(--green)}
.wpo-v28-node:has(input:checked) .wpo-v28-radio i,
.wpo-v28-option:has(input:checked) .wpo-v28-radio i{
 background:var(--green);box-shadow:0 0 0 0 color-mix(in srgb,var(--green) 50%,transparent);
 animation:wpo-v28-pulse 1.8s ease-in-out infinite}
@keyframes wpo-v28-pulse{
 0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--green) 60%,transparent);opacity:1}
 55%{box-shadow:0 0 0 6px color-mix(in srgb,var(--green) 0%,transparent);opacity:.77}
}
.wpo-v28-node:has(input:focus-visible),.wpo-v28-option:has(input:focus-visible){
 outline:2px solid var(--accent);outline-offset:3px}
.wpo-v28-node>span:last-child,.wpo-v28-option>span:last-child{display:grid;min-width:0;gap:3px}
.wpo-v28-node strong,.wpo-v28-option strong{font-size:11px;overflow:hidden;text-overflow:ellipsis}
.wpo-v28-node small,.wpo-v28-option small{font-size:9px;line-height:1.4;color:var(--muted)}
.wpo-v28-flag{font-size:19px}.wpo-v28-dialog .unavailable{opacity:.48;cursor:not-allowed}
.wpo-v28-dialog .unavailable .wpo-v28-radio i{animation:none}
.wpo-v28-calendar{position:relative;z-index:8;border:1px solid var(--line);
 border-radius:12px;background:var(--surface)}
.wpo-v28-calendar[open]{border-color:var(--accent)}
.wpo-v28-calendar>summary{display:flex;justify-content:space-between;align-items:center;
 padding:13px 15px;cursor:pointer;list-style:none;gap:12px}
.wpo-v28-calendar>summary::-webkit-details-marker{display:none}
.wpo-v28-date-head{display:grid;gap:4px}
.wpo-v28-date-head b{font-size:12px;color:var(--text)}
.wpo-v28-date-head small{font-size:11px;color:var(--muted)}
.wpo-v28-calendar-icon{flex:0 0 auto;color:var(--accent);opacity:.92}
.wpo-v28-calendar[open] .wpo-v28-calendar-icon{filter:drop-shadow(0 0 5px var(--accent))}
.wpo-v28-calendar-body{position:absolute;top:calc(100% + 9px);left:0;right:0;z-index:30;
 display:grid;grid-template-columns:134px minmax(0,1fr);gap:15px;padding:15px;
 background:var(--raised);border:1px solid var(--line);border-radius:14px;
 box-shadow:0 18px 45px #0009}
.wpo-v28-calendar:not([open]) .wpo-v28-calendar-body{display:none}
.wpo-v28-cal-aside{display:flex;flex-direction:column;gap:12px;border-right:1px solid var(--line);
 padding-right:12px;min-width:0}
.wpo-v28-cal-aside>b{font-size:11px;color:var(--muted);white-space:nowrap}
.wpo-v28-months{display:flex;flex-direction:column;gap:6px}
.wpo-v28-months button{justify-content:flex-start;width:100%;padding:8px 9px;
 border-radius:8px;font-size:10px;background:var(--surface)}
.wpo-v28-months button.is-selected{background:var(--tint);color:var(--accent);border-color:var(--accent)}
.wpo-v28-cal-main{display:grid;gap:10px;min-width:0}
.wpo-v28-cal-toolbar{display:grid;grid-template-columns:31px minmax(0,1fr) 85px 31px;
 align-items:center;gap:5px}
.wpo-v28-cal-toolbar select{width:100%;height:32px;padding:4px 7px;
 font-size:11px;border-radius:8px;color:var(--text);background:var(--surface)}
.wpo-v28-cal-nav{height:32px;min-height:0;padding:0;display:grid;place-items:center;
 font-size:21px;line-height:1;background:var(--surface)}
.wpo-v28-cal-weekdays,.wpo-v28-cal-days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:3px}
.wpo-v28-cal-weekdays span{text-align:center;font-size:9px;color:var(--muted)}
.wpo-v28-cal-days button,.wpo-v28-cal-days>span{height:33px;width:100%;
 border-radius:8px;padding:0;font-size:11px;position:relative}
.wpo-v28-cal-days button{border:1px solid transparent;background:transparent}
.wpo-v28-cal-days button:hover:not(:disabled){border-color:var(--accent);background:var(--tint)}
.wpo-v28-cal-days button:disabled{opacity:.22;cursor:not-allowed}
.wpo-v28-cal-days button.is-today{color:var(--red);font-weight:700}
.wpo-v28-cal-days button.is-today::after{content:"";position:absolute;width:5px;height:5px;
 background:var(--red);border-radius:50%;bottom:2px;left:calc(50% - 2.5px)}
.wpo-v28-cal-days button.is-selected{background:var(--tint);border:1px solid var(--accent);color:var(--text)}
.wpo-v28-cal-live{display:flex;gap:8px;align-items:center;padding:8px 9px;border:1px solid var(--line);
 border-radius:8px;background:var(--surface);font-size:10px;color:var(--muted)}
.wpo-v28-live-dot{width:7px;height:7px;flex:0 0 7px;border-radius:50%;background:var(--red);
 box-shadow:0 0 0 3px color-mix(in srgb,var(--red) 15%,transparent)}
.wpo-v28-cal-time{display:flex;flex-wrap:wrap;align-items:end;gap:6px 8px}
.wpo-v28-time-label{width:100%;font-size:10px;color:var(--muted)}
.wpo-v28-cal-time label{display:grid;gap:3px;margin:0;font-size:9px;min-width:60px}
.wpo-v28-cal-time select{width:66px;height:33px;padding:4px 6px;
 font-size:12px;border-radius:8px;background:var(--surface)}
.wpo-v28-time-colon{align-self:center;margin-top:13px;font-weight:700}
.wpo-v28-cal-time small{flex:1;min-width:120px;font-size:9px;color:var(--muted);padding-bottom:8px}
.wpo-v28-cal-actions{display:flex;justify-content:space-between;gap:8px}
.wpo-v28-cal-actions button{padding:8px 11px;font-size:11px}
.wpo-v28-limits{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:10px}
.wpo-v28-limits .wpo-v28-limit-field{display:flex;flex-direction:column;align-items:stretch;
 gap:7px;margin:0;min-width:0;align-self:start}
.wpo-v28-limit-field>span{font-size:11px;font-weight:600;line-height:16px}
.wpo-v28-limits input{width:100%;height:40px;flex:0 0 40px;padding:9px 11px;
 margin:0;box-sizing:border-box}
.wpo-v28-limits small{display:block;min-height:30px;margin:0;font-size:9px;
 line-height:1.5;color:var(--muted)}
.wpo-v28-dialog .create-summary small{display:block;margin-top:7px;color:var(--muted);font-size:10px}
@media(max-width:560px){
 .wpo-v28-grid{grid-template-columns:1fr}
 .wpo-v28-calendar-body{position:static;grid-template-columns:1fr;box-shadow:none;padding:10px}
 .wpo-v28-cal-aside{border-right:0;border-bottom:1px solid var(--line);padding:0 0 10px}
 .wpo-v28-months{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px}
 .wpo-v28-months button{padding:8px 3px;font-size:9px;justify-content:center;text-align:center}
 .wpo-v28-dialog #createClientForm{padding:12px}
}
@media(max-width:380px){
 .wpo-v28-limits{grid-template-columns:1fr}
 .wpo-v28-cal-toolbar{grid-template-columns:28px minmax(0,1fr) 74px 28px}
}
@media(prefers-reduced-motion:reduce){
 .wpo-v28-node:has(input:checked) .wpo-v28-radio i,
 .wpo-v28-option:has(input:checked) .wpo-v28-radio i{animation:none}
}
"""

SCRIPT = r"""(()=>{
const f=document.getElementById('createClientForm');
const dt=document.getElementById('wpoV28Date');
const expiry=document.getElementById('wpoV28Expiry');
const display=document.getElementById('wpoV28DateDisplay');
const calendar=document.getElementById('wpoV28Calendar');
const grid=document.getElementById('wpoV28DayGrid');
const monthSelect=document.getElementById('wpoV28Month');
const yearSelect=document.getElementById('wpoV28Year');
const hourSelect=document.getElementById('wpoV28Hour');
const minuteSelect=document.getElementById('wpoV28Minute');
const apply=document.getElementById('wpoV28Apply');
if(!f||!dt||!expiry||!calendar||!grid||!monthSelect||!yearSelect||!hourSelect||!minuteSelect)return;
const tz=Intl.DateTimeFormat().resolvedOptions().timeZone||'Локальное время браузера';
const zoneLabel=document.getElementById('wpoV28TimeZone');
zoneLabel.textContent=tz;
const now=()=>new Date();
const pad=n=>String(n).padStart(2,'0');
const fmt=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes());
const sameDay=(a,b)=>a.getFullYear()===b.getFullYear()&&a.getMonth()===b.getMonth()&&a.getDate()===b.getDate();
let selected=null;
let viewYear=now().getFullYear();
let viewMonth=now().getMonth();
function addMonths(base,count){
  const result=new Date(base.getFullYear(),base.getMonth()+count,1,base.getHours(),base.getMinutes(),0,0);
  result.setDate(Math.min(base.getDate(),new Date(result.getFullYear(),result.getMonth()+1,0).getDate()));
  return result;
}
function formatSelected(d){
  return d.toLocaleString(undefined,{year:'numeric',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'});
}
function refreshClock(){
  const clock=document.getElementById('wpoV28CurrentDateTime');
  if(clock)clock.textContent=now().toLocaleString(undefined,{
    day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'
  });
}
function validDate(d){
  const current=now();
  return d instanceof Date&&Number.isFinite(d.getTime())&&
    d.getTime()>current.getTime()+59000&&d.getFullYear()>=current.getFullYear()&&
    d.getFullYear()<=2090&&d.getUTCFullYear()<=2090;
}
function syncDate(){
  if(!selected){expiry.value='0';display.textContent='Выберите дату окончания';apply.disabled=true;return;}
  const good=validDate(selected);
  dt.value=fmt(selected);
  expiry.value=good?String(Math.floor(selected.getTime()/1000)):'0';
  display.textContent=good?formatSelected(selected):'Выберите будущую дату и время';
  display.style.color=good?'':'var(--red)';
  apply.disabled=!good;
  hourSelect.value=String(selected.getHours());
  minuteSelect.value=String(selected.getMinutes());
}
function setDate(d,preset=0){
  selected=d;
  viewYear=d.getFullYear();
  viewMonth=d.getMonth();
  syncDate();
  document.querySelectorAll('[data-wpo-months]').forEach(button=>{
    button.classList.toggle('is-selected',Number(button.dataset.wpoMonths)===preset);
    button.setAttribute('aria-pressed',String(Number(button.dataset.wpoMonths)===preset));
  });
  renderCalendar();
}
function renderCalendar(){
  const current=now();
  if(!yearSelect.options.length){
    for(let year=current.getFullYear();year<=2090;year++){
      const option=document.createElement('option');
      option.value=String(year);option.textContent=String(year);
      yearSelect.appendChild(option);
    }
  }
  viewYear=Math.max(current.getFullYear(),Math.min(2090,viewYear));
  monthSelect.value=String(viewMonth);
  yearSelect.value=String(viewYear);
  const minIndex=current.getFullYear()*12+current.getMonth();
  const maxIndex=2090*12+11;
  const index=viewYear*12+viewMonth;
  document.getElementById('wpoV28PrevMonth').disabled=index<=minIndex;
  document.getElementById('wpoV28NextMonth').disabled=index>=maxIndex;
  grid.replaceChildren();
  const first=new Date(viewYear,viewMonth,1);
  const offset=(first.getDay()+6)%7;
  const count=new Date(viewYear,viewMonth+1,0).getDate();
  for(let i=0;i<offset;i++){
    const spacer=document.createElement('span');
    spacer.setAttribute('aria-hidden','true');grid.appendChild(spacer);
  }
  for(let day=1;day<=count;day++){
    const button=document.createElement('button');
    button.type='button';button.textContent=String(day);
    const date=new Date(viewYear,viewMonth,day);
    const endOfDay=new Date(viewYear,viewMonth,day,23,59,59,999);
    button.disabled=endOfDay.getTime()<=current.getTime();
    button.classList.toggle('is-today',sameDay(date,current));
    button.classList.toggle('is-selected',selected!==null&&sameDay(date,selected));
    button.setAttribute('aria-pressed',String(selected!==null&&sameDay(date,selected)));
    button.setAttribute('aria-label',date.toLocaleDateString(undefined,{
      weekday:'long',day:'numeric',month:'long',year:'numeric'
    }));
    button.addEventListener('click',()=>{
      let d=new Date(viewYear,viewMonth,day,
        selected?selected.getHours():current.getHours(),
        selected?selected.getMinutes():current.getMinutes(),0,0);
      if(d.getTime()<=now().getTime()+59000){
        const next=now();next.setMinutes(next.getMinutes()+2,0,0);
        d=next;
      }
      setDate(d);
    });
    grid.appendChild(button);
  }
}
function changeMonth(direction){
  const index=viewYear*12+viewMonth+direction;
  const min=now().getFullYear()*12+now().getMonth();
  if(index<min||index>2090*12+11)return;
  viewYear=Math.floor(index/12);
  viewMonth=index%12;
  renderCalendar();
}
document.getElementById('wpoV28PrevMonth').addEventListener('click',()=>changeMonth(-1));
document.getElementById('wpoV28NextMonth').addEventListener('click',()=>changeMonth(1));
monthSelect.addEventListener('change',()=>{viewMonth=Number(monthSelect.value);renderCalendar();});
yearSelect.addEventListener('change',()=>{viewYear=Number(yearSelect.value);renderCalendar();});
function changeTime(){
  if(!selected)return;
  const d=new Date(selected.getFullYear(),selected.getMonth(),selected.getDate(),
    Number(hourSelect.value),Number(minuteSelect.value),0,0);
  setDate(d);
}
hourSelect.addEventListener('change',changeTime);
minuteSelect.addEventListener('change',changeTime);
document.querySelectorAll('[data-wpo-months]').forEach(button=>button.addEventListener('click',()=>{
  setDate(addMonths(now(),Number(button.dataset.wpoMonths)),Number(button.dataset.wpoMonths));
}));
document.getElementById('wpoV28Today').addEventListener('click',()=>{
  const d=now();d.setHours(d.getHours()+1,0,0,0);
  setDate(d);
});
apply.addEventListener('click',()=>{
  syncDate();
  if(expiry.value!=='0')calendar.open=false;
});
calendar.addEventListener('toggle',()=>{if(calendar.open){refreshClock();renderCalendar();}});
document.addEventListener('click',e=>{
  if(calendar.open&&!calendar.contains(e.target))calendar.open=false;
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&calendar.open){
    e.preventDefault();e.stopPropagation();calendar.open=false;
  }
});
setInterval(refreshClock,1000);
function choice(){
  const selectedProtocols=[...f.querySelectorAll('.wpo-v28-protocol:checked')];
  const native=selectedProtocols.filter(el=>!['vless','hysteria'].includes(el.dataset.protocol));
  const checkedNodes=[...f.querySelectorAll('.wpo-v28-node input:checked')];
  return {selected:selectedProtocols,native,checkedNodes};
}
function summary(){
  const {selected,native,checkedNodes}=choice();
  const text=native.length
    ? (native.length===1&&selected.length===1&&checkedNodes.length===1
       ? '1 отдельный профиль · выбранная нода · '+native[0].dataset.label
       : 'Отдельные протоколы создаются по одному на выбранной ноде')
    : checkedNodes.length+' нод × '+selected.length+' протокола = '+(checkedNodes.length*selected.length)+' подключений Happ';
  document.getElementById('wpoV28Count').textContent=text;
  document.getElementById('createSummary').textContent=native.length?'Отдельная конфигурация':'Подписка для Happ';
}
f.addEventListener('change',()=>queueMicrotask(summary));
f.addEventListener('input',()=>queueMicrotask(summary));
document.getElementById('newAccount')?.addEventListener('click',()=>{
  calendar.open=false;
  setDate(addMonths(now(),1),1);
  queueMicrotask(summary);
});
document.addEventListener('submit',e=>{
  if(e.target!==f)return;
  syncDate();
  const {selected,native,checkedNodes}=choice();
  const err=document.getElementById('createError');
  const traffic=Number(document.getElementById('wpoV28Traffic').value);
  const kind=document.getElementById('accountKind');
  const connection=document.getElementById('wpoV28DirectConnection');
  const devices=document.getElementById('wpoV28DirectDevices');
  let message='';
  if(!selected.length)message='Выберите хотя бы один доступный протокол.';
  else if(!checkedNodes.length)message='Выберите хотя бы одну доступную ноду.';
  else if(native.length&&(selected.length!==1||checkedNodes.length!==1))
    message='WEB Proxy, Telegram, Amnezia, Naive и Mieru создаются по одному на одной ноде. Для общей подписки Happ выберите VLESS или Hysteria2.';
  else if(!Number(expiry.value))message='Выберите будущую дату окончания.';
  else if(!Number.isFinite(traffic)||traffic!==0)
    message='Общий лимит трафика пока не активирован. Укажите 0 ГБ.';
  if(message){
    e.preventDefault();e.stopImmediatePropagation();
    err.textContent=message;err.hidden=false;return;
  }
  if(native.length){
    kind.value=native[0].dataset.protocol;
    connection.value=native[0].dataset.connectionId;
    const limit=Number(document.getElementById('deviceLimit').value);
    devices.value=String(['awg20','awg31','naive','mieru'].includes(kind.value)?1:Math.max(1,Math.min(20,limit||1)));
  }else{
    kind.value='subscription';
    connection.value='';
  }
},true);
refreshClock();
setDate(addMonths(now(),1),1);
summary();
})();"""


# The old Clients JS assumes the "one key / subscription" wizard and its
# removed CDN/MTProto fields. Running that code against the new form breaks
# event registration BEFORE the Create button is usable. Replace only the
# obsolete wizard section while preserving client edit, QR and delete actions.
LEGACY_CREATE_JS = r"""
const createDialog=document.getElementById('createAccount');
const createForm=document.getElementById('createClientForm');
const createError=document.getElementById('createError');
const createSubmit=document.getElementById('createClientSubmit');
const openCreate=document.getElementById('newAccount');
function showCreateError(message){
  createError.textContent=message||'Не удалось создать пользователя.';
  createError.hidden=false;
  createError.scrollIntoView({block:'nearest',behavior:'smooth'});
}
openCreate.addEventListener('click',()=>{
  createForm.reset();
  createError.hidden=true;
  // Reapply an actual current date after the reset, not a stale default.
  document.querySelector('[data-wpo-months="1"]')?.click();
  // The calendar listener refreshes the preview after a reset.
  createDialog.showModal();
  setTimeout(()=>document.getElementById('accountName').focus(),30);
});
createDialog.querySelectorAll('[data-close-dialog]').forEach(button=>
  button.addEventListener('click',()=>createDialog.close()));
document.querySelectorAll('[data-open-client]').forEach(button=>
  button.addEventListener('click',()=>document.getElementById('client-'+button.dataset.openClient).showModal()));
createForm.addEventListener('input',()=>{createError.hidden=true;});
createForm.addEventListener('submit',async event=>{
  event.preventDefault();
  event.stopImmediatePropagation();
  const chosen=createForm.querySelectorAll('.wpo-v28-protocol:checked').length;
  const nodes=createForm.querySelectorAll('.wpo-v28-node input:checked').length;
  const expiry=Number(document.getElementById('wpoV28Expiry').value);
  const traffic=Number(document.getElementById('wpoV28Traffic').value);
  if(!chosen){showCreateError('Выберите хотя бы один доступный протокол.');return;}
  if(!nodes){showCreateError('Выберите хотя бы одну ноду.');return;}
  if(!expiry || expiry<=Math.floor(Date.now()/1000)+59){
    showCreateError('Укажите будущую дату окончания.');return;
  }
  if(!Number.isFinite(traffic)||traffic!==0){
    showCreateError('Общий лимит трафика пока не готов: укажите 0 ГБ.');return;
  }
  createError.hidden=true;
  createDialog.classList.add('is-submitting');
  createSubmit.disabled=true;
  createSubmit.textContent='Создаём…';
  try{
    const response=await fetch(createForm.action,{
      method:'POST',headers:{'X-WPP-Async':'1'},
      body:new URLSearchParams(new FormData(createForm))
    });
    if(response.redirected)throw Error('Сессия завершена. Войдите снова.');
    let result;
    try{result=await response.json();}
    catch(_){throw Error('Панель вернула некорректный ответ.');}
    if(!response.ok||!result.ok)throw Error(result.message||'Не удалось создать пользователя.');
    location.href=clientPath+'/users';
  }catch(error){showCreateError(error.message);}
  finally{
    createDialog.classList.remove('is-submitting');
    createSubmit.disabled=false;
    createSubmit.textContent='Создать пользователя';
  }
},true);
"""


def replace_legacy_create_js(source):
    """Keep every other WPO client-page action and use only the new form JS."""
    start_token = "const createDialog=document.getElementById('createAccount')"
    end_token = "async function requestClient(fields)"
    if source.count(start_token) != 1 or source.count(end_token) != 1:
        raise ValueError("The WPO Clients JS changed; refusing partial UI patch")
    start = source.index(start_token)
    end = source.index(end_token)
    if end <= start:
        raise ValueError("Old wizard boundaries are reversed")
    return source[:start] + LEGACY_CREATE_JS + "\n" + source[end:]
