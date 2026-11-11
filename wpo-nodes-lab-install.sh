#!/usr/bin/env bash
# WPO Nodes Lab installer: local panel patch only; never writes to GitHub.
set -Eeuo pipefail
umask 077
APP_DIR=/opt/tproxy-panel
DATA_DIR=/var/lib/tproxy-panel
SERVICE=tproxy-panel.service
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${DATA_DIR}/nodes-lab-backup-${STAMP}"
[[ $EUID -eq 0 ]] || { echo 'Запусти от root: sudo -i bash wpo-nodes-lab-install.sh'; exit 1; }
for f in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py; do
  [[ -s "$APP_DIR/$f" ]] || { echo "Не найден $APP_DIR/$f. Ничего не изменено."; exit 1; }
done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба $SERVICE."; exit 1; }
install -d -m 0700 "$BACKUP"
for f in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py; do cp -a "$APP_DIR/$f" "$BACKUP/$f"; done
echo "Резервная копия: $BACKUP"
export WPO_APP_DIR="$APP_DIR" WPO_DATA_DIR="$DATA_DIR"
if ! python3 - <<'PY_PATCH'
import os, re, sys, json, shlex
from pathlib import Path
app=Path(os.environ['WPO_APP_DIR'])
data=Path(os.environ['WPO_DATA_DIR'])
def get(n): return (app/n).read_text(encoding='utf-8')
def put(n,s,mode=0o644):
    p=app/n; t=p.with_suffix(p.suffix+'.labtmp'); t.write_text(s,encoding='utf-8'); t.chmod(mode); t.replace(p)
def once(s,a,b,label):
    c=s.count(a)
    if c!=1: raise RuntimeError(f'{label}: ожидался один фрагмент, найдено {c}; исходники не совпадают с проверенной версией.')
    return s.replace(a,b,1)
ui=get('wpp_ui.py'); panel=get('panel.py'); nodes=get('wpp_nodes.py'); subs=get('wpp_subscriptions.py')

