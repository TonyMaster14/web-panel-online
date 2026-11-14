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
             c.get("enabled", True) and c.get("protocol") in VPN_SUPPORTED]
    choices = []
    for protocol, title, description, _kind in CATALOG:
        if protocol in VPN_SUPPORTED:
            conn = next((item for item in valid if item.get("protocol") == protocol), None)
            if conn:
                cid = str(conn.get("id", ""))
                if not (3 <= len(cid) <= 64):
                    continue
                choices.append(
                    f'<label class="wpo-v28-option"><input class="wpo-v28-protocol" type="checkbox" '
                    f'name="connection_{h(cid)}" value="1" data-protocol="{h(protocol)}" '
                    f'data-label="{h(title)}" checked><span class="wpo-v28-radio">✓</span>'
                    f'<span><strong>{h(title)}</strong><small>{h(description)}</small></span></label>'
                )
            else:
                choices.append(f'<label class="wpo-v28-option unavailable"><input type="checkbox" disabled>'
                               f'<span class="wpo-v28-radio">—</span><span><strong>{h(title)}</strong>'
                               '<small>Сначала добавьте подключение в разделе «Подключения»</small></span></label>')
        else:
            choices.append(
                f'<label class="wpo-v28-option unavailable" title="Протокол ещё не поддерживается удалёнными нодами">'
                '<input type="checkbox" disabled><span class="wpo-v28-radio">—</span><span>'
                f'<strong>{h(title)}</strong><small>{h(description)} · подключим следующим этапом</small>'
                '</span></label>'
            )
    location = local if isinstance(local, dict) else {}
    local_label = str(location.get("name") or location.get("country_name") or "Основная нода")
    local_card = (
        '<label class="wpo-v28-node"><input type="checkbox" name="node_local" value="1" checked>'
        '<span class="wpo-v28-radio">✓</span>'
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
            '<span class="wpo-v28-radio">✓</span>'
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
        '<input type="hidden" name="nodes_selector_present" value="1">'
        '<input type="hidden" name="expires_at" id="wpoV28Expiry" value="0">'
        '<label for="accountName" class="wpo-v28-label">Имя конфигурации</label>'
        '<input id="accountName" name="name" placeholder="Например, Анна · iPhone" '
        'maxlength="80" autocomplete="off" required>'
        '<div class="wpo-v28-section">'
        '<details class="wpo-v28-calendar" id="wpoV28Calendar"><summary>'
        '<span><b>Срок действия</b><small id="wpoV28DateDisplay">Выбрать дату и время окончания</small></span>'
        '<span aria-hidden="true">▦</span></summary>'
        '<div class="wpo-v28-calendar-body">'
        '<label>Дата и время окончания<input id="wpoV28Date" type="datetime-local" '
        'min="2026-01-01T00:00" max="2090-12-31T23:59"></label>'
        '<div class="wpo-v28-months" aria-label="Быстрый срок">'
        + "".join(f'<button type="button" data-wpo-months="{m}">{m} мес.</button>' for m in (1,2,3,6,12))
        + '</div><small id="wpoV28TimeZone"></small></div></details></div>'
        '<div class="wpo-v28-limits">'
        '<label>Устройств<input id="deviceLimit" name="max_devices" type="number" min="0" max="20" value="2" required>'
        '<small>0 — без ограничения HWID</small></label>'
        '<label>Трафик, ГБ<input id="wpoV28Traffic" name="traffic_limit_gb" type="number" '
        'min="0" max="100000" step="0.1" value="0" required>'
        '<small>0 — без лимита · ограничение вводим после общего учёта нод</small></label>'
        '</div><section id="subscriptionFields" class="create-step">'
        '<div class="wpo-v28-section"><h3>Ноды</h3><p>Выбери одну или несколько VPN-нод</p>'
        '<div class="wpo-v28-grid">' + "".join(node_cards) + '</div></div>'
        '<div class="wpo-v28-section"><h3>Протоколы</h3><p>Happ и остальные поддерживаемые приложения</p>'
        '<div id="subscriptionConnections" class="wpo-v28-grid">' + "".join(choices) +
        '</div></div></section>'
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
.wpo-v28-section{display:grid;gap:9px}
.wpo-v28-section h3{margin:0;font-size:13px}
.wpo-v28-section p{margin:0;color:var(--muted);font-size:11px}
.wpo-v28-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.wpo-v28-node,.wpo-v28-option{position:relative;display:flex;align-items:center;gap:10px;padding:12px;
 border:1px solid var(--line);border-radius:12px;min-width:0;background:var(--surface);cursor:pointer}
.wpo-v28-node input,.wpo-v28-option input{position:absolute;opacity:0;pointer-events:none}
.wpo-v28-radio{display:grid;place-items:center;flex:0 0 19px;height:19px;border:1px solid var(--muted);
 border-radius:50%;font-size:11px;color:transparent}
.wpo-v28-node:has(input:checked),.wpo-v28-option:has(input:checked){border-color:var(--accent);
 background:var(--tint)}
.wpo-v28-node:has(input:checked) .wpo-v28-radio,
.wpo-v28-option:has(input:checked) .wpo-v28-radio{border-color:var(--accent);color:var(--accent)}
.wpo-v28-node>span:last-child,.wpo-v28-option>span:last-child{display:grid;min-width:0;gap:3px}
.wpo-v28-node strong,.wpo-v28-option strong{font-size:11px;overflow:hidden;text-overflow:ellipsis}
.wpo-v28-node small,.wpo-v28-option small{font-size:9px;line-height:1.4;color:var(--muted)}
.wpo-v28-flag{font-size:19px}.wpo-v28-dialog .unavailable{opacity:.48;cursor:not-allowed}
.wpo-v28-calendar{border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.wpo-v28-calendar summary{display:flex;justify-content:space-between;align-items:center;padding:13px 15px;cursor:pointer}
.wpo-v28-calendar summary span:first-child{display:grid;gap:5px}
.wpo-v28-calendar summary b{font-size:12px}.wpo-v28-calendar summary small{font-size:11px;color:var(--muted)}
.wpo-v28-calendar-body{display:grid;gap:11px;padding:4px 15px 15px}
.wpo-v28-months{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:5px}
.wpo-v28-months button{font-size:10px;padding:8px 0}
.wpo-v28-limits{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.wpo-v28-limits label{display:grid;gap:5px}.wpo-v28-limits label small{font-size:9px;color:var(--muted)}
.wpo-v28-dialog .create-summary small{display:block;margin-top:7px;color:var(--muted);font-size:10px}
@media(max-width:560px){.wpo-v28-grid{grid-template-columns:1fr}.wpo-v28-limits{grid-template-columns:1fr}
.wpo-v28-dialog #createClientForm{padding:12px}}
"""

SCRIPT = r"""(()=>{const f=document.getElementById('createClientForm'),dt=document.getElementById('wpoV28Date');
const display=document.getElementById('wpoV28DateDisplay'),expiry=document.getElementById('wpoV28Expiry');
if(!f||!dt||!expiry)return;
const tz=Intl.DateTimeFormat().resolvedOptions().timeZone||'Локальный часовой пояс';
document.getElementById('wpoV28TimeZone').textContent='Часовой пояс браузера: '+tz;
const fmt=d=>{const pad=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes())};
const current=()=>new Date();
function setDate(d){dt.value=fmt(d);syncDate()}
function syncDate(){const d=new Date(dt.value);const valid=Number.isFinite(d.getTime())&&d>current()&&d.getFullYear()<=2090;
expiry.value=valid?String(Math.floor(d.getTime()/1000)):'0';
display.textContent=valid?d.toLocaleString(undefined,{year:'numeric',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}):'Выбрать будущую дату';
}
function summary(){const ns=f.querySelectorAll('.wpo-v28-node input:checked').length,ps=f.querySelectorAll('.wpo-v28-protocol:checked').length;
document.getElementById('wpoV28Count').textContent=ns+' нод × '+ps+' протокола = '+(ns*ps)+' подключений для Happ';}
document.querySelectorAll('[data-wpo-months]').forEach(button=>button.addEventListener('click',()=>{
const d=current(),m=Number(button.dataset.wpoMonths),day=d.getDate();d.setDate(1);d.setMonth(d.getMonth()+m);d.setDate(Math.min(day,new Date(d.getFullYear(),d.getMonth()+1,0).getDate()));
setDate(d);document.getElementById('wpoV28Calendar').open=false;summary()}));
dt.addEventListener('change',syncDate);
f.addEventListener('change',()=>queueMicrotask(summary));
f.addEventListener('input',()=>queueMicrotask(summary));
document.getElementById('newAccount')?.addEventListener('click',()=>{setDate(new Date(current().getTime()+30*86400000));queueMicrotask(summary)});
document.addEventListener('submit',e=>{if(e.target!==f)return;syncDate();
const protocols=f.querySelectorAll('.wpo-v28-protocol:checked').length;
const nodes=f.querySelectorAll('.wpo-v28-node input:checked').length;
const err=document.getElementById('createError');
const traffic=Number(document.getElementById('wpoV28Traffic').value);
const message=!protocols?'Выберите хотя бы один доступный протокол.':!nodes?'Выберите хотя бы одну доступную ноду.':!Number(expiry.value)?'Выберите будущую дату окончания подписки.':(traffic>0?'Лимит трафика на нескольких нодах пока не активирован. Укажите 0 ГБ.':'');
if(message){e.preventDefault();e.stopImmediatePropagation();err.textContent=message;err.hidden=false;}},true);
setDate(new Date(current().getTime()+30*86400000));summary();
})();"""
