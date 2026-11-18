"""WPO V28: routing indicator and read-only live JSON viewer on Node cards."""
from html import escape
import json
import re
from pathlib import Path

import wpp_connections
import wpp_routing
import wpo_xray_modes as modes

ROUTING_PATH = "/var/lib/tproxy-panel/routing.json"
CONNECTIONS_PATH = "/etc/web-proxy-panel/connections.json"

STYLES = r'''<style id="wpo-xray-view-v28-style">
.wpo-xray-mode-card{display:grid;gap:7px}
.wpo-xray-route{display:flex;align-items:center;gap:6px;min-width:0;padding:3px 2px 1px}
.wpo-xray-route-dot{display:block;flex:0 0 auto;width:7px;height:7px;border-radius:50%;
 background:var(--muted);box-shadow:0 0 0 3px color-mix(in srgb,var(--muted) 13%,transparent)}
.wpo-xray-route-dot.on{background:var(--green,#36d399);box-shadow:0 0 0 3px color-mix(in srgb,var(--green,#36d399) 16%,transparent)}
.wpo-xray-route-dot.partial{background:#dca640;box-shadow:0 0 0 3px #dca64020}
.wpo-xray-route-text{flex:1;min-width:0;color:var(--muted);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wpo-xray-code-open{flex:0 0 auto;border:1px solid var(--line);background:var(--input);color:var(--text);
 border-radius:7px;min-height:28px;padding:3px 9px;font-size:10px;cursor:pointer}
.wpo-xray-code-open:hover{border-color:var(--accent);color:var(--accent)}
#wpoXrayCodeDialog{width:min(820px,calc(100vw - 26px));height:min(700px,calc(100dvh - 32px));
 max-height:calc(100dvh - 32px);padding:0;border:1px solid var(--line);
 border-radius:15px;background:var(--surface);color:var(--text);overflow:hidden}
#wpoXrayCodeDialog::backdrop{background:#000a}
#wpoXrayCodeDialog .wpo-xray-code-wrap{height:100%;display:flex;flex-direction:column;min-height:0}
#wpoXrayCodeDialog .wpo-xray-code-header{padding:17px 19px;display:flex;align-items:center;gap:12px;
 border-bottom:1px solid var(--line)}
#wpoXrayCodeDialog .wpo-xray-code-header>div{flex:1;min-width:0}
#wpoXrayCodeDialog h3{font-size:17px;margin:0}
#wpoXrayCodeDialog small{display:block;margin-top:4px;font-size:10px;color:var(--muted)}
#wpoXrayCodeDialog .wpo-xray-code-close{width:34px;height:34px;padding:0}
#wpoXrayCodeDialog .wpo-xray-code-info{margin:13px 19px 0;font-size:11px;color:var(--muted);line-height:1.5}
#wpoXrayCodeDialog textarea{display:block;box-sizing:border-box;min-height:0;flex:1;width:calc(100% - 38px);
 margin:12px 19px;resize:none;overflow:auto;white-space:pre;tab-size:2;
 border:1px solid var(--line);border-radius:10px;padding:15px;background:var(--input);
 color:var(--text);font:11px/1.55 ui-monospace,monospace}
#wpoXrayCodeDialog .wpo-xray-code-actions{border-top:1px solid var(--line);
 display:flex;justify-content:flex-end;gap:8px;padding:12px 19px}
#wpoXrayCodeDialog button{font-size:11px}
@media(max-width:580px){#wpoXrayCodeDialog .wpo-xray-code-actions{flex-wrap:wrap}
#wpoXrayCodeDialog .wpo-xray-code-actions button{flex:1 1 auto}}
</style>'''