# Node page with the five agreed statuses, add wizard, rename and delete controls.
start=ui.index('def nodes_ui('); end=ui.index('\n\nNODE_COUNTRIES',start)
new_nodes=r"""def nodes_ui(nodes, local, connection_token, path, csrf, pending_nodes=None):
    nodes=nodes if isinstance(nodes,list) else []
    local=local if isinstance(local,dict) else {}
    pending_nodes=pending_nodes if isinstance(pending_nodes,list) else []
    labels={'online':('В сети','online'),'installing':('Установка','installing'),'registration':('Регистрация','registration'),'offline':('Не в сети','offline'),'error':('Ошибка','error'),'disabled':('Отключена','disabled')}
    def status(uid,state):
        title,cls=labels.get(state,labels['offline'])
        return f'<span class="wpo-node-status {cls}" data-node-status="{esc(uid)}"><i></i><b>{title}</b></span>'
    counts={k:0 for k in ('online','installing','registration','offline','error')}
    cards=[]
    lc=str(local.get('country_code','UN')).upper()
    lname=str(local.get('country_name','Основная нода'))
    counts['online']+=1
    cards.append(f'<article class="card wpo-node-card"><div class="wpo-node-card-top"><span class="wpo-node-flag">{esc(node_flag(lc))}</span><div class="wpo-node-card-title"><strong>{esc(lname)}</strong><small>Основной сервер · локальная нода</small></div>{status("local","online")}</div><div class="wpo-node-card-meta"><span>Основная нода панели</span><span>Локальные подключения</span></div></article>')
    for n in nodes:
        uid=str(n.get('id','')); state=str(n.get('status','online' if n.get('enabled',True) else 'offline'))
        if state not in counts: state='offline'
        counts[state]+=1
        name=str(n.get('name') or n.get('country_name') or 'Нода')
        code=str(n.get('country_code','UN')).upper()
        caps=n.get('capabilities') if isinstance(n.get('capabilities'),list) else []
        cap='VLESS · Hysteria2' if 'federation' in caps or not caps else 'Node Agent'
        edit=f'<button class="icon-btn" type="button" data-node-edit="{esc(uid)}" data-node-name="{esc(name)}" title="Переименовать" aria-label="Переименовать">{icon("edit")}</button>'
        delete=f'<form method="post" action="{esc(path)}/node-action" data-confirm="Удалить ноду «{esc(name)}»? Все управляемые профили будут отозваны.">{hidden(csrf,operation="delete",id=uid)}<button class="icon-btn danger" title="Удалить" aria-label="Удалить">{icon("trash")}</button></form>'
        cards.append(f'<article class="card wpo-node-card"><div class="wpo-node-card-top"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-card-title"><strong>{esc(name)}</strong><small>{esc(n.get("country_name","Страна не определена"))} · {esc(n.get("url",""))}</small></div>{status(uid,state)}</div><div class="wpo-node-card-meta"><span>Агент {esc(n.get("version","—"))}</span><span>{esc(cap)}</span></div><div class="wpo-node-card-actions">{edit}{delete}</div></article>')
    for p in pending_nodes:
        uid=str(p.get('id','pending')); state=str(p.get('status','installing'))
        if state not in counts: state='error'
        counts[state]+=1
        cards.append(f'<article class="card wpo-node-card wpo-pending-node"><div class="wpo-node-card-top"><span class="wpo-node-flag">◇</span><div class="wpo-node-card-title"><strong>{esc(p.get("domain","Новая нода"))}</strong><small>Подключение новой ноды</small></div>{status(uid,state)}</div><div class="wpo-node-card-meta"><span>Установщик</span><span>{esc(p.get("detail","Ожидает установки"))}</span></div></article>')
    stats=''.join(f'<div class="wpo-node-stat"><span>{title}</span><strong data-node-count="{key}">{counts[key]}</strong></div>' for key,title in [('online','В сети'),('installing','Установка'),('registration','Регистрация'),('offline','Не в сети'),('error','Ошибка')])
    empty='' if nodes or pending_nodes else '<div class="wpo-node-empty"><b>Дополнительных нод пока нет</b><small>Нажмите «Добавить ноду», чтобы подключить чистый VPS.</small></div>'
    css='''
.wpo-nodes-page{display:grid;gap:15px}.wpo-nodes-toolbar{display:flex;align-items:center;justify-content:space-between;gap:15px}.wpo-nodes-toolbar h2{font-size:21px;margin:4px 0}.wpo-nodes-toolbar p{margin:0;color:var(--muted);font-size:11px}.wpo-add-node{display:flex;align-items:center;gap:8px;min-height:42px;padding:10px 16px;white-space:nowrap}.wpo-node-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.wpo-node-stat{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px;border:1px solid var(--line);border-radius:11px;background:var(--surface)}.wpo-node-stat span{font-size:10px;color:var(--muted)}.wpo-node-stat strong{font:600 21px ui-monospace,monospace}.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.wpo-node-card{margin:0;padding:16px;border:1px solid color-mix(in srgb,var(--accent) 12%,var(--line));border-radius:13px;background:linear-gradient(145deg,color-mix(in srgb,var(--surface) 98%,var(--accent)),var(--surface))}.wpo-node-card-top{display:flex;align-items:center;gap:10px;min-width:0}.wpo-node-flag{display:grid;place-items:center;flex:0 0 42px;height:42px;border:1px solid var(--line);border-radius:11px;background:var(--input);font-size:22px}.wpo-node-card-title{display:grid;gap:4px;min-width:0;flex:1}.wpo-node-card-title strong{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-card-title small{font-size:9px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-status{display:inline-flex;align-items:center;gap:6px;flex:0 0 auto;padding:6px 8px;border:1px solid var(--line);border-radius:20px;font-size:9px;white-space:nowrap}.wpo-node-status i,.wpo-node-legend i{width:7px;height:7px;border-radius:50%;background:#ef4444}.wpo-node-status.online i,.wpo-node-legend .online{background:#22c55e;box-shadow:0 0 0 4px #22c55218}.wpo-node-status.installing i,.wpo-node-legend .installing{background:#eab308}.wpo-node-status.registration i,.wpo-node-legend .registration{background:#38bdf8}.wpo-node-status.offline i,.wpo-node-status.error i,.wpo-node-legend .offline,.wpo-node-legend .error{background:#ef4444}.wpo-node-card-meta{display:flex;justify-content:space-between;gap:10px;margin-top:13px;padding-top:11px;border-top:1px solid var(--line);font-size:9px;color:var(--muted)}.wpo-node-card-actions{display:flex;justify-content:flex-end;align-items:center;gap:7px;margin-top:10px}.wpo-node-card-actions form{margin:0}.wpo-pending-node{border-style:dashed}.wpo-node-empty{grid-column:1/-1;display:grid;justify-items:center;gap:7px;padding:32px;border:1px dashed var(--line);border-radius:12px;text-align:center}.wpo-node-empty small{color:var(--muted);font-size:10px}.wpo-node-legend{display:flex;flex-wrap:wrap;gap:13px;color:var(--muted);font-size:9px}.wpo-node-legend span{display:flex;align-items:center;gap:6px}.wpo-node-dialog{width:min(550px,calc(100vw - 24px));padding:0;border:1px solid var(--line);border-radius:16px;background:var(--surface);color:var(--text)}.wpo-node-dialog .dialog-head{display:flex;align-items:center;justify-content:space-between;padding:17px 19px;border-bottom:1px solid var(--line)}.wpo-node-dialog .dialog-head h2{font-size:16px;margin:0}.wpo-node-dialog .dialog-head small{display:block;margin-top:4px;color:var(--muted);font-size:10px}.wpo-node-dialog-body{display:grid;gap:10px;padding:18px}.wpo-node-dialog-body label{display:grid;gap:6px;font-size:10px;color:var(--muted)}.wpo-node-dialog-body input,.wpo-node-dialog-body textarea{width:100%;font:10px ui-monospace,monospace}.wpo-step{display:flex;align-items:center;gap:10px}.wpo-step i{display:grid;place-items:center;width:25px;height:25px;border:1px solid var(--line);border-radius:50%;font-style:normal;color:var(--accent)}.wpo-step b,.wpo-step small{display:block}.wpo-step b{font-size:12px}.wpo-step small{margin-top:3px;color:var(--muted);font-size:9px}.wpo-copy-field{display:grid;grid-template-columns:1fr auto;gap:7px}.wpo-node-hint{margin:3px 0 0;padding:11px;border:1px solid var(--line);border-radius:9px;background:var(--input);font-size:10px;line-height:1.5;color:var(--muted)}@media(max-width:850px){.wpo-node-stats{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){.wpo-nodes-toolbar{align-items:stretch;flex-direction:column}.wpo-add-node{justify-content:center;width:100%}.wpo-node-stats{grid-template-columns:repeat(2,1fr)}.wpo-node-grid{grid-template-columns:1fr}.wpo-node-card-meta{flex-direction:column}}
'''
    js=r'''(()=>{const path=__PATH__,csrf=__CSRF__,add=document.getElementById('wpoAddNode'),dlg=document.getElementById('wpoAddNodeDialog'),renameDlg=document.getElementById('wpoRenameNodeDialog'),generated=document.getElementById('wpoNodeGenerated'),err=document.getElementById('wpoNodeCreateError'),tok=document.getElementById('wpoNodeToken'),cmd=document.getElementById('wpoNodeCommand');document.querySelectorAll('[data-wpo-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog')?.close()));add?.addEventListener('click',()=>{generated.hidden=true;err.hidden=true;dlg.showModal()});const gen=document.getElementById('wpoGenerateNode');gen?.addEventListener('click',async()=>{gen.disabled=true;err.hidden=true;try{const r=await fetch(path+'/node-bootstrap',{method:'POST',headers:{'X-WPP-Async':'1'},body:new URLSearchParams({csrf})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.message||'Не удалось создать ключ');tok.value=d.token;cmd.value=d.command;generated.hidden=false;gen.textContent='Создать новый ключ'}catch(e){err.textContent=e.message;err.hidden=false}finally{gen.disabled=false}});function copy(v,b){const old=b.textContent;const done=()=>{b.textContent='Скопировано';setTimeout(()=>b.textContent=old,1200)};if(navigator.clipboard?.writeText){navigator.clipboard.writeText(v).then(done).catch(()=>fallback(v,done))}else fallback(v,done)}function fallback(v,done){const t=document.createElement('textarea');t.value=v;document.body.append(t);t.select();document.execCommand('copy');t.remove();done()}document.getElementById('wpoCopyToken')?.addEventListener('click',e=>copy(tok.value,e.currentTarget));document.getElementById('wpoCopyCommand')?.addEventListener('click',e=>copy(cmd.value,e.currentTarget));document.querySelectorAll('[data-node-edit]').forEach(b=>b.addEventListener('click',()=>{const f=document.getElementById('wpoRenameNodeForm');f.elements.id.value=b.dataset.nodeEdit;f.elements.name.value=b.dataset.nodeName||'';document.getElementById('wpoRenameError').hidden=true;renameDlg.showModal()}));const form=document.getElementById('wpoRenameNodeForm');form?.addEventListener('submit',async e=>{e.preventDefault();const btn=form.querySelector('[type=submit]'),er=document.getElementById('wpoRenameError');btn.disabled=true;try{const r=await fetch(path+'/node-action',{method:'POST',headers:{'X-WPP-Async':'1'},body:new URLSearchParams(new FormData(form))});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.message||'Не удалось сохранить');renameDlg.close();location.reload()}catch(x){er.textContent=x.message;er.hidden=false}finally{btn.disabled=false}});async function refresh(){try{const r=await fetch(path+'/nodes-status',{cache:'no-store'});if(!r.ok)return;const d=await r.json();for(const n of [...(d.nodes||[]),...(d.pending||[])]){const el=document.querySelector('[data-node-status="'+CSS.escape(n.id)+'"]');if(!el){location.reload();return;}const map={online:['В сети','online'],installing:['Установка','installing'],registration:['Регистрация','registration'],offline:['Не в сети','offline'],error:['Ошибка','error']};const v=map[n.status]||map.offline;el.className='wpo-node-status '+v[1];el.querySelector('b').textContent=v[0]}for(const k in d.counts||{}){const el=document.querySelector('[data-node-count="'+k+'"]');if(el)el.textContent=d.counts[k]}}catch(e){}}refresh();setInterval(refresh,1000)})();'''
    js=js.replace('__PATH__',json.dumps(path)).replace('__CSRF__',json.dumps(csrf))
    local_country=str(local.get('country_name','Сервер'))
    return ('<section class="wpo-nodes-page"><div class="wpo-nodes-toolbar"><div><span class="eyebrow">NODE MANAGEMENT</span><h2>Серверная сеть</h2><p>Состояние серверов и управление нодами</p></div><button class="primary wpo-add-node" id="wpoAddNode" type="button">'+icon('plus')+' Добавить ноду</button></div>'
      +'<div class="wpo-node-stats">'+stats+'</div><div class="wpo-node-grid">'+''.join(cards)+''.join([] if not empty else [empty])+'</div>'
      +'<div class="wpo-node-legend"><span><i class="online"></i>В сети</span><span><i class="installing"></i>Установка</span><span><i class="registration"></i>Регистрация</span><span><i class="offline"></i>Не в сети</span><span><i class="error"></i>Ошибка</span></div></section>'
      +'<dialog id="wpoAddNodeDialog" class="wpo-node-dialog"><div class="dialog-head"><div><h2>Добавить ноду</h2><small>Установка отдельного Node Agent на чистый VPS</small></div><button type="button" data-wpo-close>×</button></div><div class="wpo-node-dialog-body"><div class="wpo-step"><i>1</i><div><b>Сгенерируйте команду</b><small>Одноразовый ключ действует 15 минут.</small></div></div><button class="primary" id="wpoGenerateNode" type="button">Сгенерировать установщик</button><div id="wpoNodeGenerated" hidden><label>Одноразовый ключ<input id="wpoNodeToken" readonly></label><button type="button" id="wpoCopyToken">Копировать ключ</button><label>Команда установки<textarea id="wpoNodeCommand" rows="3" readonly></textarea></label><button type="button" class="primary" id="wpoCopyCommand">Копировать команду</button><p class="wpo-node-hint">Запустите команду на чистом VPS от root. Установщик запросит домен ноды и email для выпуска HTTPS-сертификата. После регистрации нода появится здесь.</p></div><p id="wpoNodeCreateError" class="create-error" hidden></p></div></dialog>'
      +'<dialog id="wpoRenameNodeDialog" class="wpo-node-dialog"><div class="dialog-head"><h2>Название ноды</h2><button type="button" data-wpo-close>×</button></div><form id="wpoRenameNodeForm" class="wpo-node-dialog-body">'+hidden(csrf,operation='rename')+'<input type="hidden" name="id"><label>Название<input name="name" maxlength="80" required></label><div class="actions"><button type="button" data-wpo-close>Отмена</button><button class="primary" type="submit">Сохранить</button></div><p id="wpoRenameError" class="create-error" hidden></p></form></dialog>'
      +'<style>'+css+'</style><script>'+js+'</script>')
"""
# Replace the full old function, rather than only its signature.
ui=ui[:start]+new_nodes+ui[end:]

# User creation: preserve existing connection tiles and add selectable node tiles to subscription form.
ui=once(ui,
"def users_ui(subs, profiles, traffic, path, domain, csrf, proxy_link, openflux_profiles=None,\n             connections=None, location_label='', routing_profiles=None, direct_profile_url=None):",
"def users_ui(subs, profiles, traffic, path, domain, csrf, proxy_link, openflux_profiles=None,\n             connections=None, location_label='', routing_profiles=None, direct_profile_url=None, nodes=None, local_node=None):",
"users_ui signature")
anchor="    creation=creation.replace('<span>Протоколы подписки</span>','<span>Подключения клиента</span>',1)\n"
insert=r'''    creation=creation.replace('<span>Протоколы подписки</span>','<span>Подключения клиента</span>',1)
    targets=[]
    loc=local_node if isinstance(local_node,dict) else {}
    lc=str(loc.get('country_code','UN')).upper()
    lf=node_flag(lc)
    ln=str(loc.get('country_name') or location_label or 'Основная нода')
    targets.append(f'<label class="wpo-node-target"><input type="checkbox" name="node_local" value="1" checked><span class="wpo-node-radio"><i></i></span><span class="wpo-node-target-flag">{esc(lf)}</span><span class="wpo-node-target-copy"><strong>{esc(ln)}</strong><small>Основной сервер · локальная нода</small></span><span class="wpo-node-auto">● Авто</span></label>')
    for n in (nodes or []):
        if not isinstance(n,dict) or not re.fullmatch(r'[a-f0-9]{16}',str(n.get('id',''))): continue
        nid=str(n['id']); code=str(n.get('country_code','UN')).upper(); name=str(n.get('name') or n.get('country_name') or 'Нода')
        state=str(n.get('status','online' if n.get('enabled',True) else 'offline'))
        sl={'online':'В сети','installing':'Установка','registration':'Регистрация','offline':'Не в сети','error':'Ошибка'}.get(state,'Не в сети')
        targets.append(f'<label class="wpo-node-target"><input type="checkbox" name="node_{esc(nid)}" value="1"><span class="wpo-node-radio"><i></i></span><span class="wpo-node-target-flag">{esc(node_flag(code))}</span><span class="wpo-node-target-copy"><strong>{esc(name)}</strong><small>{esc(n.get("country_name",""))} · {esc(n.get("url",""))}</small></span><span class="wpo-node-target-status {esc(state)}">{sl}</span></label>')
    picker='<div class="wpo-node-picker"><div class="wpo-node-picker-head"><b>Ноды подписки</b><small>Можно выбрать несколько серверов или снять весь выбор.</small></div><input type="hidden" name="nodes_selector_present" value="1"><div class="wpo-node-target-list">'+''.join(targets)+'</div></div>'
    creation=creation.replace('<section class="create-step" id="subscriptionFields">','<section class="create-step" id="subscriptionFields">'+picker,1)
'''
ui=once(ui,anchor,insert,'insert node picker')
ui += '''\n\nCSS += """\n.wpo-node-picker{margin:0 0 14px;padding:13px;border:1px solid var(--line);border-radius:12px;background:color-mix(in srgb,var(--input) 55%,transparent)}.wpo-node-picker-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}.wpo-node-picker-head b{font-size:12px}.wpo-node-picker-head small{font-size:9px;color:var(--muted)}.wpo-node-target-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.wpo-node-target{position:relative;display:flex;align-items:center;gap:8px;min-width:0;min-height:58px;margin:0;padding:9px;border:1px solid var(--line);border-radius:10px;background:var(--surface);cursor:pointer}.wpo-node-target:has(input:checked){border-color:var(--accent);background:var(--tint);box-shadow:inset 0 0 0 1px var(--accent)}.wpo-node-target>input{position:absolute;opacity:0;pointer-events:none}.wpo-node-radio{display:grid;place-items:center;flex:0 0 18px;width:18px;height:18px;border:1px solid var(--muted);border-radius:50%}.wpo-node-radio i{width:8px;height:8px;border-radius:50%;background:transparent}.wpo-node-target:has(input:checked) .wpo-node-radio{border-color:var(--accent)}.wpo-node-target:has(input:checked) .wpo-node-radio i{background:var(--accent)}.wpo-node-target-flag{flex:0 0 26px;font-size:18px}.wpo-node-target-copy{display:grid;gap:3px;min-width:0;flex:1}.wpo-node-target-copy strong,.wpo-node-target-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-target-copy strong{font-size:10px}.wpo-node-target-copy small{font-size:8px;color:var(--muted)}.wpo-node-auto{font-size:8px;color:#22c55e;white-space:nowrap}.wpo-node-target-status{font-size:8px;white-space:nowrap;color:var(--muted)}.wpo-node-target-status.online{color:#22c55e}.wpo-node-target-status.installing{color:#d3a900}.wpo-node-target-status.registration{color:#38bdf8}.wpo-node-target-status.offline,.wpo-node-target-status.error{color:#ef4444}@media(max-width:650px){.wpo-node-target-list{grid-template-columns:1fr}.wpo-node-picker-head{align-items:flex-start;flex-direction:column}}\n"""\n'''