SCRIPT = r'''<script id="wpo-xray-view-v28-script">
(()=>{
 'use strict';
 const dialog=document.getElementById('wpoXrayCodeDialog');
 if(!dialog)return;
 const path=dialog.dataset.endpoint,csrf=dialog.dataset.csrf;
 const title=dialog.querySelector('[data-wpo-code-node]');
 const code=dialog.querySelector('[data-wpo-code]');
 const revealButton=dialog.querySelector('[data-wpo-code-reveal]');
 const copyButton=dialog.querySelector('[data-wpo-code-copy]');
 const note=dialog.querySelector('[data-wpo-code-note]');
 let selected='',generation=0,revealed=false;
 async function fetchConfig(reveal){
   const current=++generation;
   code.value='Загрузка конфигурации…';
   revealButton.disabled=true;copyButton.disabled=true;
   try{
     const res=await fetch(path,{method:'POST',credentials:'same-origin',
       headers:{'Accept':'application/json','X-WPP-Async':'1',
                'Content-Type':'application/x-www-form-urlencoded'},
       body:new URLSearchParams({csrf,id:selected,reveal:reveal?'1':'0'}),
       cache:'no-store'});
     if(res.redirected)throw Error('Сессия завершена. Войдите заново.');
     const body=await res.json();
     if(!res.ok||!body.ok)throw Error(body.message||'Не удалось загрузить конфигурацию');
     if(current!==generation||!dialog.open)return;
     code.value=JSON.stringify(body.config,null,2);
     revealed=Boolean(body.secrets_visible);
     revealButton.textContent=revealed?'Скрыть ключи':'Показать ключи';
     revealButton.disabled=false;copyButton.disabled=false;
     note.textContent=revealed
       ?'Приватные ключи и UUID отображаются. Не отправляйте этот JSON посторонним.'
       :'Действующая серверная конфигурация. Секреты скрыты; JSON доступен только для чтения.';
   }catch(error){
     if(current!==generation||!dialog.open)return;
     code.value='Ошибка: '+(error.message||'Неизвестная ошибка');
     revealButton.disabled=false;
     note.textContent='Не удалось получить рабочую конфигурацию ноды.';
   }
 }
 document.querySelectorAll('[data-wpo-xray-code-open]').forEach(button=>{
   button.addEventListener('click',()=>{
     selected=button.dataset.wpoXrayCodeOpen;
     title.textContent=button.dataset.wpoXrayCodeName||'Нода';
     revealed=false;
     dialog.showModal();
     fetchConfig(false);
   });
 });
 revealButton.addEventListener('click',()=>{
   if(!revealed && !window.confirm('Показать приватные ключи, UUID и другие секреты Xray? Не передавайте этот JSON другим людям.'))return;
   fetchConfig(!revealed);
 });
 copyButton.addEventListener('click',async()=>{
   try{await navigator.clipboard.writeText(code.value);
      const original=copyButton.textContent;copyButton.textContent='Скопировано';
      setTimeout(()=>{copyButton.textContent=original},1600);
   }catch(_e){copyButton.textContent='Не удалось скопировать';}
 });
 dialog.querySelector('[data-wpo-xray-code-close]').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{generation++;code.value='';selected='';revealed=false;});
})();
</script>'''


def routing_flags():
    """Fresh persisted connection-routing state, not a synthetic green status."""
    connections = wpp_connections.load(CONNECTIONS_PATH).get("connections", [])
    profiles = wpp_routing.load(ROUTING_PATH).get("profiles", {})
    found = {"reality": False, "hysteria": False}
    for connection in connections:
        if not isinstance(connection, dict) or not connection.get("enabled", True):
            continue
        proto = connection.get("protocol")
        if proto not in found:
            continue
        value = profiles.get(str(connection.get("id","")))
        if not isinstance(value, dict):
            continue
        profile = wpp_routing.validate(value)
        if profile.get("enabled", True) and (any(profile.get(key, False) for key in wpp_routing.ROUTING_FLAGS)
                or profile.get("direct_domains") or profile.get("proxy_domains")):
            found[proto] = True
    return found