# Node display label should use editable name and retain the flag.
nodes=once(nodes,
"def location_prefix(value):\n    value = location(value)\n    icon = '🌐' if value['country_code'] == 'UN' else flag(value['country_code'])\n    return icon + ' ' + value['country_name']",
"def location_prefix(value):\n    raw = value if isinstance(value, dict) else {}\n    normalized = location(raw)\n    icon = '🌐' if normalized['country_code'] == 'UN' else flag(normalized['country_code'])\n    label = str(raw.get('name') or raw.get('display_name') or normalized['country_name']).strip()[:80]\n    return icon + ' ' + (label or normalized['country_name'])",
"node display name support")
nodes=once(nodes,
"    node['version'] = str(status.get('version', ''))[:32]\n    nodes.append(node)",
"    node['version'] = str(status.get('version', ''))[:32]\n    node['capabilities'] = [str(x)[:32] for x in status.get('capabilities', []) if isinstance(x, str)][:16]\n    node['status'] = 'online'\n    node['status_checked_at'] = int(__import__('time').time())\n    node['name'] = str(status.get('name') or loc.get('country_name') or 'Нода')[:80]\n    nodes.append(node)",
"node status metadata")

# Store selected node IDs with a subscription. Legacy subscriptions keep old all-node behaviour.
subs=once(subs,'def mutate(data, request):',
'''def clean_node_ids(value):
    if not isinstance(value,list): raise SubscriptionError('Некорректный список нод.')
    result=[]
    for item in value:
        uid=str(item or '')
        if uid!='local' and not re.fullmatch(r'[a-f0-9]{16}',uid): raise SubscriptionError('Некорректный идентификатор ноды.')
        if uid not in result: result.append(uid)
    if len(result)>17: raise SubscriptionError('Слишком много выбранных нод.')
    return result


def mutate(data, request):''','subscription helper')
subs=once(subs,
"               'connections':specs,\n               'protocols':list(dict.fromkeys(item['protocol'] for item in specs)), 'devices': [],",
"               'connections':specs, 'node_ids':clean_node_ids(request.get('node_ids',['local'])),\n               'protocols':list(dict.fromkeys(item['protocol'] for item in specs)), 'devices': [],",
"subscription node save")
subs=once(subs,
"        if operation == 'update':\n            limit = limits(request.get('max_devices', sub['max_devices']))",
"        if operation == 'update':\n            if 'node_ids' in request: sub['node_ids']=clean_node_ids(request.get('node_ids'))\n            limit = limits(request.get('max_devices', sub['max_devices']))",
"subscription update node save")

# Main app state/constants and token bootstrap.
panel=once(panel,
'LOCATION_FILE="/var/lib/tproxy-panel/location.json"\nAPI_KEY=node_api.ensure_api_key(API_KEY_FILE)',
'LOCATION_FILE="/var/lib/tproxy-panel/location.json"\nNODES_PENDING_FILE="/var/lib/tproxy-panel/nodes-pending.json"\nNODE_AGENT_INSTALLER_FILE="/opt/tproxy-panel/wpp-node-agent-install.sh"\nAPI_KEY=node_api.ensure_api_key(API_KEY_FILE)',
"pending file constants")
# Ensure shlex is available for safe one-line shell command quoting.
if '\nimport shlex\n' not in panel:
    panel=once(panel,'import shutil\n','import shutil\nimport shlex\n','shlex import')
panel=once(panel,'class Handler(BaseHTTPRequestHandler):',
'''def wpo_pending_load():
    try:
        with open(NODES_PENDING_FILE,encoding="utf-8") as stream:
            value=json.load(stream)
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError): return {}

def wpo_pending_save(value): node_api.atomic_json(NODES_PENDING_FILE,value)
def wpo_token_hash(value): return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()

class Handler(BaseHTTPRequestHandler):''','pending helpers')
# installer shell script URL is public only under the unguessable panel path.
panel=once(panel,
'        if path.startswith(SUB_PREFIX):\n            self.serve_subscription(path[len(SUB_PREFIX):]); return',
'''        if path==PANEL_PATH+"/node-agent-installer.sh":
            try:
                with open(NODE_AGENT_INSTALLER_FILE,encoding="utf-8") as stream: body=stream.read()
                body=body.replace("__WPO_CONTROLLER_ENROLL_URL__","https://"+DOMAIN+PANEL_PATH+"/node-enroll")
                body=body.replace("__WPO_CONTROLLER_STATUS_URL__","https://"+DOMAIN+PANEL_PATH+"/node-install-status")
                self.send_data(body,200,"text/x-shellscript; charset=utf-8")
            except OSError: self.send_html("Node Agent installer not found",404)
            return
        if path.startswith(SUB_PREFIX):
            self.serve_subscription(path[len(SUB_PREFIX):]); return''','serve Node installer')
# Live status endpoint; browser requests every second, network checks are cached for 5 seconds.
panel=once(panel,
'        if path==PANEL_PATH or path==PANEL_PATH+"/":\n            self.redirect("/dashboard"); return',
'''        if path==PANEL_PATH+"/nodes-status":
            now=int(time.time()); current=node_api.load_nodes(NODES_FILE); changed=False
            for node in current:
                if now-int(node.get("status_checked_at",0) or 0)<5: continue
                try:
                    state=node_api.request(node,"GET",node_api.API_PREFIX+"/status",timeout=3)
                    node["status"]="online"; node["status_detail"]="API отвечает"
                    node["version"]=str(state.get("version",node.get("version","")))[:32]
                    node["status_checked_at"]=now
                except node_api.NodeError:
                    node["status"]="offline"; node["status_detail"]="Нода не отвечает"; node["status_checked_at"]=now
                changed=True
            if changed: node_api.save_nodes(NODES_FILE,current)
            pending=wpo_pending_load(); pending_rows=[]
            for digest,item in pending.items():
                if not isinstance(item,dict) or now-int(item.get("updated_at",item.get("created_at",now)) or now)>3600: continue
                pending_rows.append({"id":"p-"+str(digest)[:12],"status":item.get("status","installing"),"domain":item.get("domain","Новая нода"),"detail":item.get("detail","")})
            statuses=["online"]+[str(n.get("status","online")) for n in current]+[str(p.get("status","installing")) for p in pending_rows]
            counts={k:statuses.count(k) for k in ("online","installing","registration","offline","error")}
            self.send_json({"nodes":[{"id":n.get("id"),"status":n.get("status","online")} for n in current],"pending":pending_rows,"counts":counts}); return
        if path==PANEL_PATH or path==PANEL_PATH+"/":
            self.redirect("/dashboard"); return''','nodes status GET')