def display(mode, status):
    active = modes.allowed(mode)
    parts = [p for p in ("reality", "hysteria") if p in active]
    enabled = sum(bool(status.get(p)) for p in parts)
    if enabled == len(parts):
        return "on", "JSON · Маршрутизация включена"
    if enabled:
        return "partial", "JSON · Частично включена"
    return "off", "JSON · Не подключён"


def attach(html, nodes, path, csrf):
    if "wpo-xray-view-v28-style" in html:
        return html
    state = routing_flags()
    node_map = {str(n.get("id")):n for n in nodes if isinstance(n,dict)}
    marker = re.compile(r'(<div class="wpo-xray-mode-card">.*?</button>)(</div>)', re.S)
    found = set()
    def add(match):
        content=match.group(1)
        uid_match=re.search(r'data-wpo-xray-mode-open="(local|[a-f0-9]{16})"',content)
        if not uid_match:
            return match.group(0)
        uid=uid_match.group(1)
        node=node_map.get(uid) if uid!="local" else None
        if uid!="local" and node is None:
            return match.group(0)
        found.add(uid)
        mode=modes.get(modes.PANEL_STATE) if uid=="local" else modes.normalize(node.get("xray_mode","both"))
        name="Основная нода" if uid=="local" else str(node.get("name") or node.get("country_name") or "Нода")[:80]
        variant,label=display(mode,state)
        detail='REALITY: '+('вкл.' if state["reality"] else 'выкл.')+' · Hysteria2: '+('вкл.' if state["hysteria"] else 'выкл.')
        ui=(
            '<div class="wpo-xray-route" title="'+escape(detail,quote=True)+'">'
            '<span class="wpo-xray-route-dot '+variant+'" aria-hidden="true"></span>'
            '<span class="wpo-xray-route-text">'+escape(label)+'</span>'
            '<button type="button" class="wpo-xray-code-open" '
            'data-wpo-xray-code-open="'+escape(uid,quote=True)+'" '
            'data-wpo-xray-code-name="'+escape(name,quote=True)+'" '
            'aria-label="Просмотр Xray JSON ноды '+escape(name,quote=True)+'">JSON</button></div>'
        )
        return content+ui+match.group(2)
    result=marker.sub(add,html)
    expected={"local"}|set(node_map)
    if found!=expected:
        raise RuntimeError("WPO: не удалось добавить JSON и маршрутизацию во все карточки нод.")
    modal=(
        '<dialog id="wpoXrayCodeDialog" data-endpoint="'+escape(path+'/node-xray-view',quote=True)+'"'
        ' data-csrf="'+escape(csrf,quote=True)+'">'
        '<div class="wpo-xray-code-wrap"><div class="wpo-xray-code-header"><div>'
        '<h3>Конфигурация Xray</h3><small data-wpo-code-node></small></div>'
        '<button type="button" class="wpo-xray-code-close" data-wpo-xray-code-close '
        'aria-label="Закрыть">×</button></div>'
        '<p class="wpo-xray-code-info" data-wpo-code-note>Рабочая конфигурация выбранной ноды.</p>'
        '<textarea data-wpo-code readonly spellcheck="false" aria-label="Xray JSON"></textarea>'
        '<div class="wpo-xray-code-actions">'
        '<button type="button" data-wpo-code-reveal>Показать ключи</button>'
        '<button type="button" data-wpo-code-copy>Копировать JSON</button>'
        '<button type="button" class="primary" data-wpo-xray-code-close>Закрыть</button>'
        '</div></div></dialog>'
    )
    return STYLES+result+modal+SCRIPT


def install_ui(ns):
    original=ns["nodes_ui"]
    def nodes_ui(*args,**kwargs):
        html=original(*args,**kwargs)
        nodes=args[0] if args else kwargs["nodes"]
        path=args[3] if len(args)>3 else kwargs["path"]
        csrf=args[4] if len(args)>4 else kwargs["csrf"]
        return attach(html,nodes,path,csrf)
    ns["nodes_ui"]=nodes_ui