# Public install progress + enrollment endpoints, before unauthenticated login logic.
panel=once(panel,'        # Login does not require an authenticated session.',
'''        if path==PANEL_PATH+"/node-install-status":
            try:
                payload=self.json_request(16384); digest=wpo_token_hash(payload.get("token","")); pending=wpo_pending_load(); item=pending.get(digest)
                if not isinstance(item,dict) or int(item.get("expires_at",0))<int(time.time()): self.send_json({"ok":False,"message":"Ключ установки недействителен или истёк."},403); return
                state=str(payload.get("status",""))
                if state not in ("installing","registration","error"): self.send_json({"ok":False,"message":"Недопустимый статус установки."},400); return
                item.update({"status":state,"detail":str(payload.get("detail",""))[:180],"domain":str(payload.get("domain",""))[:253],"updated_at":int(time.time())})
                wpo_pending_save(pending); self.send_json({"ok":True}); return
            except (ValueError,TypeError,json.JSONDecodeError) as exc: self.send_json({"ok":False,"message":str(exc)},400); return
        if path==PANEL_PATH+"/node-enroll":
            try:
                payload=self.json_request(32768); token=str(payload.get("token","")); digest=wpo_token_hash(token); pending=wpo_pending_load(); item=pending.get(digest)
                if not isinstance(item,dict) or int(item.get("expires_at",0))<int(time.time()): self.send_json({"ok":False,"message":"Одноразовый ключ недействителен или уже использован."},403); return
                info={"url":str(payload.get("url","")),"key":str(payload.get("api_key",""))}
                packed=node_api.CONNECTION_TOKEN_PREFIX+base64.urlsafe_b64encode(json.dumps(info,separators=(",",":")).encode()).decode().rstrip("=")
                added=node_api.add_node(NODES_FILE,{"connection_token":packed})
                registered=node_api.load_nodes(NODES_FILE); display=str(payload.get("name","")).strip()[:80] or "Нода"
                for n in registered:
                    if n.get("id")==added.get("id"):
                        n["name"]=display; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"
                node_api.save_nodes(NODES_FILE,registered); pending.pop(digest,None); wpo_pending_save(pending)
                self.send_json({"ok":True,"node_id":added.get("id")},201); return
            except (node_api.NodeError,ValueError,TypeError,json.JSONDecodeError) as exc: self.send_json({"ok":False,"message":str(exc)},400); return
            except Exception as exc:
                print("node enrollment failed:",type(exc).__name__,file=sys.stderr,flush=True); self.send_json({"ok":False,"message":"Не удалось зарегистрировать ноду."},503); return

        # Login does not require an authenticated session.''','public node enrollment')
# Authenticated bootstrap route inserted before backup restore handler.
panel=once(panel,'        if path==PANEL_PATH+"/backup-restore":',
'''        if path==PANEL_PATH+"/node-bootstrap":
            try:
                form=self.form(8192)
                if not self.valid_csrf(form): self.send_json({"ok":False,"message":"Недействительный запрос. Обновите страницу."},403); return
                token=secrets.token_urlsafe(32); now=int(time.time()); pending=wpo_pending_load()
                pending[wpo_token_hash(token)]={"created_at":now,"updated_at":now,"expires_at":now+900,"status":"installing","detail":"Ожидает запуска установщика","domain":""}
                pending={k:v for k,v in pending.items() if isinstance(v,dict) and int(v.get("updated_at",0))>now-3600}
                if len(pending)>16: pending=dict(sorted(pending.items(),key=lambda pair:int(pair[1].get("created_at",0)),reverse=True)[:16])
                wpo_pending_save(pending)
                url="https://"+DOMAIN+PANEL_PATH+"/node-agent-installer.sh"
                inner=f'curl -4fsSL "{url}" -o /tmp/wpo-node-install.sh && bash /tmp/wpo-node-install.sh "{token}"; code=$?; rm -f /tmp/wpo-node-install.sh; exit $code'
                self.send_json({"ok":True,"token":token,"command":"sudo -i bash -c "+shlex.quote(inner),"expires_in":900}); return
            except Exception as exc: self.send_json({"ok":False,"message":"Не удалось подготовить установщик: "+str(exc)[:160]},503); return

        if path==PANEL_PATH+"/backup-restore":''','node bootstrap POST')
# Node rename action
panel=once(panel,
'                elif operation=="delete":\n                    nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")',
'''                elif operation=="rename":
                    nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")
                    selected=next((n for n in nodes if n.get("id")==uid),None)
                    if selected is None: raise node_api.NodeError("Нода не найдена.")
                    selected["name"]=node_api.clean_text(form.get("name",""),"Название ноды",80)
                    node_api.save_nodes(NODES_FILE,nodes)
                    if self.headers.get("X-WPP-Async","")=="1": self.send_json({"ok":True}); return
                elif operation=="delete":
                    nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")''','node rename')
# Pass registered node metadata into users page and replace old nodes view.
panel=once(panel,
'                          routing_profiles,direct_profile_url)\n            self.send_html(layout("Клиенты",body,"users")); return',
'                          routing_profiles,direct_profile_url,\n                          [node_api.public_node(n) for n in node_api.load_nodes(NODES_FILE)],default_node_location)\n            self.send_html(layout("Клиенты",body,"users")); return','users page nodes')
panel=once(panel,
'            body=nodes_ui([node_api.public_node(n) for n in node_api.load_nodes(NODES_FILE)],\n                          node_api.load_location(LOCATION_FILE),node_api.make_connection_token(DOMAIN,API_KEY),PANEL_PATH,self.csrf())',
'''            now=int(time.time()); pending=wpo_pending_load()
            pending_rows=[{"id":"p-"+str(k)[:12],"status":v.get("status","installing"),"domain":v.get("domain","Новая нода"),"detail":v.get("detail","")} for k,v in pending.items() if isinstance(v,dict) and now-int(v.get("updated_at",v.get("created_at",now)) or now)<=3600]
            body=nodes_ui([node_api.public_node(n) for n in node_api.load_nodes(NODES_FILE)],node_api.load_location(LOCATION_FILE),"",PANEL_PATH,self.csrf(),pending_rows)''','nodes page wizard')
# selected node ids helper before traffic helper
panel=once(panel,'def traffic():',
'''def selected_node_ids(form):
    if form.get("nodes_selector_present")!="1": return ["local"]
    allowed={"local"}; allowed.update(str(n.get("id","")) for n in node_api.load_nodes(NODES_FILE))
    selected=[]
    for key,value in form.items():
        if value!="1": continue
        if key=="node_local": selected.append("local")
        elif key.startswith("node_") and key[5:] in allowed: selected.append(key[5:])
    return list(dict.fromkeys(selected))

def traffic():''','node ids form helper')
# Subscription create stores exact selection; do not pretend initial registration agent supports traffic plane yet.
panel=once(panel,
'                result=ctl_subscription({"operation":"create","name":name,"max_devices":form.get("max_devices","0"),\n                                         "connections":connection_specs})',
'''                chosen_nodes=selected_node_ids(form)
                if not chosen_nodes: create_error("Выберите хотя бы одну ноду для подписки."); return
                registered=node_api.load_nodes(NODES_FILE)
                unsupported=[n for n in registered if n.get("id") in chosen_nodes and isinstance(n.get("capabilities"),list) and n.get("capabilities") and "federation" not in n.get("capabilities",[])]
                if unsupported:
                    create_error("Нода зарегистрирована, но установка VPN-служб и выпуск профилей на ней — следующий этап тестирования. Подписка не создана.",409); return
                result=ctl_subscription({"operation":"create","name":name,"max_devices":form.get("max_devices","0"),
                                         "connections":connection_specs,"node_ids":chosen_nodes})''','create subscription nodes')
# Filter local and remote nodes on subscription feed for subscriptions carrying node_ids.
panel=once(panel,
'            lines=[proxy_link(u["protocol"],u["secret"],u["backend_port"],local_name,u.get("username","")) for u in result["users"]]\n            if result["users"]:',
'''            selected_nodes=subscription.get("node_ids")
            has_selection=isinstance(selected_nodes,list)
            local_selected=(not has_selection or "local" in selected_nodes)
            lines=[proxy_link(u["protocol"],u["secret"],u["backend_port"],local_name,u.get("username","")) for u in result["users"]] if local_selected else []
            if result["users"]:''','local subscription selection')
panel=once(panel,
'                for node in node_api.load_nodes(NODES_FILE):\n                    if not node.get("enabled",True): continue\n                    try:',
'''                for node in node_api.load_nodes(NODES_FILE):
                    if not node.get("enabled",True): continue
                    if has_selection and node.get("id") not in selected_nodes: continue
                    capabilities=node.get("capabilities")
                    if isinstance(capabilities,list) and capabilities and "federation" not in capabilities: continue
                    try:''','remote subscription selection')
panel=once(panel,
'            local_count=len(result["users"])',
'            local_count=len(result["users"]) if local_selected else 0',
'route output alignment for remote-only subscriptions')


# Node Agent installation script embedded locally and served by the panel.
agent=r'''#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
TOKEN="${1:-}"
[[ "$TOKEN" =~ ^[A-Za-z0-9_-]{40,60}$ ]] || { echo 'Одноразовый ключ не передан.'; exit 2; }
ENROLL_URL="__WPO_CONTROLLER_ENROLL_URL__"; STATUS_URL="__WPO_CONTROLLER_STATUS_URL__"
DOMAIN=""; EMAIL=""; API_KEY=""
report(){ python3 - "$TOKEN" "$1" "$2" "${3:-$DOMAIN}" <<'PY_STATUS' | curl -fsS --max-time 8 -H 'Content-Type: application/json' --data-binary @- "$STATUS_URL" >/dev/null 2>&1 || true
import json,sys
print(json.dumps({'token':sys.argv[1],'status':sys.argv[2],'detail':sys.argv[3],'domain':sys.argv[4]}))
PY_STATUS
}
fail(){ rc=$?; trap - ERR; report error "Установщик завершился с ошибкой (код $rc)."; echo "Установка завершилась с ошибкой ($rc)."; exit "$rc"; }
trap fail ERR
report installing 'Проверка VPS и домена.'
echo '=== WEB PANEL ONLINE — Node Agent ==='
read -r -p 'Домен ноды (например, de.example.com): ' DOMAIN
DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN%%/*}"; DOMAIN="${DOMAIN,,}"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || { report error 'Некорректный домен.'; echo 'Некорректный домен.'; exit 2; }
read -r -p "Email для Let's Encrypt: " EMAIL
[[ "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || { report error 'Некорректный email.'; echo 'Некорректный email.'; exit 2; }
. /etc/os-release
case "${ID:-}" in ubuntu) dpkg --compare-versions "${VERSION_ID:-0}" ge 22.04 || { echo 'Требуется Ubuntu 22.04+.'; exit 2; };; debian) dpkg --compare-versions "${VERSION_ID:-0}" ge 12 || { echo 'Требуется Debian 12+.'; exit 2; };; *) echo 'Поддерживаются Ubuntu 22.04+ и Debian 12+.'; exit 2;; esac
report installing 'Установка Caddy и выпуск HTTPS.'
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates gnupg python3
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update; apt-get install -y --no-install-recommends caddy
fi
PUBLIC_IP="$(curl -4fsS --max-time 10 https://api.ipify.org)"
getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | grep -Fxq "$PUBLIC_IP" || { report error "DNS A-запись должна указывать на $PUBLIC_IP."; echo "DNS A-запись $DOMAIN должна указывать на $PUBLIC_IP."; exit 3; }
install -d -m 0755 /opt/wpp-node-agent; install -d -m 0700 /etc/wpp-node-agent
API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 - "$DOMAIN" "$EMAIL" "$API_KEY" <<'PY_CFG'
import json,os,sys,tempfile
p='/etc/wpp-node-agent/config.json'; d={'domain':sys.argv[1],'email':sys.argv[2],'api_key':sys.argv[3],'version':'0.1.0'}
fd,t=tempfile.mkstemp(dir=os.path.dirname(p)); f=os.fdopen(fd,'w'); json.dump(d,f); f.write('\n'); f.close(); os.chmod(t,0o600); os.replace(t,p)
PY_CFG
cat > /opt/wpp-node-agent/agent.py <<'PY_AGENT'
#!/usr/bin/env python3
import json,hmac,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
C=json.load(open('/etc/wpp-node-agent/config.json')); KEY=C['api_key']; DOMAIN=C['domain']
def location():
 try:
  with urllib.request.urlopen('https://ipapi.co/json/',timeout=4) as r: d=json.loads(r.read(65536))
  code=str(d.get('country_code','UN')).upper(); code=code if len(code)==2 else 'UN'
  return {'country_code':code,'country_name':str(d.get('country_name') or 'Сервер')[:80],'name':str(d.get('country_name') or 'Сервер')[:80]}
 except Exception: return {'country_code':'UN','country_name':'Сервер','name':'Сервер'}
class H(BaseHTTPRequestHandler):
 def log_message(self,*a): pass
 def out(self,d,code=200):
  b=json.dumps(d).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
 def auth(self):
  h=self.headers.get('Authorization',''); return h.startswith('Bearer ') and hmac.compare_digest(h[7:].strip(),KEY)
 def do_GET(self):
  if self.path=='/healthz': self.out({'ok':True}); return
  if not self.auth(): self.out({'ok':False,'message':'Unauthorized'},401); return
  if self.path=='/wpp-api/v1/status': self.out({'ok':True,'api_version':1,'version':C['version'],'domain':DOMAIN,'location':location(),'name':DOMAIN.split('.')[0],'capabilities':['node-agent']}); return
  if self.path=='/wpp-api/v1/profiles': self.out({'ok':True,'profiles':[]}); return
  self.out({'ok':False,'message':'Not found'},404)
 def do_POST(self):
  if not self.auth(): self.out({'ok':False,'message':'Unauthorized'},401); return
  if self.path.endswith('/federation/purge'): self.out({'ok':True,'deleted':0}); return
  if self.path.endswith('/federation/delete'): self.out({'ok':True,'deleted':False}); return
  if self.path.endswith('/federation/sync'): self.out({'ok':False,'message':'VPN services are not installed in Node Agent Lab.'},501); return
  self.out({'ok':False,'message':'Not found'},404)
ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()
PY_AGENT
chmod 0755 /opt/wpp-node-agent/agent.py
cat > /etc/systemd/system/wpp-node-agent.service <<'UNIT'
[Unit]
Description=WPO lightweight Node Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
Group=root
UMask=0077
ExecStart=/usr/bin/python3 /opt/wpp-node-agent/agent.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/log
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/caddy/Caddyfile <<CADDY
${DOMAIN} {
    tls ${EMAIL}
    encode zstd gzip
    reverse_proxy 127.0.0.1:9088
}
CADDY
chmod 0644 /etc/caddy/Caddyfile
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then ufw allow 80/tcp >/dev/null || true; ufw allow 443/tcp >/dev/null || true; fi
systemctl daemon-reload; systemctl enable --now wpp-node-agent.service; systemctl enable --now caddy; systemctl reload caddy || systemctl restart caddy
report installing 'Ожидание HTTPS-сертификата.'
TLS_OK=0
for i in $(seq 1 60); do if curl -fsS --connect-timeout 3 --max-time 5 "https://${DOMAIN}/healthz" >/dev/null 2>&1; then TLS_OK=1; break; fi; sleep 5; done
[[ $TLS_OK == 1 ]] || { report error 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; echo 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; exit 4; }
report registration 'HTTPS готов. Регистрация в основной панели.'
python3 - "$ENROLL_URL" "$TOKEN" "$DOMAIN" "$API_KEY" <<'PY_ENROLL'
import json,sys,urllib.request
url,token,domain,key=sys.argv[1:]; body=json.dumps({'token':token,'url':'https://'+domain,'api_key':key,'name':domain.split('.')[0]}).encode()
r=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(r,timeout=20) as response: result=json.loads(response.read(32768))
if not result.get('ok'): raise SystemExit(result.get('message','Registration failed'))
print('Нода зарегистрирована:',result.get('node_id',''))
PY_ENROLL
trap - ERR
echo "Готово: Node Agent зарегистрирован на https://${DOMAIN}"
'''
# Save installer file into APP_DIR
agent_path=app/'wpp-node-agent-install.sh'
agent_path.write_text(agent,encoding='utf-8'); agent_path.chmod(0o700)

# Syntax validation before touching installed source files.
for name,src in [('wpp_ui.py',ui),('panel.py',panel),('wpp_nodes.py',nodes),('wpp_subscriptions.py',subs)]: compile(src,name,'exec')
# Atomic replacements after every transform and compile has succeeded.
for name,src in [('wpp_ui.py',ui),('wpp_nodes.py',nodes),('wpp_subscriptions.py',subs),('panel.py',panel)]: put(name,src)
print('Patch sources updated and Python syntax checks passed.')
PY_PATCH
then
  echo 'Patch не применён. Восстанавливаю резервные копии.'
  for f in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py; do cp -a "$BACKUP/$f" "$APP_DIR/$f"; done
  exit 1
fi
if ! python3 -m py_compile "$APP_DIR/panel.py" "$APP_DIR/wpp_ui.py" "$APP_DIR/wpp_nodes.py" "$APP_DIR/wpp_subscriptions.py"; then
  echo 'Ошибка компиляции. Откат.'
  for f in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py; do cp -a "$BACKUP/$f" "$APP_DIR/$f"; done
  rm -f "$APP_DIR/wpp-node-agent-install.sh"
  exit 1
fi
chown root:root "$APP_DIR/panel.py" "$APP_DIR/wpp_ui.py" "$APP_DIR/wpp_nodes.py" "$APP_DIR/wpp_subscriptions.py" "$APP_DIR/wpp-node-agent-install.sh"
chmod 0644 "$APP_DIR/panel.py" "$APP_DIR/wpp_ui.py" "$APP_DIR/wpp_nodes.py" "$APP_DIR/wpp_subscriptions.py"
chmod 0700 "$APP_DIR/wpp-node-agent-install.sh"
if ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  echo 'Панель не стартовала. Откатываю исходные файлы.'
  for f in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py; do cp -a "$BACKUP/$f" "$APP_DIR/$f"; done
  rm -f "$APP_DIR/wpp-node-agent-install.sh"
  systemctl restart "$SERVICE" || true
  exit 1
fi
echo
echo 'WPO Nodes Lab установлен локально.'
echo "Резервная копия: $BACKUP"
echo 'GitHub не изменялся.'
echo 'Открой раздел «Ноды» → «Добавить ноду».'
echo 'ВАЖНО: эта версия проверяет агент, HTTPS, регистрацию и статусы. VPN-профили на отдельном Node Agent пока не создаются; выбор таких нод в подписке пока блокируется с понятным сообщением.'