#!/usr/bin/env bash
# WEB PANEL ONLINE 3.0 — consolidated node-install.sh (all 26 validated patch steps in one source).
set -Eeuo pipefail
umask 077

REF="9fb7260fd7fa0b6c9d0490052d2a62e2df63f8c1"
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF"
PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Complete first-install bundles already contain all the Nodes Lab source files.
USE_PACKAGE=0
if [[ "${WPO_NODES_LOCAL_SOURCE:-0}" == 1 ]] &&
   [[ -s "$PACKAGE_DIR/install-final.sh" &&
      -s "$PACKAGE_DIR/node-install.sh" &&
      -s "$PACKAGE_DIR/wpo-node-agent-install-v2.sh" ]]; then
    USE_PACKAGE=1
    echo 'Nodes Lab: повторная загрузка файлов не нужна.'
fi
APP="/opt/tproxy-panel"
SERVICE="tproxy-panel.service"
DATA="/var/lib/tproxy-panel"
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
AGENT="$APP/wpp-node-agent-install.sh"
GEO="$APP/wpo_node_geo.py"
AUTO="$APP/wpo_node_autotemplate.py"
NODE="$APP/wpp_nodes.py"
SUB="$APP/wpp_subscriptions.py"

die(){ echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die 'Запустите от root на основном VPS WPO.'
command -v curl >/dev/null || die 'Требуется curl.'
command -v python3 >/dev/null || die 'Требуется python3.'
for file in "$PANEL" "$UI" "$NODE" "$SUB"; do
    [[ -s "$file" ]] || die "Сначала установите оригинальную WPO 3.0: отсутствует $file"
done
systemctl cat "$SERVICE" >/dev/null 2>&1 || die "Не найдена служба $SERVICE."
install -d -m 0700 "$DATA"

STAGE="$(mktemp -d /tmp/wpo-nodes-release.XXXXXXXX)"
BACKUP=""
TOUCHED=0
cleanup(){
    local rc=$?
    trap - EXIT
    if (( rc != 0 && TOUCHED == 1 )); then
        echo "Ошибка ($rc): возвращаю исходные файлы контроллера..." >&2
        for name in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py wpp-node-agent-install.sh wpo_node_geo.py wpo_node_autotemplate.py; do
            if [[ -f "$BACKUP/$name" ]]; then
                cp -a "$BACKUP/$name" "$APP/$name" || true
            elif [[ -f "$BACKUP/absent-$name" ]]; then
                rm -f "$APP/$name" || true
            fi
        done
        systemctl reset-failed "$SERVICE" 2>/dev/null || true
        systemctl restart "$SERVICE" || true
        echo "Код восстановлен из $BACKUP. Данные пользователей и нод не удалены." >&2
    fi
    rm -rf "$STAGE"
    exit "$rc"
}
trap cleanup EXIT

# Embedded legacy step payloads, frozen at current main.
# These are extracted locally, syntax-checked before any controller changes,
# and applied with a single final service restart on clean installations.
cat > "$STAGE/wpo-nodes-lab-install.sh" <<'__WPO_EMBED_V1_END_736a4b__'
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
start=ui.index('def nodes_ui('); end=ui.index('\n\nCSS +=',start)
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
        cap='VLESS XHTTP · Hysteria2' if 'federation' in caps else 'Node Agent · VPN не установлена'
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
.wpo-nodes-page{display:grid;gap:15px}.wpo-nodes-toolbar{display:flex;align-items:center;justify-content:space-between;gap:15px}.wpo-nodes-toolbar h2{font-size:21px;margin:4px 0}.wpo-nodes-toolbar p{margin:0;color:var(--muted);font-size:11px}.wpo-add-node{display:flex;align-items:center;gap:8px;min-height:42px;padding:10px 16px;white-space:nowrap}.wpo-node-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.wpo-node-stat{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px;border:1px solid var(--line);border-radius:11px;background:var(--surface)}.wpo-node-stat span{font-size:10px;color:var(--muted)}.wpo-node-stat strong{font:600 21px ui-monospace,monospace}.wpo-node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,340px));gap:9px;align-items:start}.wpo-node-card{margin:0;padding:11px;width:100%;max-width:340px;box-sizing:border-box;border:1px solid color-mix(in srgb,var(--accent) 12%,var(--line));border-radius:13px;background:linear-gradient(145deg,color-mix(in srgb,var(--surface) 98%,var(--accent)),var(--surface))}.wpo-node-card-top{display:flex;align-items:center;gap:10px;min-width:0}.wpo-node-flag{display:grid;place-items:center;flex:0 0 34px;height:34px;border:1px solid var(--line);border-radius:9px;background:var(--input);font-size:18px}.wpo-node-card-title{display:grid;gap:4px;min-width:0;flex:1}.wpo-node-card-title strong{font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-card-title small{font-size:9px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-status{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;padding:4px 7px;border:1px solid var(--line);border-radius:20px;font-size:8px;white-space:nowrap}.wpo-node-status i,.wpo-node-legend i{width:7px;height:7px;border-radius:50%;background:#ef4444}.wpo-node-status.online i,.wpo-node-legend .online{background:#22c55e;box-shadow:0 0 0 4px #22c55218}.wpo-node-status.installing i,.wpo-node-legend .installing{background:#eab308}.wpo-node-status.registration i,.wpo-node-legend .registration{background:#38bdf8}.wpo-node-status.offline i,.wpo-node-status.error i,.wpo-node-legend .offline,.wpo-node-legend .error{background:#ef4444}.wpo-node-card-meta{display:flex;justify-content:space-between;gap:8px;margin-top:8px;padding-top:7px;border-top:1px solid var(--line);font-size:8px;color:var(--muted)}.wpo-node-card-actions{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:5px}.wpo-node-card-actions form{margin:0}.wpo-pending-node{border-style:dashed}.wpo-node-empty{grid-column:1/-1;display:grid;justify-items:center;gap:7px;padding:32px;border:1px dashed var(--line);border-radius:12px;text-align:center}.wpo-node-empty small{color:var(--muted);font-size:10px}.wpo-node-legend{display:flex;flex-wrap:wrap;gap:13px;color:var(--muted);font-size:9px}.wpo-node-legend span{display:flex;align-items:center;gap:6px}.wpo-node-dialog{width:min(550px,calc(100vw - 24px));padding:0;border:1px solid var(--line);border-radius:16px;background:var(--surface);color:var(--text)}.wpo-node-dialog .dialog-head{display:flex;align-items:center;justify-content:space-between;padding:17px 19px;border-bottom:1px solid var(--line)}.wpo-node-dialog .dialog-head h2{font-size:16px;margin:0}.wpo-node-dialog .dialog-head small{display:block;margin-top:4px;color:var(--muted);font-size:10px}.wpo-node-dialog-body{display:grid;gap:10px;padding:18px}.wpo-node-dialog-body label{display:grid;gap:6px;font-size:10px;color:var(--muted)}.wpo-node-dialog-body input,.wpo-node-dialog-body textarea{width:100%;font:10px ui-monospace,monospace}.wpo-step{display:flex;align-items:center;gap:10px}.wpo-step i{display:grid;place-items:center;width:25px;height:25px;border:1px solid var(--line);border-radius:50%;font-style:normal;color:var(--accent)}.wpo-step b,.wpo-step small{display:block}.wpo-step b{font-size:12px}.wpo-step small{margin-top:3px;color:var(--muted);font-size:9px}.wpo-copy-field{display:grid;grid-template-columns:1fr auto;gap:7px}.wpo-node-hint{margin:3px 0 0;padding:11px;border:1px solid var(--line);border-radius:9px;background:var(--input);font-size:10px;line-height:1.5;color:var(--muted)}@media(max-width:850px){.wpo-node-stats{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){.wpo-nodes-toolbar{align-items:stretch;flex-direction:column}.wpo-add-node{justify-content:center;width:100%}.wpo-node-stats{grid-template-columns:repeat(2,1fr)}.wpo-node-grid{grid-template-columns:1fr}.wpo-node-card-meta{flex-direction:column}}
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
# Allow correction without reinstalling; trim accidental paste artifacts at the edges.
for EMAIL_ATTEMPT in 1 2 3; do
  IFS= read -r -p "Email для Let's Encrypt: " EMAIL
  EMAIL="$(python3 - "$EMAIL" <<'PY_EMAIL_TRIM'
import sys
print(sys.argv[1].strip(' \t\r\n\ufeff\u200b\u2060'))
PY_EMAIL_TRIM
)"
  if python3 - "$EMAIL" <<'PY_VALIDATE_EMAIL'
import re
import sys

value = sys.argv[1]
local, sep, host = value.partition("@")
local_ok = (
    1 <= len(local) <= 64
    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*", local) is not None
    and not local.endswith(".")
    and ".." not in local
)
host_ok = re.fullmatch(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}",
    host,
) is not None
valid = value.isascii() and len(value) <= 254 and bool(sep) and local_ok and host_ok
if not valid:
    invalid = sorted({f"U+{ord(ch):04X}" for ch in value if ord(ch) > 127 or ord(ch) < 32})
    if invalid:
        print("Найдены посторонние символы: " + ", ".join(invalid), file=sys.stderr)
sys.exit(0 if valid else 1)
PY_VALIDATE_EMAIL
  then
    break
  fi
  echo 'Некорректный email. Наберите адрес вручную английскими буквами, например name@example.com.'
  if [[ "$EMAIL_ATTEMPT" == "3" ]]; then
    report error 'Некорректный email после трёх попыток.'
    echo 'Установка остановлена: неверный email.'
    exit 2
  fi
done
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
__WPO_EMBED_V1_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v2-install.sh" <<'__WPO_EMBED_V2_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR=/opt/tproxy-panel
DATA_DIR=/var/lib/tproxy-panel
SERVICE=tproxy-panel.service
UI="$APP_DIR/wpp_ui.py"
PANEL="$APP_DIR/panel.py"
AGENT="$APP_DIR/wpp-node-agent-install.sh"
[[ $EUID -eq 0 ]] || { echo 'Запустите установщик от root.'; exit 1; }
for file in "$UI" "$PANEL"; do [[ -s "$file" ]] || { echo "Файл не найден: $file"; exit 1; }; done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'def wpo_pending_load' "$PANEL" || { echo 'Сначала установите Nodes Lab. Обновление не применено.'; exit 1; }
grep -q 'def nodes_ui(' "$UI" || { echo 'Разметка нод не найдена.'; exit 1; }
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$DATA_DIR/nodes-lab-v2-backup-$STAMP"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"
cp -a "$PANEL" "$BACKUP/panel.py"
if [[ -f "$AGENT" ]]; then cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"; fi
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 20 "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh" -o "$TMP"
[[ -s "$TMP" ]] && grep -q 'site-template' "$TMP" || { echo 'Не удалось получить Node Agent v2.'; exit 1; }
export WPO_APP_DIR="$APP_DIR"
if ! python3 - <<'PY_PATCH'
import os
from pathlib import Path
app=Path(os.environ["WPO_APP_DIR"])
ui_path=app/"wpp_ui.py"
panel_path=app/"panel.py"
ui=ui_path.read_text(encoding="utf-8")
panel=panel_path.read_text(encoding="utf-8")
def replace_once(source,old,new,label):
    n=source.count(old)
    if n!=1: raise RuntimeError("%s: найдено %s совпадений, требуется 1."%(label,n))
    return source.replace(old,new,1)
start=ui.index("def nodes_ui(")
end=ui.index("\n\nCSS +=",start)
new_nodes=r"""def nodes_ui(nodes, local, connection_token, path, csrf, pending_nodes=None, presets=None):
    nodes=nodes if isinstance(nodes,list) else []
    local=local if isinstance(local,dict) else {}
    pending_nodes=pending_nodes if isinstance(pending_nodes,list) else []
    presets=presets if isinstance(presets,list) else []
    labels={'online':('В сети','online'),'installing':('Установка','installing'),'registration':('Регистрация','registration'),'offline':('Не в сети','offline'),'error':('Ошибка','error')}
    def status(uid,state):
        title,cls=labels.get(state,labels['offline'])
        return f'<span class="wpo-node-status {cls}" data-node-status="{esc(uid)}"><i></i><b>{title}</b></span>'
    counts={key:0 for key in labels}
    cards=[]
    lc=str(local.get('country_code','UN')).upper()
    lname=str(local.get('country_name','Основная нода'))
    counts['online']+=1
    cards.append(f'''<article class="card wpo-node-card">
      <div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span>{status("local","online")}</div>
      <div class="wpo-node-card-body"><small class="wpo-node-eyebrow">ОСНОВНАЯ НОДА</small><h3>{esc(lname)}</h3><a class="wpo-node-domain" href="https://{esc(connection_token)}" target="_blank" rel="noopener noreferrer">{icon("link")}<span>{esc(connection_token)}</span></a></div>
      <div class="wpo-node-card-bottom"><span>Локальный сервер</span><span class="muted">Основная</span></div>
      </article>''')
    for n in nodes:
        uid=str(n.get('id',''))
        state=str(n.get('status','online' if n.get('enabled',True) else 'offline'))
        if state not in counts: state='offline'
        counts[state]+=1
        name=str(n.get('name') or n.get('country_name') or 'Нода')
        country=str(n.get('country_name') or 'Страна не определена')
        code=str(n.get('country_code','UN')).upper()
        url=str(n.get('url',''))
        hostname=url.removeprefix('https://')
        caps=n.get('capabilities') if isinstance(n.get('capabilities'),list) else []
        cap='VLESS · Hysteria2' if 'federation' in caps else 'Node Agent'
        site_id=str(n.get('site_template_id',''))
        site_name=next((str(p.get('name','')) for p in presets if p.get('id')==site_id),'Сайт не выбран') if site_id else 'Сайт не выбран'
        edit=f'<button class="icon-btn wpo-node-icon" type="button" data-node-edit="{esc(uid)}" data-node-name="{esc(name)}" data-node-template="{esc(site_id)}" title="Редактировать ноду" aria-label="Редактировать ноду">{icon("edit")}</button>'
        delete=f'<form method="post" action="{esc(path)}/node-action" data-confirm="Удалить ноду «{esc(name)}» из панели?"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="operation" value="delete"><input type="hidden" name="id" value="{esc(uid)}"><button class="icon-btn wpo-node-icon danger" type="submit" title="Удалить ноду" aria-label="Удалить ноду">{icon("trash")}</button></form>'
        cards.append(f'''<article class="card wpo-node-card">
          <div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span>{status(uid,state)}</div>
          <div class="wpo-node-card-body"><small class="wpo-node-eyebrow">{esc(country)}</small><h3 title="{esc(name)}">{esc(name)}</h3><a class="wpo-node-domain" href="{esc(url)}" target="_blank" rel="noopener noreferrer" title="Открыть сайт ноды">{icon('link')}<span>{esc(hostname)}</span></a>
          <p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p></div>
          <div class="wpo-node-card-bottom"><span>Агент {esc(n.get("version","—"))}</span><div class="wpo-node-actions">{edit}{delete}</div></div>
          </article>''')
    for p in pending_nodes:
        uid=str(p.get('id',''))
        state=str(p.get('status','installing'))
        if state not in counts: state='error'
        counts[state]+=1
        domain=str(p.get('domain') or '')
        detail=str(p.get('detail') or 'Установщик не запущен')
        delete=f'<form method="post" action="{esc(path)}/node-action" data-confirm="Удалить незавершённую установку? Ключ установки будет отозван."><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="operation" value="pending-delete"><input type="hidden" name="id" value="{esc(uid)}"><button class="icon-btn wpo-node-icon danger" title="Удалить установку" aria-label="Удалить установку">{icon("trash")}</button></form>'
        cards.append(f'''<article class="card wpo-node-card wpo-pending-node">
          <div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span>{status(uid,state)}</div>
          <div class="wpo-node-card-body"><small class="wpo-node-eyebrow">ПОДКЛЮЧЕНИЕ НОДЫ</small><h3>Установка</h3><div class="wpo-node-domain">{icon("link")}<span>{esc(domain or "Домен определяется")}</span></div><p class="wpo-node-template">{esc(detail)}</p></div>
          <div class="wpo-node-card-bottom"><span>Одноразовый установщик</span><div class="wpo-node-actions">{delete}</div></div></article>''')
    stats=''.join(f'<div class="wpo-node-stat"><span>{title}</span><strong data-node-count="{key}">{counts[key]}</strong></div>' for key,title in [('online','В сети'),('installing','Установка'),('registration','Регистрация'),('offline','Не в сети'),('error','Ошибка')])
    empty='' if nodes or pending_nodes else '<div class="wpo-node-empty"><b>Дополнительных нод пока нет</b><small>Добавьте ноду, чтобы подключить отдельный VPS.</small></div>'
    options='<option value="">Стандартная страница ноды</option>'+''.join(f'<option value="{esc(p.get("id",""))}">{esc(p.get("name",""))}</option>' for p in presets if p.get('id') and p.get('name'))
    css='''
.wpo-nodes-page{display:grid;gap:16px}.wpo-nodes-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px}.wpo-nodes-toolbar h2{font-size:21px;margin:4px 0}.wpo-nodes-toolbar p{margin:0;color:var(--muted);font-size:12px}.wpo-add-node{gap:8px;min-height:41px}
.wpo-node-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.wpo-node-stat{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px;border:1px solid var(--line);border-radius:11px;background:var(--surface)}.wpo-node-stat span{font-size:11px;color:var(--muted)}.wpo-node-stat strong{font:600 21px ui-monospace,monospace}
.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,320px));gap:14px;align-items:start;justify-content:start}
.wpo-nodes-page .wpo-node-card{display:flex;flex-direction:column;justify-content:space-between;aspect-ratio:1/1;min-width:0;min-height:298px;margin:0;padding:18px;border:1px solid var(--line);border-radius:15px;background:linear-gradient(155deg,color-mix(in srgb,var(--surface) 95%,var(--accent)),var(--surface));box-sizing:border-box;transition:border-color .18s ease,box-shadow .18s ease,transform .18s ease}
.wpo-nodes-page .wpo-node-card:hover{border-color:color-mix(in srgb,var(--accent) 34%,var(--line));box-shadow:0 9px 22px #0002}
.wpo-node-card-head,.wpo-node-card-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}.wpo-node-flag{display:grid;place-items:center;flex:0 0 48px;width:48px;height:48px;border:1px solid var(--line);border-radius:12px;background:var(--input);font-size:25px}
.wpo-node-status{display:inline-flex;align-items:center;gap:6px;padding:6px 9px;border:1px solid var(--line);border-radius:16px;font-size:10px;white-space:nowrap}.wpo-node-status i,.wpo-node-legend i{display:inline-block;width:7px;height:7px;border-radius:50%;background:#ef4444}.wpo-node-status.online i,.wpo-node-legend .online{background:#22c55e;box-shadow:0 0 0 4px #22c55218}.wpo-node-status.installing i,.wpo-node-legend .installing{background:#eab308}.wpo-node-status.registration i,.wpo-node-legend .registration{background:#38bdf8}.wpo-node-status.offline i,.wpo-node-status.error i,.wpo-node-legend .offline,.wpo-node-legend .error{background:#ef4444}
.wpo-node-card-body{display:grid;gap:9px;min-width:0;align-content:center;flex:1;padding:12px 0}.wpo-node-card-body h3{font-size:18px;font-weight:650;margin:0;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-eyebrow{font-size:10px;letter-spacing:.07em;color:var(--muted);text-transform:uppercase}
.wpo-node-domain{display:flex;align-items:center;gap:8px;min-width:0;padding:10px 11px;background:var(--input);border:1px solid var(--line);border-radius:9px;text-decoration:none;color:var(--accent);font:500 12px ui-monospace,monospace}.wpo-node-domain .ico{width:15px;height:15px;flex-shrink:0}.wpo-node-domain span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-domain:hover{border-color:var(--accent)}
.wpo-node-template{font-size:11px;color:var(--muted);margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.wpo-node-template .ico{vertical-align:middle;width:13px;height:13px}
.wpo-node-card-bottom{padding-top:10px;border-top:1px solid var(--line);min-height:38px;font-size:10px;color:var(--muted)}.wpo-node-actions{display:flex;align-items:center;gap:5px}.wpo-node-actions form{margin:0}
.wpo-nodes-page .wpo-node-icon{height:34px;width:34px;padding:6px;background:transparent;color:var(--muted);border:1px solid transparent;border-radius:8px}.wpo-nodes-page .wpo-node-icon:hover{background:var(--tint);color:var(--accent);border-color:var(--accent)}.wpo-nodes-page .wpo-node-icon.danger:hover{color:var(--red);border-color:var(--red)}
.wpo-nodes-page button{transition:background .16s ease,color .16s ease,border-color .16s ease,filter .16s ease,transform .16s ease}.wpo-nodes-page button:hover{filter:brightness(1.08);transform:translateY(-1px)}.wpo-nodes-page button:active{transform:translateY(0) scale(.98)}.wpo-nodes-page button.primary:hover{background:var(--accent)}
.wpo-pending-node{border-style:dashed!important}.wpo-node-empty{grid-column:1/-1;display:grid;justify-items:center;gap:7px;padding:32px;border:1px dashed var(--line);border-radius:12px;text-align:center}.wpo-node-empty small{color:var(--muted);font-size:11px}.wpo-node-legend{display:flex;flex-wrap:wrap;gap:13px;color:var(--muted);font-size:10px}.wpo-node-legend span{display:flex;align-items:center;gap:6px}
.wpo-node-dialog{width:min(550px,calc(100vw - 28px));max-height:88dvh;overflow:auto;padding:0;border:1px solid var(--line);border-radius:16px;background:var(--surface);color:var(--text)}.wpo-node-dialog::backdrop{background:#0009}.wpo-node-dialog .dialog-head{display:flex;align-items:center;justify-content:space-between;padding:16px 19px;border-bottom:1px solid var(--line)}.wpo-node-dialog .dialog-head h2{font-size:17px;margin:0}.wpo-node-dialog .dialog-head small{display:block;margin-top:4px;color:var(--muted);font-size:11px}.wpo-node-dialog-body{display:grid;gap:12px;padding:18px}.wpo-node-dialog-body label{display:grid;gap:6px;margin:0;font-size:12px;color:var(--muted)}.wpo-node-dialog-body input,.wpo-node-dialog-body textarea,.wpo-node-dialog-body select{width:100%;font-size:12px}.wpo-node-dialog-body textarea{font:11px/1.5 ui-monospace,monospace;resize:vertical}.wpo-step{display:flex;gap:10px;align-items:center}.wpo-step i{display:grid;place-items:center;flex:0 0 28px;height:28px;border:1px solid var(--line);border-radius:50%;font-style:normal;color:var(--accent)}.wpo-step b{font-size:13px}.wpo-step small{display:block;margin-top:3px;color:var(--muted);font-size:11px}.wpo-node-hint{padding:11px;border:1px solid var(--line);border-radius:9px;background:var(--input);font-size:11px;line-height:1.5;color:var(--muted);margin:0}.wpo-node-generated{display:grid;gap:10px}.wpo-node-generated[hidden]{display:none!important}
@media(max-width:850px){.wpo-node-stats{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.wpo-nodes-toolbar{align-items:stretch;flex-direction:column}.wpo-add-node{width:100%;justify-content:center}.wpo-node-stats{grid-template-columns:repeat(2,1fr)}.wpo-node-grid{grid-template-columns:minmax(0,340px)}.wpo-nodes-page .wpo-node-card{min-height:298px}.wpo-node-legend{gap:9px}}
'''
    js=r'''(()=>{const path=__PATH__,csrf=__CSRF__,add=document.getElementById('wpoAddNode'),dlg=document.getElementById('wpoAddNodeDialog'),editDlg=document.getElementById('wpoEditNodeDialog'),generated=document.getElementById('wpoNodeGenerated'),err=document.getElementById('wpoNodeCreateError'),tok=document.getElementById('wpoNodeToken'),cmd=document.getElementById('wpoNodeCommand');
document.querySelectorAll('[data-wpo-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog')?.close()));
add?.addEventListener('click',()=>{err.hidden=true;if(!dlg.open)dlg.showModal()});
const gen=document.getElementById('wpoGenerateNode');
gen?.addEventListener('click',async()=>{gen.disabled=true;err.hidden=true;try{const r=await fetch(path+'/node-bootstrap',{method:'POST',headers:{'X-WPP-Async':'1'},body:new URLSearchParams({csrf})});if(r.redirected)throw new Error('Сессия завершена. Обновите страницу.');const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.message||'Не удалось создать ключ');tok.value=d.token;cmd.value=d.command;generated.hidden=false;gen.textContent='Сгенерировать новый ключ'}catch(e){err.textContent=e.message;err.hidden=false}finally{gen.disabled=false}});
function copy(value,button){navigator.clipboard.writeText(value).then(()=>{const old=button.textContent;button.textContent='Скопировано ✓';setTimeout(()=>button.textContent=old,1400)}).catch(()=>{const ta=document.createElement('textarea');ta.value=value;document.body.append(ta);ta.select();document.execCommand('copy');ta.remove();button.textContent='Скопировано ✓'})}
document.getElementById('wpoCopyToken')?.addEventListener('click',e=>copy(tok.value,e.currentTarget));
document.getElementById('wpoCopyCommand')?.addEventListener('click',e=>copy(cmd.value,e.currentTarget));
document.querySelectorAll('[data-node-edit]').forEach(b=>b.addEventListener('click',()=>{const f=document.getElementById('wpoEditNodeForm');f.elements.id.value=b.dataset.nodeEdit;f.elements.name.value=b.dataset.nodeName||'';f.elements.site_template.value=b.dataset.nodeTemplate||'';document.getElementById('wpoEditNodeError').hidden=true;if(!editDlg.open)editDlg.showModal()}));
const f=document.getElementById('wpoEditNodeForm');
f?.addEventListener('submit',async e=>{e.preventDefault();const button=f.querySelector('[type=submit]'),error=document.getElementById('wpoEditNodeError');button.disabled=true;error.hidden=true;try{const r=await fetch(path+'/node-action',{method:'POST',headers:{'X-WPP-Async':'1'},body:new URLSearchParams(new FormData(f))});if(r.redirected)throw new Error('Сессия завершена. Обновите страницу.');const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.message||'Не удалось сохранить ноду');editDlg.close();location.reload()}catch(x){error.textContent=x.message;error.hidden=false}finally{button.disabled=false}});
let polling=false;
async function refresh(){if(polling||document.querySelector('dialog:modal'))return;polling=true;try{const r=await fetch(path+'/nodes-status',{cache:'no-store'});if(!r.ok||document.querySelector('dialog:modal'))return;const d=await r.json();if(document.querySelector('dialog:modal'))return;const ids=new Set([...(d.nodes||[]),...(d.pending||[])].map(x=>x.id));for(const n of [...(d.nodes||[]),...(d.pending||[])]){const el=document.querySelector('[data-node-status="'+CSS.escape(n.id)+'"]');if(!el){location.reload();return}const map={online:['В сети','online'],installing:['Установка','installing'],registration:['Регистрация','registration'],offline:['Не в сети','offline'],error:['Ошибка','error']};const state=map[n.status]||map.offline;el.className='wpo-node-status '+state[1];el.querySelector('b').textContent=state[0]}for(const el of document.querySelectorAll('[data-node-status]')){if(el.dataset.nodeStatus!=='local'&&!ids.has(el.dataset.nodeStatus)){location.reload();return}}for(const key in d.counts||{}){const el=document.querySelector('[data-node-count="'+key+'"]');if(el)el.textContent=d.counts[key]}}catch(e){}finally{polling=false}}
setInterval(refresh,1000)})();'''
    js=js.replace('__PATH__',json.dumps(path)).replace('__CSRF__',json.dumps(csrf))
    return ('<section class="wpo-nodes-page"><div class="wpo-nodes-toolbar"><div><span class="eyebrow">NODE MANAGEMENT</span><h2>Серверная сеть</h2><p>Подключённые серверы и состояние установок</p></div><button class="primary wpo-add-node" id="wpoAddNode" type="button">'+icon("plus")+' Добавить ноду</button></div>'
      +'<div class="wpo-node-stats">'+stats+'</div><div class="wpo-node-grid">'+''.join(cards)+(empty if empty else '')+'</div>'
      +'<div class="wpo-node-legend"><span><i class="online"></i>В сети</span><span><i class="installing"></i>Установка</span><span><i class="registration"></i>Регистрация</span><span><i class="offline"></i>Не в сети</span><span><i class="error"></i>Ошибка</span></div></section>'
      +'<dialog id="wpoAddNodeDialog" class="wpo-node-dialog"><div class="dialog-head"><div><h2>Добавить ноду</h2><small>Установка отдельного Node Agent на новый VPS</small></div><button type="button" data-wpo-close>×</button></div><div class="wpo-node-dialog-body"><div class="wpo-step"><i>1</i><div><b>Сгенерируйте установщик</b><small>Одноразовый ключ действует 15 минут.</small></div></div><button class="primary" id="wpoGenerateNode" type="button">Сгенерировать установщик</button><div id="wpoNodeGenerated" class="wpo-node-generated" hidden><label>Одноразовый ключ<input id="wpoNodeToken" readonly></label><button type="button" id="wpoCopyToken">Копировать ключ</button><label>Команда установки<textarea id="wpoNodeCommand" rows="4" readonly></textarea></label><button type="button" class="primary" id="wpoCopyCommand">Копировать команду</button><p class="wpo-node-hint">Скопируйте команду и запустите на чистом VPS. Понадобятся домен ноды и email для HTTPS. Окно останется открытым, пока вы его не закроете.</p></div><p id="wpoNodeCreateError" class="create-error" hidden></p></div></dialog>'
      +'<dialog id="wpoEditNodeDialog" class="wpo-node-dialog"><div class="dialog-head"><div><h2>Настройки ноды</h2><small>Название и шаблон сайта</small></div><button type="button" data-wpo-close>×</button></div><form id="wpoEditNodeForm" class="wpo-node-dialog-body"><input type="hidden" name="csrf" value="'+esc(csrf)+'"><input type="hidden" name="operation" value="edit"><input type="hidden" name="id"><label>Название ноды<input name="name" maxlength="80" required></label><label>Шаблон сайта<select name="site_template">'+options+'</select></label><p class="wpo-node-hint">Шаблоны берутся из раздела «Настройки» панели, включая ваши собственные. На подключённом Node Agent 0.2 выбранный шаблон публикуется на домене ноды.</p><div class="actions"><button type="button" data-wpo-close>Отмена</button><button class="primary" type="submit">Сохранить</button></div><p id="wpoEditNodeError" class="create-error" hidden></p></form></dialog>'
      +'<style>'+css+'</style><script>'+js+'</script>')
"""
ui=ui[:start]+new_nodes+ui[end:]
# Expose the real current preset list to the node editor.
anchor='body=nodes_ui([node_api.public_node(n) for n in node_api.load_nodes(NODES_FILE)],node_api.load_location(LOCATION_FILE),"",PANEL_PATH,self.csrf(),pending_rows)'
panel=replace_once(panel,anchor,anchor[:-1].replace('LOCATION_FILE),"",PANEL_PATH','LOCATION_FILE),DOMAIN,PANEL_PATH')+',all_presets())','load site presets')
# Old generated tokens are not installation jobs: never render cards until the installer reports progress.
needle='and now-int(v.get("updated_at",v.get("created_at",now)) or now)<=3600]'
panel=replace_once(panel,needle,'and now-int(v.get("updated_at",v.get("created_at",now)) or now)<=3600 and not (v.get("detail")=="Ожидает запуска установщика" and not v.get("domain"))]','filter idle pending page')
needle='if not isinstance(item,dict) or now-int(item.get("updated_at",item.get("created_at",now)) or now)>3600: continue'
panel=replace_once(panel,needle,'if not isinstance(item,dict) or now-int(item.get("updated_at",item.get("created_at",now)) or now)>3600 or (item.get("detail")=="Ожидает запуска установщика" and not item.get("domain")): continue','filter idle pending poll')
# Existing node-action handler accepts session+CSRF before this branch; add edit/delete operations.
anchor='                elif operation=="rename":\n'
insert='''                elif operation=="pending-delete":
                    uid=str(form.get("id",""))
                    if not uid.startswith("p-") or len(uid)!=14 or not all(ch in "0123456789abcdef" for ch in uid[2:]):
                        raise node_api.NodeError("Некорректный идентификатор установки.")
                    pending=wpo_pending_load()
                    matches=[key for key in pending if key.startswith(uid[2:])]
                    if len(matches)!=1: raise node_api.NodeError("Установка не найдена.")
                    pending.pop(matches[0]); wpo_pending_save(pending)
                    if self.headers.get("X-WPP-Async","")=="1": self.send_json({"ok":True}); return
                elif operation=="edit":
                    nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")
                    selected=next((node for node in nodes if node.get("id")==uid),None)
                    if selected is None: raise node_api.NodeError("Нода не найдена.")
                    new_name=node_api.clean_text(form.get("name",""),"Название ноды",80)
                    template_id=str(form.get("site_template",""))
                    allowed={str(item.get("id")):item for item in all_presets() if isinstance(item,dict)}
                    if template_id and template_id not in allowed: raise node_api.NodeError("Шаблон не найден в настройках панели.")
                    if template_id!=str(selected.get("site_template_id","")):
                        caps=selected.get("capabilities") or []
                        if "site-template" not in caps:
                            raise node_api.NodeError("Эта нода не поддерживает шаблоны сайтов. Требуется Node Agent версии 0.2 или новее.")
                        preset=allowed.get(template_id)
                        html_text=str(preset.get("html","")) if preset else ""
                        asset_names=sorted(set(re.findall(r"/(preset-[A-Za-z0-9_.-]+\.webp)",html_text)))
                        assets=[]; total=0
                        for filename in asset_names:
                            file_path=os.path.join("/srv/tproxy-site",filename)
                            try:
                                with open(file_path,"rb") as stream: raw=stream.read(2000001)
                            except OSError: raise node_api.NodeError("Не найден ресурс шаблона: "+filename)
                            if len(raw)>2000000: raise node_api.NodeError("Ресурс шаблона слишком большой: "+filename)
                            total+=len(raw)
                            if total>6500000: raise node_api.NodeError("Шаблон содержит слишком много изображений.")
                            assets.append({"name":filename,"data":base64.b64encode(raw).decode("ascii")})
                        node_api.request(selected,"POST",node_api.API_PREFIX+"/site-template",{"template_id":template_id,"html":html_text,"assets":assets},timeout=35)
                        selected["site_template_id"]=template_id
                    selected["name"]=new_name
                    node_api.save_nodes(NODES_FILE,nodes)
                    if self.headers.get("X-WPP-Async","")=="1": self.send_json({"ok":True}); return
'''
panel=replace_once(panel,anchor,insert+anchor,'node edit/delete actions')
# JSON error messages in node edit modal, not browser error page.
panel=replace_once(panel,
'''            except node_api.NodeError as exc:
                self.send_html(esc(str(exc)),400)
            return

        if path==PANEL_PATH+"/create-account":''',
'''            except node_api.NodeError as exc:
                if self.headers.get("X-WPP-Async","")=="1": self.send_json({"ok":False,"message":str(exc)},400)
                else: self.send_html(esc(str(exc)),400)
            return

        if path==PANEL_PATH+"/create-account":''',
'node async error replies')
for filename,source in [("wpp_ui.py",ui),("panel.py",panel)]:
    compile(source,filename,"exec")
for filename,source in [("wpp_ui.py",ui),("panel.py",panel)]:
    dest=app/filename
    temp=dest.with_suffix(".py.v2tmp")
    temp.write_text(source,encoding="utf-8")
    temp.chmod(dest.stat().st_mode & 0o777)
    temp.replace(dest)
print("Node UI, pending cleanup and template actions compiled.")
PY_PATCH
then
  echo 'Обновление не применено: проверка исходников не прошла.'
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  cp -a "$BACKUP/panel.py" "$PANEL"
  exit 1
fi
install -o root -g root -m 0700 "$TMP" "$AGENT"
if ! python3 -m py_compile "$PANEL" "$UI" || ! bash -n "$AGENT"; then
  echo 'Ошибка проверки синтаксиса. Откат.'
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  cp -a "$BACKUP/panel.py" "$PANEL"
  if [[ -f "$BACKUP/wpp-node-agent-install.sh" ]]; then cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"; fi
  exit 1
fi
if ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  echo 'Служба не запустилась. Откат.'
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  cp -a "$BACKUP/panel.py" "$PANEL"
  if [[ -f "$BACKUP/wpp-node-agent-install.sh" ]]; then cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"; fi
  systemctl restart "$SERVICE" || true
  exit 1
fi
echo "Nodes Lab v2 установлен. Резервная копия: $BACKUP"
echo 'Проверьте раздел «Ноды»: 2 колонки, квадратные карточки, домены, редактирование, удаление установок.'
echo 'Нода с Node Agent 0.1 не поддерживает публикацию шаблонов: потребуется Node Agent 0.2.'
echo 'Основная ветка main не изменена.'
__WPO_EMBED_V2_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v3-install.sh" <<'__WPO_EMBED_V3_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo "Запустите скрипт от root."; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI."; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-card-body' "$UI" || { echo "Nodes Lab v2 не обнаружен. Обновление не применено."; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v3-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY'
from pathlib import Path
import sys

p=Path(sys.argv[1])
source=p.read_text(encoding='utf-8')
if "wpo-node-compact-v3" in source:
    print("Компактный дизайн уже установлен.")
    raise SystemExit(0)

def one(old, new, label):
    global source
    count=source.count(old)
    if count!=1:
        raise RuntimeError(f"{label}: ожидалось 1 совпадение, найдено {count}. Ничего не записано.")
    source=source.replace(old,new,1)

one(
    'grid-template-columns:repeat(2,minmax(0,320px));gap:14px;align-items:start;justify-content:start',
    'grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start',
    'Две колонки')
one(
    'aspect-ratio:1/1;min-width:0;min-height:298px;margin:0;padding:18px;',
    'aspect-ratio:auto;min-width:0;min-height:172px;margin:0;padding:14px;',
    'Прямоугольные карточки')
one(
    'flex:0 0 48px;width:48px;height:48px;',
    'flex:0 0 40px;width:40px;height:40px;',
    'Компактный флаг')
one(
    'border-radius:12px;background:var(--input);font-size:25px}',
    'border-radius:10px;background:var(--input);font-size:22px}',
    'Размер флага')
one(
    '.wpo-node-card-body{display:grid;gap:9px;min-width:0;align-content:center;flex:1;padding:12px 0}',
    '.wpo-node-card-body{display:grid;gap:7px;min-width:0;align-content:center;flex:1;padding:9px 0}',
    'Высота содержимого')
one(
    '.wpo-node-card-body h3{font-size:18px;',
    '.wpo-node-card-body h3{font-size:16px;',
    'Размер заголовка')
one(
    '<a class="wpo-node-domain" href="https://{esc(connection_token)}" target="_blank" rel="noopener noreferrer">{icon("link")}<span>{esc(connection_token)}</span></a>',
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(connection_token)}</span></div>',
    'Домен основной ноды')
one(
    '<a class="wpo-node-domain" href="{esc(url)}" target="_blank" rel="noopener noreferrer" title="Открыть сайт ноды">{icon(\'link\')}<span>{esc(hostname)}</span></a>',
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(hostname)}</span></div>',
    'Домен дополнительной ноды')
one(
    '.wpo-node-domain{display:flex;align-items:center;gap:8px;min-width:0;padding:10px 11px;background:var(--input);border:1px solid var(--line);border-radius:9px;text-decoration:none;color:var(--accent);font:500 12px ui-monospace,monospace}',
    '.wpo-node-domain{display:flex;align-items:center;gap:8px;min-width:0;padding:8px 10px;background:var(--input);border:1px solid var(--line);border-radius:8px;color:var(--text);font:500 12px ui-monospace,monospace;cursor:default}',
    'Оформление домена')
one(
    '.wpo-node-domain:hover{border-color:var(--accent)}',
    '.wpo-domain-mark{font:14px system-ui,sans-serif;flex:0 0 auto}',
    'Неактивный домен')
one(
    '@media(max-width:700px){.wpo-nodes-toolbar{align-items:stretch;flex-direction:column}.wpo-add-node{width:100%;justify-content:center}.wpo-node-stats{grid-template-columns:repeat(2,1fr)}.wpo-node-grid{grid-template-columns:minmax(0,340px)}.wpo-nodes-page .wpo-node-card{min-height:298px}.wpo-node-legend{gap:9px}}',
    '@media(max-width:700px){.wpo-nodes-toolbar{align-items:stretch;flex-direction:column}.wpo-add-node{width:100%;justify-content:center}.wpo-node-stats{grid-template-columns:repeat(2,1fr)}.wpo-node-grid{grid-template-columns:minmax(0,410px)}.wpo-nodes-page .wpo-node-card{min-height:172px}.wpo-node-legend{gap:9px}}',
    'Мобильная разметка')
one(
    '    css=\'\'\'\n.wpo-nodes-page',
    '    # wpo-node-compact-v3\n    css=\'\'\'\n.wpo-nodes-page',
    'Маркер обновления')

compile(source,str(p),'exec')
tmp=p.with_suffix('.py.nodes3tmp')
tmp.write_text(source,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print("Карточки стали прямоугольными, домены больше не являются ссылками.")
PY
then
    echo "Обновление не удалось, возвращаю резервную копию."
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo "Ошибка проверки или перезапуска. Возвращаю прежнюю версию."
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Дизайн нод обновлён. Резервная копия: $BACKUP"
echo "Главная ветка main не затронута."
__WPO_EMBED_V3_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v4-install.sh" <<'__WPO_EMBED_V4_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo "Запустите от root."; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба $SERVICE"; exit 1; }
grep -q 'wpo-node-compact-v3' "$UI" || { echo 'Нужен установленный Nodes Lab v3. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v4-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-title-v4' in src:
    print('Оформление v4 уже установлено.')
    raise SystemExit(0)

def one(old, new, label):
    global src
    count=src.count(old)
    if count != 1: raise RuntimeError(f'{label}: найдено {count} совпадений, требуется одно.')
    src=src.replace(old,new,1)

# Title and country/location return to the flag row; status stays aligned on the right.
one(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span>{status("local","online")}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span><div class="wpo-node-label"><h3>{esc(lname)}</h3><small>Основная нода</small></div>{status("local","online")}</div>',
    'Название основной ноды')
one(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    'Название удалённой ноды')
one(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div>{status(uid,state)}</div>',
    'Название установки')

# Remove former large centered names to avoid duplication.
one(
    '<div class="wpo-node-card-body"><small class="wpo-node-eyebrow">ОСНОВНАЯ НОДА</small><h3>{esc(lname)}</h3>',
    '<div class="wpo-node-card-body">',
    'Заголовок основной карточки')
one(
    '<div class="wpo-node-card-body"><small class="wpo-node-eyebrow">{esc(country)}</small><h3 title="{esc(name)}">{esc(name)}</h3>',
    '<div class="wpo-node-card-body">',
    'Заголовок удалённой карточки')
one(
    '<div class="wpo-node-card-body"><small class="wpo-node-eyebrow">ПОДКЛЮЧЕНИЕ НОДЫ</small><h3>Установка</h3>',
    '<div class="wpo-node-card-body">',
    'Заголовок установки')

# Domain becomes quiet secondary metadata, not an action or a prominent tile.
one(
    '.wpo-node-domain{display:flex;align-items:center;gap:8px;min-width:0;padding:8px 10px;background:var(--input);border:1px solid var(--line);border-radius:8px;color:var(--text);font:500 12px ui-monospace,monospace;cursor:default}',
    '.wpo-node-domain{display:flex;align-items:center;gap:6px;min-width:0;padding:2px 0;background:transparent;border:0;border-radius:0;color:var(--muted);font:400 11px ui-monospace,monospace;cursor:default}',
    'Спокойная подпись домена')
one(
    '.wpo-domain-mark{font:14px system-ui,sans-serif;flex:0 0 auto}',
    '.wpo-domain-mark{font:11px system-ui,sans-serif;filter:grayscale(1);opacity:.65;flex:0 0 auto}',
    'Иконка домена')
one(
    '.wpo-node-card-head,.wpo-node-card-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}',
    '.wpo-node-card-head,.wpo-node-card-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}.wpo-node-label{display:grid;min-width:0;flex:1;gap:3px}.wpo-node-label h3{margin:0;font-size:15px;font-weight:650;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.wpo-node-label small{font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    'Название возле флага')
one(
    '    # wpo-node-compact-v3\n    css=',
    '    # wpo-node-compact-v3\n    # wpo-node-title-v4\n    css=',
    'Маркер обновления')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes4tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Название перенесено к флагу, домен стал компактной подписью.')
PY_PATCH
then
    echo 'Патч не применён. Возвращаю резервную копию.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Проверка или перезапуск не удались. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Обновление Nodes Lab v4 установлено. Резервная копия: $BACKUP"
echo 'Основная ветка main не изменена.'
__WPO_EMBED_V4_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v5-install.sh" <<'__WPO_EMBED_V5_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-title-v4' "$UI" || { echo 'Требуется установленный Nodes Lab v4. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v5-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-title-v5' in src:
    print('Nodes Lab v5 уже установлен.')
    raise SystemExit(0)

def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1: raise RuntimeError(f'{label}: ожидалось 1 совпадение, найдено {count}.')
    src=src.replace(old,new,1)

once(
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(connection_token)}</span></div>',
    '<a class="wpo-node-domain" href="https://{esc(connection_token)}" target="_blank" rel="noopener noreferrer" title="Открыть домен основной ноды"><span class="wpo-domain-mark">🌐</span><span>{esc(connection_token)}</span></a>',
    'Домен основной ноды')
once(
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(hostname)}</span></div>',
    '<a class="wpo-node-domain" href="{esc(url)}" target="_blank" rel="noopener noreferrer" title="Открыть домен ноды"><span class="wpo-domain-mark">🌐</span><span>{esc(hostname)}</span></a>',
    'Домен удалённой ноды')
once(
    '.wpo-node-domain{display:flex;align-items:center;gap:6px;min-width:0;padding:2px 0;background:transparent;border:0;border-radius:0;color:var(--muted);font:400 11px ui-monospace,monospace;cursor:default}',
    '.wpo-node-domain{display:flex;align-items:center;gap:6px;min-width:0;padding:2px 0;background:transparent;border:0;border-radius:0;color:var(--muted);text-decoration:none;font:400 11px ui-monospace,monospace;cursor:pointer}',
    'Стиль домена')
once(
    '.wpo-domain-mark{font:11px system-ui,sans-serif;filter:grayscale(1);opacity:.65;flex:0 0 auto}',
    '.wpo-domain-mark{font:11px system-ui,sans-serif;filter:grayscale(1);opacity:.65;flex:0 0 auto}.wpo-node-domain[href]:hover span:last-child{text-decoration:underline;text-underline-offset:2px}.wpo-node-domain[href]:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:3px}',
    'Наведение на домен')
once(
    '<div class="wpo-node-card-bottom"><span>Локальный сервер</span><span class="muted">Основная</span></div>',
    '<div class="wpo-node-card-bottom"><span class="muted">Основная</span></div>',
    'Убрать Локальный сервер')
once(
    '<h2>Серверная сеть</h2>',
    '<h2>⚙️ Управление нодами</h2>',
    'Заголовок раздела')
once(
    '    # wpo-node-title-v4\n    css=',
    '    # wpo-node-title-v4\n    # wpo-node-title-v5\n    css=',
    'Маркер версии')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes5tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Готово: кликабельные домены, без подписи «Локальный сервер», новый заголовок.')
PY_PATCH
then
    echo 'Ошибка изменения. Возвращаю исходную версию.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Не прошла проверка или перезапуск. Возвращаю исходную версию.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v5 готов. Резервная копия: $BACKUP"
echo 'Основная ветка GitHub main не затронута.'
__WPO_EMBED_V5_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v6-install.sh" <<'__WPO_EMBED_V6_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-title-v5' "$UI" || { echo 'Нужен установленный Nodes Lab v5. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v6-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"
if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-compact-v6' in src:
    print('Компактное оформление v6 уже установлено.')
    raise SystemExit(0)

def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: найдено {count} совпадений, требуется одно. Изменения не записаны.')
    src=src.replace(old,new,1)

# Remove the empty footer from the primary card.
once(
    '      <div class="wpo-node-card-bottom"><span class="muted">Основная</span></div>\n      </article>',
    '      </article>',
    'Нижняя полоса основной ноды')

# Put edit/delete controls beside the status, so other nodes need no footer.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div><div class="wpo-node-head-tools">{status(uid,state)}<div class="wpo-node-actions">{edit}{delete}</div></div></div>',
    'Кнопки подключённой ноды')
once(
    '          <div class="wpo-node-card-bottom"><span>Агент {esc(n.get("version","—"))}</span><div class="wpo-node-actions">{edit}{delete}</div></div>',
    '',
    'Нижняя полоса подключённой ноды')
once(
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p></div>',
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)} · Агент {esc(n.get("version","—"))}</p></div>',
    'Версия ноды рядом с шаблоном')
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div><div class="wpo-node-head-tools">{status(uid,state)}<div class="wpo-node-actions">{delete}</div></div></div>',
    'Корзина временной установки')
once(
    '          <div class="wpo-node-card-bottom"><span>Одноразовый установщик</span><div class="wpo-node-actions">{delete}</div></div></article>',
    '          </article>',
    'Нижняя полоса временной установки')

# Remove empty placeholder and the legend under the grid.
once(
    '    empty=\'\' if nodes or pending_nodes else \'<div class="wpo-node-empty"><b>Дополнительных нод пока нет</b><small>Добавьте ноду, чтобы подключить отдельный VPS.</small></div>\'\n',
    '',
    'Пустой блок')
once(
    '+\'<div class="wpo-node-stats">\'+stats+\'</div><div class="wpo-node-grid">\'+\'\'.join(cards)+(empty if empty else \'\')+\'</div>\'',
    '+\'<div class="wpo-node-stats">\'+stats+\'</div><div class="wpo-node-grid">\'+\'\'.join(cards)+\'</div>\'',
    'Сетка без пустой карточки')
once(
    '+\'<div class="wpo-node-legend"><span><i class="online"></i>В сети</span><span><i class="installing"></i>Установка</span><span><i class="registration"></i>Регистрация</span><span><i class="offline"></i>Не в сети</span><span><i class="error"></i>Ошибка</span></div></section>\'',
    '+\'</section>\'',
    'Удаление легенды под нодами')

# Compact cards in the same two-column, left-to-right flow.
once(
    'aspect-ratio:auto;min-width:0;min-height:172px;margin:0;padding:14px;',
    'aspect-ratio:auto;min-width:0;min-height:108px;margin:0;padding:12px;',
    'Высота карточек')
once(
    '.wpo-node-card-body{display:grid;gap:7px;min-width:0;align-content:center;flex:1;padding:9px 0}',
    '.wpo-node-card-body{display:grid;gap:5px;min-width:0;align-content:center;flex:0 0 auto;padding:6px 0 0}',
    'Компактное содержимое')
once(
    '.wpo-node-card-head,.wpo-node-card-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}',
    '.wpo-node-card-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.wpo-node-head-tools{display:flex;align-items:center;gap:5px;flex:0 0 auto;min-width:0}',
    'Кнопки и статус в заголовке')
once(
    '.wpo-node-card-bottom{padding-top:10px;border-top:1px solid var(--line);min-height:38px;font-size:10px;color:var(--muted)}.wpo-node-actions{display:flex;align-items:center;gap:5px}.wpo-node-actions form{margin:0}',
    '.wpo-node-actions{display:flex;align-items:center;gap:3px}.wpo-node-actions form{margin:0}',
    'Убрать нижний разделитель')
once(
    '.wpo-nodes-page .wpo-node-icon{height:34px;width:34px;padding:6px;',
    '.wpo-nodes-page .wpo-node-icon{height:29px;width:29px;padding:5px;',
    'Размер кнопок управления')
once(
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start}',
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    'Порядок слева направо')
once(
    '.wpo-nodes-page .wpo-node-card{min-height:172px}',
    '.wpo-nodes-page .wpo-node-card{min-height:108px}',
    'Мобильная высота')
once(
    '    # wpo-node-title-v5\n    css=',
    '    # wpo-node-title-v5\n    # wpo-node-compact-v6\n    css=',
    'Маркер обновления')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes6tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Карточки укорочены, элементы управления сохранены, пустой блок и нижняя легенда удалены.')
PY_PATCH
then
    echo 'Патч не применён. Восстанавливаю файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Ошибка проверки или запуска. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v6 установлен. Резервная копия: $BACKUP"
echo 'Ветка main не изменена.'
__WPO_EMBED_V6_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v7-install.sh" <<'__WPO_EMBED_V7_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-compact-v6' "$UI" || { echo 'Требуется установленный Nodes Lab v6. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v7-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-width-v7' in src:
    print('Ширина Nodes Lab v7 уже установлена.')
    raise SystemExit(0)

def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: найдено {n} совпадений вместо одного. Ничего не изменено.')
    src=src.replace(old,new,1)

# One node is as wide as a single "В сети" counter card. Keep two columns, their order,
# the height, padding, text, and node controls untouched.
once(
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,calc((100% - 36px)/5)));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    'Ширина ноды как у блока В сети')
# The five counters become three at tablet width, so keep matching their widths there.
once(
    '@media(max-width:850px){.wpo-node-stats{grid-template-columns:repeat(3,1fr)}}',
    '@media(max-width:850px){.wpo-node-stats{grid-template-columns:repeat(3,1fr)}.wpo-node-grid{grid-template-columns:repeat(2,minmax(0,calc((100% - 18px)/3)))}}',
    'Адаптация ширины нод на планшете')
# Existing mobile single-column layout is preserved.
once(
    '    # wpo-node-compact-v6\n    css=',
    '    # wpo-node-compact-v6\n    # wpo-node-width-v7\n    css=',
    'Метка v7')
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes7tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Изменена только ширина карточек нод. Высота и содержимое сохранены.')
PY_PATCH
then
    echo 'Проверка не пройдена. Восстанавливаю исходный файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Проверка или перезапуск не удались. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi

echo "Ширина нод обновлена. Резервная копия: $BACKUP"
echo 'Основная ветка main не изменена.'
__WPO_EMBED_V7_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v8-install.sh" <<'__WPO_EMBED_V8_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-width-v7' "$UI" || { echo 'Требуется установленный Nodes Lab v7. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v8-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
marker='/* wpo-node-spinner-v8 */'
if marker in src:
    print('Анимация v8 уже добавлена.')
    raise SystemExit(0)
anchor='.wpo-pending-node{border-style:dashed!important}'
if src.count(anchor)!=1:
    raise SystemExit('Не найдено ожидаемое оформление временной ноды. Файл не изменён.')

css="""/* wpo-node-spinner-v8 */
.wpo-pending-node .wpo-node-flag{font-size:0}
.wpo-pending-node .wpo-node-flag::after{content:"";display:block;width:21px;height:21px;box-sizing:border-box;border:2px solid color-mix(in srgb,var(--line) 70%,#eab308);border-top-color:#eab308;border-radius:50%;animation:wpo-node-turn .9s linear infinite}
.wpo-pending-node:has(.wpo-node-status.registration) .wpo-node-flag::after{border-color:color-mix(in srgb,var(--line) 70%,#38bdf8);border-top-color:#38bdf8}
.wpo-pending-node:has(.wpo-node-status.error) .wpo-node-flag::after{content:"!";display:grid;place-items:center;border-color:#ef4444;color:#ef4444;font:700 14px system-ui,sans-serif;animation:none}
.wpo-pending-node .wpo-node-status.installing i,.wpo-pending-node .wpo-node-status.registration i{animation:wpo-node-pulse 1.5s ease-in-out infinite}
@keyframes wpo-node-turn{to{transform:rotate(360deg)}}
@keyframes wpo-node-pulse{50%{opacity:.4;transform:scale(.8)}}
@media(prefers-reduced-motion:reduce){.wpo-pending-node .wpo-node-flag::after,.wpo-pending-node .wpo-node-status i{animation:none}}
"""
src=src.replace(anchor,anchor+'\n'+css,1)
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes8tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Добавлен кружок загрузки только для ноды в процессе установки.')
PY_PATCH
then
    echo 'Не удалось добавить анимацию; восстанавливаю файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Ошибка проверки или перезапуска; выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v8: анимация установки добавлена. Резервная копия: $BACKUP"
echo 'Основная ветка GitHub main не затронута.'
__WPO_EMBED_V8_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v9-install.sh" <<'__WPO_EMBED_V9_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-spinner-v8' "$UI" || { echo 'Требуется установленный Nodes Lab v8. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v9-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-aligned-v9' in src:
    print('Выравнивание v9 уже установлено.')
    raise SystemExit(0)

def once(old, new, name):
    global src
    count=src.count(old)
    if count != 1:
        raise RuntimeError(f'{name}: ожидается одно совпадение, найдено {count}. Ничего не изменено.')
    src=src.replace(old,new,1)

# Progress is shown under "Установка", where normal nodes show the country.
# Domain remains on the second line; no additional third line extends the card.
once(
    '<div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div>',
    '<div class="wpo-node-label"><h3>Установка</h3><small data-node-progress="{esc(uid)}" title="{esc(detail)}">{esc(detail)}</small></div>',
    'Прогресс в заголовке')
once(
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">{icon("link")}<span>{esc(domain or "Домен определяется")}</span></div><p class="wpo-node-template">{esc(detail)}</p></div>',
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">{icon("link")}<span data-node-domain="{esc(uid)}">{esc(domain or "Домен определяется")}</span></div></div>',
    'Убрать лишнюю строку установки')
# Keep progress and domain updated every second without reloading the page.
once(
    'for(const n of [...(d.nodes||[]),...(d.pending||[])]){const el=document.querySelector(',
    'for(const n of [...(d.nodes||[]),...(d.pending||[])]){if(n.id&&n.id.startsWith("p-")){const progress=document.querySelector("[data-node-progress="+CSS.escape(n.id)+"]");if(progress&&typeof n.detail==="string"){progress.textContent=n.detail;progress.title=n.detail}const domain=document.querySelector("[data-node-domain="+CSS.escape(n.id)+"]");if(domain&&n.domain)domain.textContent=n.domain}const el=document.querySelector(',
    'Живое обновление прогресса и домена')
once(
    '    # wpo-node-title-v5\n    # wpo-node-compact-v6',
    '    # wpo-node-title-v5\n    # wpo-node-aligned-v9\n    # wpo-node-compact-v6',
    'Маркер v9')
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes9tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Временная карточка выровнена с основной; анимация и статус сохранены.')
PY_PATCH
then
    echo 'Ошибка изменения. Возвращаю исходный файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Ошибка проверки или перезапуска. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v9 готов. Резервная копия: $BACKUP"
echo 'Основная ветка main не затронута.'
__WPO_EMBED_V9_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v10-install.sh" <<'__WPO_EMBED_V10_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
[[ $EUID -eq 0 ]] || { echo 'Запустите команду от root.'; exit 1; }
[[ -s "$AGENT" ]] || { echo "Установщик нод не найден: $AGENT"; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Требуется установленный Node Agent 0.2 (Nodes Lab v2). Ничего не изменено.'; exit 1; }
if grep -Fq 'PY_VALIDATE_EMAIL' "$AGENT"; then
  echo 'Проверка email уже обновлена. Ничего не изменено.'
  exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 20 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
if ! grep -Fq 'PY_VALIDATE_EMAIL' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_STATUS_URL__' "$TMP" ||
   ! grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$TMP" ||
   ! bash -n "$TMP"; then
  echo 'Полученный установщик не прошёл проверку; действующая версия не изменена.'
  exit 1
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v10-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"
if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
  cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
  echo 'Ошибка обновления, предыдущая версия восстановлена.'
  exit 1
fi

echo 'Nodes Lab v10: проверка email обновлена.'
echo 'Кириллица и некорректные адреса отклоняются до установки Caddy.'
echo "Резервная копия: $BACKUP"
echo 'Перезапуск панели не требуется. GitHub main не изменён.'
__WPO_EMBED_V10_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v11-install.sh" <<'__WPO_EMBED_V11_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$AGENT" ]] || { echo "Установщик нод не найден: $AGENT"; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Требуется Node Agent 0.2. Ничего не изменено.'; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 20 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
if ! grep -Fq 'for EMAIL_ATTEMPT in 1 2 3' "$TMP" ||
   ! grep -Fq 'PY_EMAIL_TRIM' "$TMP" ||
   ! grep -Fq 'PY_VALIDATE_EMAIL' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_STATUS_URL__' "$TMP" ||
   ! grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$TMP" ||
   ! bash -n "$TMP"; then
  echo 'Полученный установщик не прошёл проверку. Действующая версия не изменена.'
  exit 1
fi
if cmp -s "$TMP" "$AGENT"; then
  echo 'Обновление email v11 уже установлено.'
  exit 0
fi
BACKUP="/var/lib/tproxy-panel/nodes-lab-v11-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"
if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
  cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
  echo 'Обновление не удалось, исходный установщик восстановлен.'
  exit 1
fi
echo 'Nodes Lab v11: email проверяется до установки Caddy; невидимые символы по краям убираются; три попытки ввода.'
echo "Резервная копия: $BACKUP"
echo 'Панель не перезапускалась. GitHub main не изменён.'
__WPO_EMBED_V11_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v12-install.sh" <<'__WPO_EMBED_V12_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью.'; exit 1; }
[[ -s "$AGENT" ]] || { echo "Установщик ноды не найден: $AGENT"; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Ожидается Node Agent 0.2. Ничего не изменено.'; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 20 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
if ! grep -Fq 'Email для Let' "$TMP" ||
   ! grep -Fq 'Убраны случайные символы по краям email.' "$TMP" ||
   ! grep -Fq 'PY_VALIDATE_EMAIL' "$TMP" ||
   ! grep -Fq 'tls $EMAIL' "$TMP" ||
   ! grep -Fq 'site-template' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_STATUS_URL__' "$TMP" ||
   ! grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$TMP" ||
   ! bash -n "$TMP"; then
  echo 'Проверка нового установщика не пройдена; ничего не изменено.'
  exit 1
fi

if cmp -s "$TMP" "$AGENT"; then
  echo 'Исправленная версия установщика уже установлена.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v12-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"
if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
  cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
  echo 'Не удалось обновить установщик, выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v12: email сохранён; случайная кириллица по краям удаляется, ошибки исправляются без перезапуска установки.'
echo "Резервная копия: $BACKUP"
echo 'Панель не перезапускалась, репозиторий main не изменён.'
__WPO_EMBED_V12_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v13-install.sh" <<'__WPO_EMBED_V13_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR=/opt/tproxy-panel
PANEL="$APP_DIR/panel.py"
UI="$APP_DIR/wpp_ui.py"
GEO="$APP_DIR/wpo_node_geo.py"
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Требуется root на основном VPS.'; exit 1; }
for item in "$PANEL" "$UI"; do [[ -s "$item" ]] || { echo "Не найден $item"; exit 1; }; done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена'; exit 1; }
grep -Fq 'def wpo_pending_load' "$PANEL" || { echo 'Nodes Lab не найден. Ничего не изменено.'; exit 1; }
grep -Fq 'wpo-node-label' "$UI" || { echo 'Неподдерживаемая версия UI нод.'; exit 1; }

if grep -Fq '# wpo-node-country-v13' "$PANEL"; then
  echo 'Обновление геолокации v13 уже установлено.'
  exit 0
fi
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 15 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-geo-v13.py' -o "$TMP"
python3 - "$TMP" <<'PY_CHECK'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text(encoding="utf-8")
assert "def lookup_country(" in s and "def enrich(" in s
compile(s,"wpo_node_geo.py","exec")
PY_CHECK

BACKUP="/var/lib/tproxy-panel/nodes-lab-v13-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$UI" "$BACKUP/wpp_ui.py"
if [[ -f "$GEO" ]]; then cp -a "$GEO" "$BACKUP/wpo_node_geo.py"; fi

if ! python3 - "$PANEL" "$UI" "$TMP" "$GEO" <<'PY_PATCH'
from pathlib import Path
import sys

panel_path,ui_path,geo_source,geo_path=map(Path,sys.argv[1:])
panel=panel_path.read_text(encoding='utf-8')
ui=ui_path.read_text(encoding='utf-8')
def once(source,old,new,label):
    matches=source.count(old)
    if matches!=1:
        raise RuntimeError(f'{label}: найдено {matches} совпадений вместо одного.')
    return source.replace(old,new,1)

panel=once(panel,
    'import shlex\n',
    'import shlex\nimport wpo_node_geo as wpo_node_geo  # wpo-node-country-v13\n',
    'Импорт геолокации')
panel=once(panel,
    'now=int(time.time()); current=node_api.load_nodes(NODES_FILE); changed=False',
    'now=int(time.time()); current=node_api.load_nodes(NODES_FILE); changed=wpo_node_geo.enrich(current,now)',
    'Автообновление страны для неизвестных нод')
panel=once(panel,
    '"nodes":[{"id":n.get("id"),"status":n.get("status","online")} for n in current]',
    '"nodes":[{"id":n.get("id"),"status":n.get("status","online"),"country_code":n.get("country_code","UN"),"name":n.get("name","")} for n in current]',
    'Страна в ответе статуса')
panel=once(panel,
    'n["name"]=display; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"',
    'n["name"]=str(n.get("country_name") or display) if n.get("country_code")!="UN" else display; n["name_auto"]=True; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"',
    'Имя новой ноды из страны')
panel=once(panel,
    'selected["name"]=new_name',
    'selected["name"]=new_name; selected["name_auto"]=False',
    'Сохранение пользовательских имён')

ui=once(ui,
    'const state=map[n.status]||map.offline;el.className=',
    'if(n.name&&el.closest(".wpo-node-card")?.querySelector(".wpo-node-label h3")?.textContent.trim()!==n.name){location.reload();return}if(n.country_code&&n.country_code!=="UN"&&el.closest(".wpo-node-card")?.querySelector(".wpo-node-flag")?.textContent.includes("🌐")){location.reload();return}const state=map[n.status]||map.offline;el.className=',
    'Автообновление карточки при появлении флага')

compile(panel,str(panel_path),'exec')
compile(ui,str(ui_path),'exec')
geo=geo_source.read_text(encoding='utf-8')
compile(geo,str(geo_path),'exec')
for target,value in [(geo_path,geo),(panel_path,panel),(ui_path,ui)]:
    tmp=target.with_suffix(target.suffix+'.v13tmp')
    tmp.write_text(value,encoding='utf-8')
    tmp.chmod(target.stat().st_mode & 0o777 if target.exists() else 0o644)
    tmp.replace(target)
print('Геолокация нод обновлена. Имена, заданные вручную, сохраняются.')
PY_PATCH
then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_geo.py" ]]; then cp -a "$BACKUP/wpo_node_geo.py" "$GEO"; else rm -f "$GEO"; fi
  echo 'Ошибка проверки: исходные файлы восстановлены.'
  exit 1
fi
if ! python3 -m py_compile "$PANEL" "$UI" "$GEO" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_geo.py" ]]; then cp -a "$BACKUP/wpo_node_geo.py" "$GEO"; else rm -f "$GEO"; fi
  systemctl restart "$SERVICE" || true
  echo 'Ошибка при запуске. Панель возвращена к предыдущей версии.'
  exit 1
fi
echo "Nodes Lab v13: добавлена повторная геолокация нод по IP, с сохранением ручных названий."
echo 'Откройте раздел Ноды: информация обновится автоматически при следующей проверке.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main не изменён. На VPS ноды изменения не требуются.'
__WPO_EMBED_V13_END_736a4b__

cat > "$STAGE/wpo-nodes-lab-v14-install.sh" <<'__WPO_EMBED_V14_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-aligned-v9' "$UI" || { echo 'Требуется установленный Nodes Lab v9 или новее. Ничего не изменено.'; exit 1; }

if grep -Fq '# wpo-node-visual-v14' "$UI"; then
  echo 'Nodes Lab v14 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v14-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    hits=src.count(old)
    if hits!=1:
        raise RuntimeError(f'{label}: найдено {hits} совпадений вместо одного. Файл не изменён.')
    src=src.replace(old,new,1)

# Preserve both node columns and their existing widths; stretch each card in
# one grid row to the height of the taller card.
once(
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,calc((100% - 36px)/5)));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,calc((100% - 36px)/5)));gap:12px;align-items:stretch;justify-content:start;grid-auto-flow:row}',
    'Одинаковая высота Нидерландов и Чехии')

# On additional nodes, the status becomes the right-most control in the header.
# The primary node markup is intentionally left untouched.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div><div class="wpo-node-head-tools">{status(uid,state)}<div class="wpo-node-actions">{edit}{delete}</div></div></div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    'Статус дополнительной ноды справа')

# Restore the clean site-template line, remove version and dot separator,
# and put only edit/delete controls at the bottom-right of additional cards.
once(
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)} · Агент {esc(n.get("version","—"))}</p></div>',
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p></div><div class="wpo-node-card-bottom"><div class="wpo-node-actions">{edit}{delete}</div></div>',
    'Шаблон сайта по центру, кнопки снизу справа')

once(
    '.wpo-node-actions{display:flex;align-items:center;gap:3px}.wpo-node-actions form{margin:0}',
    '.wpo-node-actions{display:flex;align-items:center;gap:3px}.wpo-node-actions form{margin:0}\n'
    '/* wpo-node-visual-v14: only additional-node footers and template labels */\n'
    '.wpo-nodes-page .wpo-node-card-bottom{display:flex;align-items:center;justify-content:flex-end;min-height:29px;margin-top:auto;padding:5px 0 0;border:0;background:transparent}\n'
    '.wpo-nodes-page .wpo-node-card-bottom .wpo-node-actions{margin-left:auto;justify-content:flex-end}\n'
    '.wpo-nodes-page .wpo-node-template{text-align:center;margin:6px 0 0;line-height:1.35}\n'
    '.wpo-nodes-page .wpo-node-template .ico{vertical-align:-2px;margin-right:2px}',
    'Позиционирование действий и названия шаблона')

once(
    '    # wpo-node-aligned-v9\n    # wpo-node-compact-v6',
    '    # wpo-node-aligned-v9\n    # wpo-node-visual-v14\n    # wpo-node-compact-v6',
    'Маркер версии v14')

compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes14tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Готово: карточки одной высоты, статус справа, кнопки внизу, только название сайта.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Правка не применена: файл восстановлен из резервной копии.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Не пройдена проверка или запуск панели: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v14: визуальные правки карточек нод применены.'
echo "Резервная копия: $BACKUP"
echo 'Node Agent и подключения не изменены. GitHub main не затронута.'
__WPO_EMBED_V14_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v15-install.sh" <<'__WPO_EMBED_V15_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите на основном VPS от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл панели не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-visual-v14' "$UI" || { echo 'Сначала требуется Nodes Lab v14. Изменения не применены.'; exit 1; }

if grep -Fq '# wpo-node-polish-v15' "$UI"; then
  echo 'Nodes Lab v15 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v15-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: найдено {n} совпадений вместо 1. Ничего не изменено.')
    src=src.replace(old,new,1)

# Main node: one centered country name and a discreet starred flag. Status unchanged.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span><div class="wpo-node-label"><h3>{esc(lname)}</h3><small>Основная нода</small></div>{status("local","online")}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag wpo-node-main-flag">{esc(node_flag(lc))}<span class="wpo-node-main-mark" title="Основная нода" aria-label="Основная нода">★</span></span><div class="wpo-node-label"><h3>{esc(lname)}</h3></div>{status("local","online")}</div>',
    'Основная нода без подписи и со звёздочкой')

# Additional nodes: no duplicated country subtitle. Keep status at the right.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3></div>{status(uid,state)}</div>',
    'Убрать повтор названия страны у дополнительных нод')

css=r"""
/* wpo-node-polish-v15 — clean grid, equal domain baselines, blue globe */
.wpo-nodes-page .wpo-node-card{
    display:grid;
    grid-template-rows:40px minmax(0,1fr) 27px;
    row-gap:7px;
    min-height:157px;
    align-content:stretch;
    justify-content:stretch;
}
.wpo-nodes-page .wpo-node-card-head{min-height:40px;align-items:center;gap:7px}
.wpo-nodes-page .wpo-node-label{
    display:flex;align-items:center;min-width:0;flex:1;min-height:40px;gap:0
}
.wpo-nodes-page .wpo-node-label h3{
    margin:0;font-size:14px;line-height:1.2;font-weight:650;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis
}
.wpo-nodes-page .wpo-node-card-head>.wpo-node-status{margin-left:auto;flex-shrink:0}
.wpo-nodes-page .wpo-node-card-body{
    grid-row:2;display:grid;align-content:start;align-self:start;
    gap:6px;min-width:0;padding:0;flex:none;
}
.wpo-nodes-page .wpo-node-domain{
    display:flex;align-items:center;gap:7px;min-width:0;
    margin:0;padding:3px 0;background:transparent;border:0;
    color:var(--muted);text-decoration:none;cursor:pointer;
    font:500 10.5px/1.3 ui-monospace,monospace;letter-spacing:-.16px
}
.wpo-nodes-page .wpo-node-domain .wpo-domain-mark{
    filter:none;opacity:1;color:#38bdf8;
    font:13px/1 system-ui,sans-serif;flex:0 0 13px
}
.wpo-nodes-page .wpo-node-domain span:last-child{
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0
}
.wpo-nodes-page .wpo-node-domain:hover{color:var(--accent)}
.wpo-nodes-page .wpo-node-template{
    display:flex;align-items:center;justify-content:center;gap:4px;
    min-width:0;margin:3px 0 0;line-height:1.35;
    text-align:center;transform:translateX(-6px);font-size:10.5px
}
.wpo-nodes-page .wpo-node-template .ico{
    flex:0 0 13px;width:13px;height:13px;margin:0;vertical-align:middle
}
.wpo-nodes-page .wpo-node-card-bottom{
    grid-row:3;align-self:end;min-height:27px;margin:0;padding:0;
    display:flex;align-items:center;justify-content:flex-end
}
.wpo-nodes-page .wpo-node-card-bottom .wpo-node-actions{margin-left:auto}
.wpo-nodes-page .wpo-node-main-flag{position:relative}
.wpo-nodes-page .wpo-node-main-mark{
    position:absolute;top:-5px;right:-5px;display:grid;place-items:center;
    width:16px;height:16px;border:1px solid var(--line);border-radius:50%;
    background:var(--surface);color:#eab308;
    font:700 10px/1 system-ui,sans-serif
}
@media(max-width:700px){
  .wpo-nodes-page .wpo-node-card{min-height:157px}
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Единая сетка и оформление доменов')

once(
    '    # wpo-node-visual-v14\n    # wpo-node-compact-v6',
    '    # wpo-node-visual-v14\n    # wpo-node-polish-v15\n    # wpo-node-compact-v6',
    'Маркер v15')

compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes15tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Карточки выровнены, названия по центру флага, домены на одной линии.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Ошибка обновления: восстановлен предыдущий интерфейс.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или перезапуска: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v15: визуал карточек нод обновлён.'
echo "Резервная копия: $BACKUP"
echo 'Подключения, настройки и Node Agent не изменены. GitHub main не затронут.'
__WPO_EMBED_V15_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v16-install.sh" <<'__WPO_EMBED_V16_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-polish-v15' "$UI" || { echo 'Требуется установленный Nodes Lab v15. Ничего не изменено.'; exit 1; }
if grep -Fq '# wpo-node-finetune-v16' "$UI"; then
  echo 'Nodes Lab v16 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v16-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: найдено {n} совпадений вместо 1. Изменений нет.')
    src=src.replace(old,new,1)

# Keep both node columns identical; reduce each card by only eight pixels.
once(
    '    grid-template-rows:40px minmax(0,1fr) 27px;\n    row-gap:7px;\n    min-height:157px;',
    '    grid-template-rows:40px minmax(0,1fr) 25px;\n    row-gap:6px;\n    min-height:149px;',
    'Высота двух карточек')

# Move the domain down equally in the main and additional node.
once(
    '    gap:6px;min-width:0;padding:0;flex:none;',
    '    gap:6px;min-width:0;padding:7px 0 0;flex:none;',
    'Домены чуть ниже')

# Align the gear icon and site-template name with the globe and domain text.
once(
    '    display:flex;align-items:center;justify-content:center;gap:4px;\n'
    '    min-width:0;margin:3px 0 0;line-height:1.35;\n'
    '    text-align:center;transform:translateX(-6px);font-size:10.5px',
    '    display:flex;align-items:center;justify-content:flex-start;gap:7px;\n'
    '    min-width:0;margin:3px 0 0;line-height:1.35;\n'
    '    text-align:left;transform:none;font-size:10.5px',
    'Подпись шаблона слева, по сетке домена')

once(
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:157px}\n}',
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:149px}\n}',
    'Адаптация мобильного вида')

once(
    '    # wpo-node-polish-v15\n    # wpo-node-compact-v6',
    '    # wpo-node-polish-v15\n    # wpo-node-finetune-v16\n    # wpo-node-compact-v6',
    'Маркер v16')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes16tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Высота карточек уменьшена на 8px, домены опущены, подпись шаблона выровнена по тексту.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Ошибка правки: интерфейс восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки/перезапуска: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v16: карточки чуть ниже, домены опущены, строка шаблона слева.'
echo "Резервная копия: $BACKUP"
echo 'Функции нод не затронуты. Основная ветка main не изменена.'
__WPO_EMBED_V16_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v17-install.sh" <<'__WPO_EMBED_V17_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-finetune-v16' "$UI" || { echo 'Требуется установленный Nodes Lab v16. Ничего не изменено.'; exit 1; }
if grep -Fq '# wpo-node-globe-v17' "$UI"; then
  echo 'Оформление Nodes Lab v17 уже установлено.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v17-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')
def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: найдено {count} совпадений вместо одного; файл не изменён.')
    src=src.replace(old,new,1)

# Both cards use the same monochrome, precisely aligned blue vector globe.
# Avoid platform-dependent emoji baseline and font sizing differences.
globe_svg=(
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9"/>'
    '<path d="M3 12h18M12 3c2.8 2.4 4 5.4 4 9s-1.2 6.6-4 9'
    'M12 3c-2.8 2.4-4 5.4-4 9s1.2 6.6 4 9"/>'
    '</svg>'
)
old_globe='<span class="wpo-domain-mark">🌐</span>'
count=src.count(old_globe)
if count != 2:
    raise RuntimeError(f'Глобусы основной и дополнительной ноды: найдено {count}, ожидается 2.')
src=src.replace(old_globe,'<span class="wpo-domain-mark">'+globe_svg+'</span>')

# Reduce both cards by another seven pixels, without moving top indicators.
once(
    '    grid-template-rows:40px minmax(0,1fr) 25px;\n    row-gap:6px;\n    min-height:149px;',
    '    grid-template-rows:40px minmax(0,1fr) 25px;\n    row-gap:6px;\n    min-height:142px;',
    'Высота двух карточек')
once(
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:149px}\n}',
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:142px}\n}',
    'Мобильная высота')

# Fix the icon and text baselines identically in both domain rows.
css="""
/* wpo-node-globe-v17: fixed SVG baseline for both domain rows */
.wpo-nodes-page .wpo-node-domain{
  display:grid;grid-template-columns:14px minmax(0,1fr);
  align-items:center;column-gap:7px;min-height:21px;line-height:1.35
}
.wpo-nodes-page .wpo-node-domain .wpo-domain-mark{
  display:flex;align-items:center;justify-content:center;
  width:14px;height:16px;min-width:14px;color:#38bdf8;
  font-size:0;line-height:0;filter:none;opacity:1;
}
.wpo-nodes-page .wpo-node-domain .wpo-domain-mark svg{
  display:block;width:14px;height:14px;flex:0 0 14px;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'CSS выравнивания SVG')

once(
    '    # wpo-node-finetune-v16\n    # wpo-node-compact-v6',
    '    # wpo-node-finetune-v16\n    # wpo-node-globe-v17\n    # wpo-node-compact-v6',
    'Маркер v17')

compile(src,str(path),'exec')
tmp=path.with_suffix('.py.nodes17tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(path.stat().st_mode & 0o777)
tmp.replace(path)
print('Глобусы выровнены и заменены на голубые SVG, карточки уменьшены на 7px.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Изменения не применены. Восстановлена резервная копия.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или запуска: выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v17: одинаковые голубые глобусы, карточки ниже на 7px.'
echo "Резервная копия: $BACKUP"
echo 'Данные, функции нод и GitHub main не изменены.'
__WPO_EMBED_V17_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v18-install.sh" <<'__WPO_EMBED_V18_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-globe-v17' "$UI" || { echo 'Требуется установленный Nodes Lab v17. Ничего не изменено.'; exit 1; }
if grep -Fq '# wpo-node-divider-v18' "$UI"; then
  echo 'Nodes Lab v18 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v18-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    matches=src.count(old)
    if matches!=1:
        raise RuntimeError(f'{label}: найдено {matches} совпадений вместо одного. Файл не изменён.')
    src=src.replace(old,new,1)

# Primary node: preserve the complete flag/title/status/domain, add matching
# metadata under its domain. Restrict replacement to the local card only.
start=src.index('    cards.append(f\'\'\'<article class="card wpo-node-card">')
end=src.index('    for n in nodes:',start)
main=src[start:end]
if main.count('</a></div>')!=1 or 'href="https://{esc(connection_token)}"' not in main:
    raise RuntimeError('Не найдена ожидаемая основная карточка; ничего не изменено.')
main=main.replace('</a></div>',
    '</a><div class="wpo-node-meta-row"><p class="wpo-node-template wpo-main-node-label">Основная нода</p></div></div>',1)
src=src[:start]+main+src[end:]

# Additional nodes: template and action buttons share the same separated row.
# Template name remains dynamic ("Технические работы", "Открытие кофейни"...).
once(
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p></div><div class="wpo-node-card-bottom"><div class="wpo-node-actions">{edit}{delete}</div></div>',
    '<div class="wpo-node-meta-row"><p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p><div class="wpo-node-actions">{edit}{delete}</div></div></div>',
    'Строка шаблона и кнопок')

# Exactly the same layout for local/remote nodes. Installation cards are
# excluded, so their spinner and progress presentation stay unchanged.
css=r"""
/* wpo-node-divider-v18: matched meta rows with subtle separators */
.wpo-nodes-page .wpo-node-card:not(.wpo-pending-node){
    display:grid;
    grid-template-rows:40px minmax(0,1fr);
    row-gap:5px;
    min-height:140px;
    padding:10px 12px;
}
.wpo-nodes-page .wpo-node-card:not(.wpo-pending-node) .wpo-node-card-body{
    display:grid;
    grid-template-rows:21px minmax(0,1fr);
    row-gap:7px;
    align-content:stretch;
    align-self:stretch;
    padding:11px 0 0;
    min-width:0;
}
.wpo-nodes-page .wpo-node-meta-row{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:5px;
    align-self:end;
    min-height:35px;
    min-width:0;
    position:relative;
    padding:6px 0 0;
    border-top:1px solid var(--line);
}
.wpo-nodes-page .wpo-node-meta-row::before{
    content:"";
    position:absolute;
    top:-1px;left:0;
    height:1px;width:55%;
    background:linear-gradient(90deg,color-mix(in srgb,var(--accent) 44%,var(--line)),transparent);
    pointer-events:none;
}
.wpo-nodes-page .wpo-node-meta-row .wpo-node-template{
    margin:0;
    padding:0;
    display:flex;
    justify-content:flex-start;
    align-items:center;
    gap:6px;
    text-align:left;
    transform:none;
    min-width:0;
    line-height:1.35;
    font-size:10.5px;
    overflow:hidden;
    white-space:nowrap;
    text-overflow:ellipsis;
}
.wpo-nodes-page .wpo-node-meta-row:has(.wpo-node-actions) .wpo-node-template{
    max-width:calc(100% - 61px);
}
.wpo-nodes-page .wpo-node-meta-row .wpo-node-actions{
    margin-left:auto;
    display:flex;
    flex:0 0 auto;
    align-items:center;
    justify-content:flex-end;
    gap:3px;
}
.wpo-nodes-page .wpo-node-meta-row .wpo-main-node-label{
    font-size:12px;
    line-height:1.35;
    font-weight:650;
    color:var(--text);
    letter-spacing:.01em;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Стили разделителя и общей сетки')

once(
    '    # wpo-node-globe-v17\n    # wpo-node-compact-v6',
    '    # wpo-node-globe-v17\n    # wpo-node-divider-v18\n    # wpo-node-compact-v6',
    'Маркер v18')

compile(src,str(p),'exec')
temp=p.with_suffix('.py.nodes18tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(p.stat().st_mode & 0o777)
temp.replace(p)
print('Добавлены одинаковые разделители; "Основная нода" и шаблон сайта стоят на одной линии.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Правка не применена, интерфейс восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Проверка или запуск панели не удались. Выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v18: обе карточки с разделителем, подписи на одном уровне, немного компактнее.'
echo "Резервная копия: $BACKUP"
echo 'Сервисы нод, шаблоны, статусы и GitHub main не затронуты.'
__WPO_EMBED_V18_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v19-install.sh" <<'__WPO_EMBED_V19_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-divider-v18' "$UI" || { echo 'Сначала установите Nodes Lab v18. Ничего не изменено.'; exit 1; }

if grep -Fq '# wpo-node-server-icon-v19' "$UI"; then
  echo 'Nodes Lab v19 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v19-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: найдено {count} совпадений вместо одного. Исходник не изменён.')
    src=src.replace(old,new,1)

# Reuse the panel's server-rack icon, which is already drawn in the same
# SVG style and size as the site-template/settings icon.
once(
    '<p class="wpo-node-template wpo-main-node-label">Основная нода</p>',
    '<p class="wpo-node-template wpo-main-node-label">{icon("nodes")} Основная нода</p>',
    'Значок сервера перед подписью основной ноды')

# Keep all card measurements untouched. Tint only this new icon.
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    '\n/* wpo-node-server-icon-v19 */\n'
    '.wpo-nodes-page .wpo-main-node-label .ico{color:#38bdf8}\n'
    "'''\n    js=r'''(()=>{const path=__PATH__",
    'Голубой значок сервера')

once(
    '    # wpo-node-divider-v18\n    # wpo-node-compact-v6',
    '    # wpo-node-divider-v18\n    # wpo-node-server-icon-v19\n    # wpo-node-compact-v6',
    'Маркер v19')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes19tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Значок сервера добавлен к надписи "Основная нода".')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Обновление не применено: исходный интерфейс восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Проверка или перезапуск не удались: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v19: у основной ноды появился голубой значок сервера.'
echo "Резервная копия: $BACKUP"
echo 'Размеры и функции нод не изменены. GitHub main не затронут.'
__WPO_EMBED_V19_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v20-install.sh" <<'__WPO_EMBED_V20_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
AUTO="$APP/wpo_node_autotemplate.py"
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью WPO.'; exit 1; }
[[ -s "$PANEL" && -s "$UI" ]] || { echo 'Файлы панели не найдены.'; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq 'def wpo_pending_load' "$PANEL" || { echo 'Nodes Lab не обнаружен.'; exit 1; }
grep -Fq 'all_presets()' "$PANEL" || { echo 'Требуется поддержка шаблонов из Nodes Lab v2.'; exit 1; }
grep -Fq '# wpo-node-country-v13' "$PANEL" || { echo 'Требуется установленный Nodes Lab v13 или новее.'; exit 1; }
grep -Fq '# wpo-node-server-icon-v19' "$UI" || { echo 'Требуется установленный Nodes Lab v19.'; exit 1; }

if grep -Fq '# wpo-node-auto-v20' "$PANEL"; then
  echo 'Nodes Lab v20 уже установлен.'
  exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 15 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-autotemplate-v20.py' -o "$TMP"
python3 - "$TMP" <<'PY_CHECK'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text(encoding='utf-8')
assert all(x in s for x in ['def choose(', 'def start(', 'def _loop(', 'registry_lock'])
compile(s,'wpo_node_autotemplate.py','exec')
PY_CHECK

BACKUP="/var/lib/tproxy-panel/nodes-lab-v20-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$UI" "$BACKUP/wpp_ui.py"
if [[ -f "$AUTO" ]]; then cp -a "$AUTO" "$BACKUP/wpo_node_autotemplate.py"; fi

if ! python3 - "$PANEL" "$UI" "$TMP" "$AUTO" <<'PY_PATCH'
from pathlib import Path
import sys
panel_path,ui_path,auto_source,auto_path=map(Path,sys.argv[1:])
panel=panel_path.read_text(encoding='utf-8')
ui=ui_path.read_text(encoding='utf-8')

def once(source,old,new,label):
    cnt=source.count(old)
    if cnt!=1:
        raise RuntimeError(f'{label}: найдено {cnt} совпадений вместо одного. Ничего не изменено.')
    return source.replace(old,new,1)

panel=once(panel,
    'import shlex\n',
    'import shlex\nimport wpo_node_autotemplate as wpo_node_auto  # wpo-node-auto-v20\n',
    'Импорт автоподбора сайтов')

panel=once(panel,
    'class Handler(BaseHTTPRequestHandler):',
    'wpo_node_auto.start(NODES_FILE,lambda: all_presets(),node_api)\n\nclass Handler(BaseHTTPRequestHandler):',
    'Запуск автоотправки шаблонов в фоне')

# Reserve a template ONLY when a new node is enrolled. Reservations are
# persisted before responding, and never alter old/renamed nodes.
old='''                added=node_api.add_node(NODES_FILE,{"connection_token":packed})
                registered=node_api.load_nodes(NODES_FILE); display=str(payload.get("name","")).strip()[:80] or "Нода"
                for n in registered:
                    if n.get("id")==added.get("id"):
                        n["name"]=str(n.get("country_name") or display) if n.get("country_code")!="UN" else display; n["name_auto"]=True; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"
                node_api.save_nodes(NODES_FILE,registered); pending.pop(digest,None); wpo_pending_save(pending)'''
new='''                with wpo_node_auto.registry_lock:
                    added=node_api.add_node(NODES_FILE,{"connection_token":packed})
                    registered=node_api.load_nodes(NODES_FILE); display=str(payload.get("name","")).strip()[:80] or "Нода"
                    for n in registered:
                        if n.get("id")==added.get("id"):
                            n["name"]=str(n.get("country_name") or display) if n.get("country_code")!="UN" else display; n["name_auto"]=True; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"
                            try:
                                auto_id=wpo_node_auto.choose(registered,all_presets())
                                if auto_id: n["auto_site_template_id"]=auto_id
                            except Exception as auto_error:
                                print("Node auto-template selection:",type(auto_error).__name__,file=sys.stderr,flush=True)
                    node_api.save_nodes(NODES_FILE,registered)
                pending.pop(digest,None); wpo_pending_save(pending)'''
panel=once(panel,old,new,'Автоподбор только для новой ноды')

# Show the chosen label automatically as soon as delivery is confirmed.
panel=once(panel,
    '"country_code":n.get("country_code","UN"),"name":n.get("name","")',
    '"country_code":n.get("country_code","UN"),"name":n.get("name",""),"site_template_id":n.get("site_template_id","")',
    'Актуальный шаблон в ответе статуса')

ui=once(ui,
    'const state=map[n.status]||map.offline;el.className=',
    'const edit=el.closest(".wpo-node-card")?.querySelector("[data-node-edit]");if(edit&&typeof n.site_template_id==="string"&&edit.dataset.nodeTemplate!==n.site_template_id){location.reload();return}const state=map[n.status]||map.offline;el.className=',
    'Автообновление имени шаблона в карточке')

# Manual template edits always have priority over pending auto-assignments.
panel=once(panel,
    '                        selected["site_template_id"]=template_id',
    '                        selected["site_template_id"]=template_id\n                        selected.pop("auto_site_template_id",None)',
    'Ручной выбор отменяет ожидающий автоподбор')

newmod=auto_source.read_text(encoding='utf-8')
compile(newmod,str(auto_path),'exec')
compile(panel,str(panel_path),'exec')
compile(ui,str(ui_path),'exec')

# Stage every file and only then replace originals.
for path,data in [(auto_path,newmod),(panel_path,panel),(ui_path,ui)]:
    tmp=path.with_suffix(path.suffix+'.v20tmp')
    tmp.write_text(data,encoding='utf-8')
    tmp.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
for path in [auto_path,panel_path,ui_path]:
    path.with_suffix(path.suffix+'.v20tmp').replace(path)
print('Включён рандомный подбор шаблона на регистрации и автоматическая публикация.')
PY_PATCH
then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_autotemplate.py" ]]; then cp -a "$BACKUP/wpo_node_autotemplate.py" "$AUTO"; else rm -f "$AUTO"; fi
  echo 'Обновление не применено, исходный код восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$PANEL" "$UI" "$AUTO" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_autotemplate.py" ]]; then cp -a "$BACKUP/wpo_node_autotemplate.py" "$AUTO"; else rm -f "$AUTO"; fi
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или запуска панели. Выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v20 готов: шаблоны выбираются случайно без повторов, пока есть свободные.'
echo 'Новые ноды получают сайт автоматически после регистрации. Старые ноды не изменяются.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main не затронут.'
__WPO_EMBED_V20_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v21-install.sh" <<'__WPO_EMBED_V21_END_736a4b__'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-server-icon-v19' "$UI" || { echo 'Нужен Nodes Lab v19 или новее. Изменений нет.'; exit 1; }
if grep -Fq '/* wpo-node-heading-v21 */' "$UI"; then
    echo 'Nodes Lab v21 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v21-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')
def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: ожидается 1 совпадение, найдено {n}; файл не изменён.')
    src=src.replace(old,new,1)

# Earlier live UI edits may already have removed the subtitle; in that case
# v21 must still apply the final spacing and alignment.
heading='<h2>⚙️ Управление нодами</h2>'
if src.count(heading)!=1 or 'def nodes_ui(' not in src:
    raise RuntimeError('Заголовок нод не найден однозначно. Файл не изменён.')
import re
subtitle_re=r'<p(?:\s[^>]*)?>\s*Подключённые серверы и состояние установок\s*</p>'
# Keep any other page or help text untouched: this is restricted to nodes_ui.
start=src.index('def nodes_ui(')
end=src.index('\n\nCSS +=',start)
section=src[start:end]
section,removed=re.subn(subtitle_re,'',section)
if removed>1:
    raise RuntimeError('У подписи найдено более одного совпадения; файл не изменён.')
src=src[:start]+section+src[end:]
print('Подпись раздела:', 'удалена' if removed else 'уже отсутствовала')

css="""
/* wpo-node-heading-v21 */
/* Align heading to the first statistics card left edge. */
.wpo-nodes-page .wpo-nodes-toolbar > div:first-child{
    margin-left:0;
    padding-left:0;
    min-width:0;
}
.wpo-nodes-page .wpo-nodes-toolbar .eyebrow{margin-bottom:0}
.wpo-nodes-page .wpo-nodes-toolbar h2{
    margin:10px 0 0;
    line-height:1.3;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Отступ и левое выравнивание заголовка')

compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes21tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Подпись удалена; заголовок ниже и выровнен по левому краю блока «В сети».')
PY_PATCH
then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    echo 'Ошибка правки. Исходный файл восстановлен.'
    exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    echo 'Ошибка проверки или запуска. Выполнен откат.'
    exit 1
fi
echo 'Nodes Lab v21: подпись удалена, заголовок выровнен.'
echo "Резервная копия: $BACKUP"
echo 'Работа нод и ветка GitHub main не изменены.'
__WPO_EMBED_V21_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v22-install.sh" <<'__WPO_EMBED_V22_END_736a4b__'
#!/usr/bin/env bash
# Nodes Lab v22: horizontal continuous node list and correctly sized install card.
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите на основном VPS с WPO от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Отсутствует $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба WPO не найдена.'; exit 1; }
grep -Fq '/* wpo-node-heading-v21 */' "$UI" || { echo 'Сначала нужен Nodes Lab v21.'; exit 1; }

if grep -Fq '/* wpo-node-pending-row-v22 */' "$UI"; then
  echo 'Nodes Lab v22 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v22-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,what):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{what}: найдено {count} совпадений, ожидалось одно; исходник не изменён.')
    src=src.replace(old,new,1)

# Install card uses the SAME three visual rows as an ordinary node.
# The long live progress text moves out of the header to the compact lower row.
old_head=(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span>'
    '<div class="wpo-node-label"><h3>Установка</h3>'
    '<small data-node-progress="{esc(uid)}" title="{esc(detail)}">{esc(detail)}</small></div>'
    '<div class="wpo-node-head-tools">{status(uid,state)}'
    '<div class="wpo-node-actions">{delete}</div></div></div>'
)
new_head=(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span>'
    '<div class="wpo-node-label"><h3>Установка</h3></div>{status(uid,state)}</div>'
)
once(old_head,new_head,'Заголовок ожидающей ноды')

globe_svg=(
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9"/>'
    '<path d="M3 12h18M12 3c2.8 2.4 4 5.4 4 9s-1.2 6.6-4 9'
    'M12 3c-2.8 2.4-4 5.4-4 9s1.2 6.6 4 9"/>'
    '</svg>'
)
old_body=(
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">{icon("link")}'
    '<span data-node-domain="{esc(uid)}">{esc(domain or "Домен определяется")}</span>'
    '</div></div>'
)
new_body=(
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">'
    '<span class="wpo-domain-mark">'+globe_svg+'</span>'
    '<span data-node-domain="{esc(uid)}">{esc(domain or "Домен определяется")}</span></div>'
    '<div class="wpo-node-meta-row">'
    '<p class="wpo-node-template wpo-node-install-detail" data-node-progress="{esc(uid)}"'
    ' title="{esc(detail)}">{esc(detail)}</p>'
    '<div class="wpo-node-actions">{delete}</div></div></div>'
)
once(old_body,new_body,'Домен и нижняя полоса ожидающей ноды')

css=r"""
/* wpo-node-pending-row-v22 */
/* Nodes always fill the first available slot from left to right. */
.wpo-nodes-page .wpo-node-grid{
    display:grid;
    grid-template-columns:repeat(5,minmax(0,1fr));
    gap:9px;
    grid-auto-flow:row;
    align-items:stretch;
    justify-content:stretch;
    min-width:0;
}
@media(max-width:850px){
    .wpo-nodes-page .wpo-node-grid{
        grid-template-columns:repeat(3,minmax(0,1fr));
    }
}
@media(max-width:700px){
    .wpo-nodes-page .wpo-node-grid{
        grid-template-columns:minmax(0,1fr);
    }
}
/* Match installed-node card dimensions and keep everything inside the card. */
.wpo-nodes-page .wpo-pending-node{
    display:grid;
    grid-template-rows:40px minmax(0,1fr);
    row-gap:5px;
    min-height:140px;
    padding:10px 12px;
    min-width:0;
    overflow:hidden;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head{
    display:flex;
    align-items:center;
    min-height:40px;
    min-width:0;
    gap:7px;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-label{
    display:flex;
    min-width:0;
    flex:1 1 auto;
    overflow:hidden;
    white-space:nowrap;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-label h3{
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
    max-width:100%;
    font-size:12px;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head>.wpo-node-status{
    margin-left:auto;
    flex:0 0 auto;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-body{
    display:grid;
    grid-template-rows:21px minmax(0,1fr);
    gap:7px;
    align-content:stretch;
    align-self:stretch;
    padding:11px 0 0;
    min-width:0;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-domain{
    display:grid;
    grid-template-columns:14px minmax(0,1fr);
    align-items:center;
    column-gap:7px;
    min-width:0;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-domain .wpo-domain-mark{
    color:#38bdf8;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    line-height:1;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-meta-row{
    min-width:0;
    overflow:hidden;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-install-detail{
    margin:0;
    display:block;
    flex:1 1 0;
    min-width:0;
    max-width:calc(100% - 36px);
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
    text-align:left;
    font-size:10.5px;
    color:var(--muted);
}
.wpo-nodes-page .wpo-pending-node .wpo-node-actions{
    flex:0 0 auto;
    margin-left:auto;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Сетка и компактный дизайн временной ноды')
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes22tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Ноды идут слева направо; третья карточка в первом ряду, установка без вылезающего текста.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'v22 не применился; восстановлен исходный интерфейс.'
  exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или перезапуска; выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v22 готов: слева направо, одинаковые карточки, компактная установка.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main, Node Agent и работа протоколов не изменены.'
__WPO_EMBED_V22_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v23-install.sh" <<'__WPO_EMBED_V23_END_736a4b__'
#!/usr/bin/env bash
# Nodes Lab v23: refresh the Node Agent installer served by "Добавить ноду".
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите на основном VPS WPO от root.'; exit 1; }
[[ -s "$AGENT" ]] || { echo 'Установщик ноды не найден. Сначала установите Nodes Lab v22.'; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Основная панель WPO не найдена.'; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Ожидается Node Agent 0.2.'; exit 1; }

if grep -Fq 'wpo-node-agent-reinstall-v23' "$AGENT"; then
    echo 'Nodes Lab v23 уже установлен.'
    exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 15 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
[[ -s "$TMP" ]] || { echo 'Не удалось получить установщик Node Agent.'; exit 1; }

for token in 'wpo-node-agent-reinstall-v23' \
             'systemctl restart wpp-node-agent.service' \
             'Регистрация: HTTP %d' \
             'wpp-api/v1/status' \
             '__WPO_CONTROLLER_ENROLL_URL__' \
             '__WPO_CONTROLLER_STATUS_URL__' \
             'PY_VALIDATE_EMAIL'; do
    grep -Fq "$token" "$TMP" || { echo "Проверка нового установщика не прошла: $token"; exit 1; }
done
bash -n "$TMP" || { echo 'Синтаксис установщика Node Agent некорректен.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v23-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"

if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
    cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
    echo 'Ошибка обновления: предыдущий установщик восстановлен.'
    exit 1
fi

echo 'Nodes Lab v23: установщик из кнопки «Добавить ноду» обновлён.'
echo 'Повторная установка перезапускает Node Agent с новым ключом API.'
echo 'При ошибке регистрации показывается причина, возвращённая панелью.'
echo "Резервная копия: $BACKUP"
echo 'Работающие ноды не изменены. Перезапуск основной панели не нужен. GitHub main не затронут.'
__WPO_EMBED_V23_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v24-install.sh" <<'__WPO_EMBED_V24_END_736a4b__'
#!/usr/bin/env bash
# Nodes Lab v24 — center spinner/error ring within installation flag tile.
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба $SERVICE"; exit 1; }
grep -Fq '/* wpo-node-pending-row-v22 */' "$UI" || { echo 'Нужен Nodes Lab v22 или новее.'; exit 1; }

if grep -Fq '/* wpo-node-indicator-center-v24 */' "$UI"; then
    echo 'Nodes Lab v24 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v24-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
anchor="'''\n    js=r'''(()=>{const path=__PATH__"
if src.count(anchor)!=1:
    raise RuntimeError('Не найдено единственное место для стилей нод; интерфейс не изменён.')
if src.count('/* wpo-node-pending-row-v22 */')!=1:
    raise RuntimeError('Не найден базовый стиль v22; интерфейс не изменён.')

css=r"""
/* wpo-node-indicator-center-v24 */
/* Keep the tile size untouched: only center the circular spinner / error icon. */
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag {
    display:grid;
    place-items:center;
    align-items:center;
    justify-items:center;
    padding:0;
    line-height:0;
    position:relative;
    box-sizing:border-box;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag::after {
    display:grid;
    place-items:center;
    justify-self:center;
    align-self:center;
    width:20px;
    height:20px;
    box-sizing:border-box;
    margin:0;
    flex:none;
    border-radius:50%;
    transform-origin:50% 50%;
}
.wpo-nodes-page .wpo-pending-node:has(.wpo-node-status.error) .wpo-node-flag::after {
    display:grid;
    place-items:center;
    font:700 12px/1 system-ui,sans-serif;
    text-align:center;
    animation:none;
}
"""
updated=src.replace(anchor, css+"\n"+anchor, 1)
compile(updated,str(p),'exec')
tmp=p.with_suffix('.py.nodes24tmp')
tmp.write_text(updated,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Индикатор установки и красный значок ошибки выровнены по центру квадрата.')
PY_PATCH
then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    echo 'Ошибка правки, исходный интерфейс восстановлен.'
    exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    echo 'Ошибка проверки или запуска. Исходный интерфейс восстановлен.'
    exit 1
fi
echo 'Nodes Lab v24 установлен. Кружочки строго по центру; размеры карточек не менялись.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main и установщик Node Agent не изменены.'
__WPO_EMBED_V24_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v25-install.sh" <<'__WPO_EMBED_V25_END_736a4b__'
#!/usr/bin/env bash
# Nodes Lab v25 — always publish a chosen website immediately on Save.
set -Eeuo pipefail
umask 077
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
AUTO="$APP/wpo_node_autotemplate.py"
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запускайте на основном VPS WPO от root.'; exit 1; }
for file in "$PANEL" "$UI" "$AUTO"; do [[ -s "$file" ]] || { echo "Файл не найден: $file"; exit 1; }; done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Основная служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-auto-v20' "$PANEL" || { echo 'Требуется Nodes Lab v20 или новее.'; exit 1; }
grep -Fq '/* wpo-node-divider-v18' "$UI" || { echo 'Нужен компактный интерфейс v18 или новее.'; exit 1; }

if grep -Fq '# wpo-node-template-save-v25' "$PANEL" &&
   grep -Fq '# wpo-node-template-sync-v25' "$AUTO" &&
   grep -Fq 'Шаблон: {esc(site_name)}' "$UI"; then
    echo 'Nodes Lab v25 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v25-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
for file in "$PANEL" "$UI" "$AUTO"; do cp -a "$file" "$BACKUP/$(basename "$file")"; done

if ! python3 - "$PANEL" "$UI" "$AUTO" <<'PY_PATCH'
from pathlib import Path
import sys
panel_path, ui_path, auto_path = map(Path, sys.argv[1:])
panel=panel_path.read_text(encoding='utf-8')
ui=ui_path.read_text(encoding='utf-8')
auto=auto_path.read_text(encoding='utf-8')

start_marker='                elif operation=="edit":\n'
end_marker='                elif operation=="rename":\n'
if panel.count(start_marker)!=1:
    raise RuntimeError('Не найден единственный обработчик редактирования ноды; файлы не изменены.')
start=panel.index(start_marker)
end=panel.find(end_marker,start)
if end==-1:
    raise RuntimeError('Не найдена граница обработчика ноды; файлы не изменены.')
previous=panel[start:end]
for expected in (
    'site-template',
    'selected["site_template_id"]=template_id',
    'selected.pop("auto_site_template_id",None)',
    'node_api.save_nodes(NODES_FILE,nodes)',
):
    if expected not in previous:
        raise RuntimeError('Неожиданная версия обработчика '+expected+'; файлы не изменены.')

new_handler='''                elif operation=="edit":
                    # wpo-node-template-save-v25: every Save publishes to the remote agent,
                    # including re-selecting the currently stored template.
                    # Lock with the auto-template worker to avoid a stale auto-push.
                    with wpo_node_auto.registry_lock:
                        nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")
                        selected=next((node for node in nodes if node.get("id")==uid),None)
                        if selected is None: raise node_api.NodeError("Нода не найдена.")
                        new_name=node_api.clean_text(form.get("name",""),"Название ноды",80)
                        template_id=str(form.get("site_template","")).strip()
                        presets=all_presets()
                        allowed={str(item.get("id")):item for item in presets if isinstance(item,dict)}
                        if template_id and template_id not in allowed:
                            raise node_api.NodeError("Шаблон не найден в настройках панели.")
                        # Capabilities are advertised by the live agent; older node
                        # registrations did not persist them in the controller registry.
                        # The authenticated POST itself is the authoritative check.
                        if template_id:
                            try:
                                payload=wpo_node_auto._payload(presets,template_id)
                            except (ValueError,OSError) as exc:
                                raise node_api.NodeError("Не удалось подготовить шаблон: "+str(exc)) from exc
                        else:
                            payload={"template_id":"","html":"","assets":[]}
                        try:
                            response=node_api.request(
                                selected,"POST",node_api.API_PREFIX+"/site-template",payload,timeout=35
                            )
                        except node_api.NodeError as exc:
                            raise node_api.NodeError("Сайт ноды не обновлён: "+str(exc)) from exc
                        if str(response.get("template_id",""))!=template_id:
                            raise node_api.NodeError("Нода не подтвердила применение выбранного шаблона.")
                        # Save the label only after the website was actually accepted.
                        selected["site_template_id"]=template_id
                        selected.pop("auto_site_template_id",None)
                        selected["name"]=new_name
                        node_api.save_nodes(NODES_FILE,nodes)
                    if self.headers.get("X-WPP-Async","")=="1":
                        self.send_json({"ok":True,"site_template_id":template_id}); return
'''
panel=panel[:start]+new_handler+panel[end:]

# An auto-assign worker can otherwise overwrite a manually saved page between
# its initial registry check and its subsequent POST. Keep its POST under the
# same registry lock as the manual handler; the lock is reentrant.
old_worker='''                        node_copy = dict(selected)
                    payload = _payload(all_presets(), tid)
                    node_api.request(
                        node_copy, "POST", node_api.API_PREFIX + "/site-template",
                        payload, timeout=30,
                    )
'''
new_worker='''                        # wpo-node-template-sync-v25: serialize auto and manual publishing.
                        payload = _payload(all_presets(), tid)
                        node_api.request(
                            dict(selected), "POST", node_api.API_PREFIX + "/site-template",
                            payload, timeout=30,
                        )
'''
if auto.count(old_worker)!=1:
    raise RuntimeError('Не найдена ожидаемая фоновая отправка; файлы не изменены.')
auto=auto.replace(old_worker,new_worker,1)

old_title='<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p>'
new_title='<p class="wpo-node-template" title="Шаблон: {esc(site_name)}">{icon("settings")} Шаблон: {esc(site_name)}</p>'
if ui.count(old_title)!=1:
    raise RuntimeError('Не найдена единственная подпись шаблона ноды; файлы не изменены.')
ui=ui.replace(old_title,new_title,1)

for path,content in [(panel_path,panel),(ui_path,ui),(auto_path,auto)]:
    compile(content,str(path),'exec')
# All validations complete. Install using temporary files on the same filesystem.
staged=[]
for path,content in [(panel_path,panel),(ui_path,ui),(auto_path,auto)]:
    temporary=path.with_suffix('.py.nodes25tmp')
    temporary.write_text(content,encoding='utf-8')
    temporary.chmod(path.stat().st_mode & 0o777)
    staged.append((temporary,path))
for temporary,path in staged:
    temporary.replace(path)
print('Сохранение любого шаблона теперь публикует сайт сразу; подписи карточек обновлены.')
PY_PATCH
then
    for name in panel.py wpp_ui.py wpo_node_autotemplate.py; do cp -a "$BACKUP/$name" "$APP/$name"; done
    echo 'Изменения не применены. Исходные файлы восстановлены.'
    exit 1
fi

if ! python3 -m py_compile "$PANEL" "$UI" "$AUTO" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    for name in panel.py wpp_ui.py wpo_node_autotemplate.py; do cp -a "$BACKUP/$name" "$APP/$name"; done
    systemctl restart "$SERVICE" || true
    echo 'Проверка завершилась ошибкой: предыдущая версия восстановлена.'
    exit 1
fi

echo 'Nodes Lab v25 установлен: каждый выбор шаблона применяется при сохранении.'
echo 'Автошаблоны не могут перезаписать ручной выбор.'
echo 'В карточках отображается «Шаблон: ...».'
echo "Резервная копия: $BACKUP"
echo 'Существующие ноды, VPN и ветка GitHub main не изменены.'
__WPO_EMBED_V25_END_736a4b__
cat > "$STAGE/wpo-nodes-lab-v26-install.sh" <<'__WPO_EMBED_V26_END_736a4b__'
#!/usr/bin/env bash
# Nodes Lab v26 — center the yellow installation spinner and red error icon.
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Не найдена служба панели WPO.'; exit 1; }
grep -Fq '/* wpo-node-indicator-center-v24 */' "$UI" || {
    echo 'Сначала установите Nodes Lab v24 или новее.'; exit 1;
}
if grep -Fq '/* wpo-node-spinner-center-v26 */' "$UI"; then
    echo 'Nodes Lab v26 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v26-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')

# The actual issue: the old diamond glyph becomes an anonymous *first*
# CSS-grid item (even with font-size:0); ::after is laid out in a second row.
# Remove it entirely so the animated ring is the only item in the flag tile.
old='<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3></div>{status(uid,state)}</div>'
new='<div class="wpo-node-card-head"><span class="wpo-node-flag" aria-hidden="true"></span><div class="wpo-node-label"><h3>Установка</h3></div>{status(uid,state)}</div>'
if src.count(old)!=1:
    raise RuntimeError('Не найдена единственная карточка установки версии v22. Файл не изменён.')
src=src.replace(old,new,1)

# The spinner rotates using transform; using flex centering on the PARENT
# means transform rotation cannot override a translate-based centering.
css=r"""
/* wpo-node-spinner-center-v26 */
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag{
    display:flex;
    align-items:center;
    justify-content:center;
    padding:0;
    line-height:0;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head > .wpo-node-flag::after{
    position:static;
    display:block;
    flex:0 0 20px;
    width:20px;
    height:20px;
    margin:0;
    box-sizing:border-box;
    transform-origin:center center;
}
.wpo-nodes-page .wpo-pending-node:has(.wpo-node-status.error) .wpo-node-card-head > .wpo-node-flag::after{
    display:grid;
    place-items:center;
    font:700 12px/1 system-ui,sans-serif;
    animation:none;
}
"""
anchor="'''\n    js=r'''(()=>{const path=__PATH__"
if src.count(anchor)!=1:
    raise RuntimeError('Не найдено единственное место стилей карточек. Файл не изменён.')
src=src.replace(anchor,css+"\n"+anchor,1)
compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes26tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Кружок загрузки и ошибка точно по центру: лишний символ из карточки удалён.')
PY_PATCH
then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    echo 'Ошибка правки. Исходный интерфейс восстановлен.'
    exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    echo 'Ошибка проверки или перезапуска. Интерфейс восстановлен.'
    exit 1
fi
echo 'Nodes Lab v26 установлен: жёлтый и красный индикаторы по центру.'
echo "Резервная копия: $BACKUP"
echo 'Размеры карточек, ноды, шаблоны, VPN и ветка GitHub main не менялись.'
__WPO_EMBED_V26_END_736a4b__

for v in $(seq 1 26); do
    if [[ "$v" == 1 ]]; then file="wpo-nodes-lab-install.sh"; else file="wpo-nodes-lab-v$v-install.sh"; fi
    [[ -s "$STAGE/$file" ]] || die "Нет встроенного этапа Nodes Lab: $file"
    bash -n "$STAGE/$file" || die "Ошибка синтаксиса Nodes Lab: $file"
done

for file in wpo-node-agent-install-v2.sh wpo-node-geo-v13.py wpo-node-autotemplate-v20.py; do
    if (( USE_PACKAGE )); then
        [[ -s "$PACKAGE_DIR/$file" ]] || die "Неполный пакет: $file"
        cp "$PACKAGE_DIR/$file" "$STAGE/$file"
    else
        curl -4fsSL --retry 3 --connect-timeout 15 --max-time 80 "$BASE/$file" -o "$STAGE/$file"
    fi
    [[ -s "$STAGE/$file" ]] || die "Не удалось получить $file"
done
bash -n "$STAGE/wpo-node-agent-install-v2.sh"
python3 -m py_compile "$STAGE/wpo-node-geo-v13.py" "$STAGE/wpo-node-autotemplate-v20.py"

# Freeze nested downloads to the same snapshot, not the moving nodes-lab tip.
python3 - "$STAGE" "$REF" <<'PY_PIN'
from pathlib import Path
import sys
root, ref=Path(sys.argv[1]),sys.argv[2]
old='https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/'
new='https://raw.githubusercontent.com/TonyMaster14/web-panel-online/'+ref+'/'
for version in (2,10,11,12,13,20,23):
    path=root/('wpo-nodes-lab-v'+str(version)+'-install.sh')
    content=path.read_text(encoding='utf-8')
    if old not in content:
        raise RuntimeError('Ожидаемый адрес не найден: '+path.name)
    path.write_text(content.replace(old,new),encoding='utf-8')
PY_PIN

# The complete installation package already carries the exact helper files.
# Never download the same Node Agent/geolocation/template files again inside
# the legacy nested steps: use the checked local snapshot instead.
python3 - "$STAGE" <<'PY_LOCAL_DEPS'
from pathlib import Path
import re, shlex, sys
root=Path(sys.argv[1])
assets={
    2:'wpo-node-agent-install-v2.sh',
    10:'wpo-node-agent-install-v2.sh',
    11:'wpo-node-agent-install-v2.sh',
    12:'wpo-node-agent-install-v2.sh',
    13:'wpo-node-geo-v13.py',
    20:'wpo-node-autotemplate-v20.py',
    23:'wpo-node-agent-install-v2.sh',
}
pattern=re.compile(r'''(?m)^curl -4fsSL --retry 3 --connect-timeout \d+ (?:\\\n[ \t]*)?['"]https://raw\.githubusercontent\.com/TonyMaster14/web-panel-online/[^'"\n]+/(?P<asset>wpo-node-agent-install-v2\.sh|wpo-node-geo-v13\.py|wpo-node-autotemplate-v20\.py)['"] -o "\$TMP"$''')
for version,asset in assets.items():
    path=root/f'wpo-nodes-lab-v{version}-install.sh'
    original=path.read_text(encoding='utf-8')
    packaged=root/asset
    if not packaged.is_file() or packaged.stat().st_size==0:
        raise RuntimeError('Нет упакованного файла: '+asset)
    found=list(pattern.finditer(original))
    if len(found)!=1 or found[0].group('asset')!=asset:
        raise RuntimeError('Неожиданная повторная загрузка: '+path.name)
    replacement='cp -- '+shlex.quote(str(packaged))+' "$TMP"'
    path.write_text(pattern.sub(lambda m:replacement,original),encoding='utf-8')
print('Вспомогательные файлы Node Agent берутся из локального пакета.')
PY_LOCAL_DEPS

# A clean installation already has a healthy running controller. Apply the
# checked source patches without restarting it after every intermediate edit.
# The controller is restarted once when the complete final code is ready.
# Standalone upgrades retain the original per-version restart behavior.
BATCH_RESTART=0
if [[ "${WPO_NODES_BATCH_RESTART:-0}" == 1 ]]; then
    BATCH_RESTART=1
    python3 - "$STAGE" <<'PY_BATCH'
from pathlib import Path
import sys
root=Path(sys.argv[1])
old='systemctl restart "$SERVICE"'
changed=0
for script in sorted(root.glob('wpo-nodes-lab*-install.sh')):
    content=script.read_text(encoding='utf-8')
    if old not in content:
        continue
    # Only defer the controller restart. Source checks and other services
    # are unchanged. The release-level rollback still restarts on failure.
    script.write_text(content.replace(old,'true'),encoding='utf-8')
    changed+=1
if changed < 20:
    raise SystemExit('Неожиданная версия Nodes Lab: пакетное ускорение не применено.')
print('Nodes Lab: один итоговый перезапуск вместо повторных перезапусков.')
PY_BATCH
    for file in "$STAGE"/wpo-nodes-lab*-install.sh; do
        bash -n "$file" || die "Неверный синтаксис: $file"
    done
fi

BACKUP="$DATA/nodes-lab-release-v26-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
for name in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py wpp-node-agent-install.sh wpo_node_geo.py wpo_node_autotemplate.py; do
    if [[ -f "$APP/$name" ]]; then cp -a "$APP/$name" "$BACKUP/$name"
    else : > "$BACKUP/absent-$name"
    fi
done

# Show progress for the actual source stage being applied, not a timed guess.
# Versions 10-12 are carried by the final combined Node Agent installer.
wpo_node_stage(){
    local version="$1" percent
    [[ -n "${WPO_UI_PROGRESS_FILE:-}" && -f "$WPO_UI_PROGRESS_FILE" ]] || return 0
    percent=$((80 + version*18/26))
    printf '%s\tУстановка нод\n' "$percent" > "$WPO_UI_PROGRESS_FILE"
}
apply(){
    local script="$1" file="$2" marker="$3" version=1
    if [[ "$script" =~ -v([0-9]+)-install\.sh$ ]]; then
        version="${BASH_REMATCH[1]}"
    fi
    if grep -Fq -- "$marker" "$file" 2>/dev/null; then
        echo "✓ Уже есть: $script"
    else
        echo "→ Применяю: $script"
        TOUCHED=1
        bash "$STAGE/$script"
    fi
    wpo_node_stage "$version"
}
apply wpo-nodes-lab-install.sh "$PANEL" "def wpo_pending_load"
apply wpo-nodes-lab-v2-install.sh "$UI" "wpo-node-card-head"
apply wpo-nodes-lab-v3-install.sh "$UI" "# wpo-node-compact-v3"
apply wpo-nodes-lab-v4-install.sh "$UI" "# wpo-node-title-v4"
apply wpo-nodes-lab-v5-install.sh "$UI" "# wpo-node-title-v5"
apply wpo-nodes-lab-v6-install.sh "$UI" "# wpo-node-compact-v6"
apply wpo-nodes-lab-v7-install.sh "$UI" "# wpo-node-width-v7"
apply wpo-nodes-lab-v8-install.sh "$UI" "wpo-node-spinner-v8"
apply wpo-nodes-lab-v9-install.sh "$UI" "# wpo-node-aligned-v9"

# The final v12 agent installer includes all v10–v12 email fixes.
# It lives on the controller, not on already enrolled remote VPSs.
if ! cmp -s "$STAGE/wpo-node-agent-install-v2.sh" "$AGENT"; then
    echo '→ Обновляю установщик Node Agent до финальной версии v12'
    TOUCHED=1
    install -m 0700 "$STAGE/wpo-node-agent-install-v2.sh" "$AGENT"
fi
wpo_node_stage 12

apply wpo-nodes-lab-v13-install.sh "$PANEL" "# wpo-node-country-v13"
apply wpo-nodes-lab-v14-install.sh "$UI" "# wpo-node-visual-v14"
apply wpo-nodes-lab-v15-install.sh "$UI" "# wpo-node-polish-v15"
apply wpo-nodes-lab-v16-install.sh "$UI" "# wpo-node-finetune-v16"
apply wpo-nodes-lab-v17-install.sh "$UI" "# wpo-node-globe-v17"
apply wpo-nodes-lab-v18-install.sh "$UI" "# wpo-node-divider-v18"
apply wpo-nodes-lab-v19-install.sh "$UI" "# wpo-node-server-icon-v19"
apply wpo-nodes-lab-v20-install.sh "$PANEL" "# wpo-node-auto-v20"
apply wpo-nodes-lab-v21-install.sh "$UI" "/* wpo-node-heading-v21 */"
apply wpo-nodes-lab-v22-install.sh "$UI" "/* wpo-node-pending-row-v22 */"
apply wpo-nodes-lab-v23-install.sh "$AGENT" "wpo-node-agent-reinstall-v23"
apply wpo-nodes-lab-v24-install.sh "$UI" "/* wpo-node-indicator-center-v24 */"
apply wpo-nodes-lab-v25-install.sh "$PANEL" "# wpo-node-template-save-v25"
apply wpo-nodes-lab-v26-install.sh "$UI" "/* wpo-node-spinner-center-v26 */"

# v27 test bridge: keep remote Node Agent support distinct from the 26
# already validated UI stages. This is bundled with the branch's package
# and never modifies unrelated node websites or subscriber keys.
if [[ -s "$PACKAGE_DIR/wpo-node-controller-vpn.sh" ]] &&
   ! grep -Fq '# wpo-vpn-controller-v27' "$PANEL"; then
    TOUCHED=1
    WPO_NODES_VPN_DURING_INSTALL=1 WPO_NODES_BATCH_RESTART=1 \
        bash "$PACKAGE_DIR/wpo-node-controller-vpn.sh"
fi

# v28 test: the UI and expiry protection are installed with the panel,
# so the user never needs a separate patch on the additional node VPS.
if [[ -s "$PACKAGE_DIR/wpo_v28_apply.py" && -s "$PACKAGE_DIR/wpo_user_v28.py" ]]; then
    TOUCHED=1
    python3 "$PACKAGE_DIR/wpo_v28_apply.py" --app "$APP" \
        --manager /usr/local/sbin/web-proxy-panelctl \
        --helper "$PACKAGE_DIR/wpo_user_v28.py"
else
    die 'В тестовом пакете отсутствует интерфейс пользователей v28.'
fi

for file in "$PANEL" "$UI" "$GEO" "$AUTO"; do [[ -s "$file" ]] || die "Отсутствует файл: $file"; done
# Validate the final generated-node installer and controller feature set.
grep -Fq 'node-agent-installer.sh' "$PANEL" || die 'Нет маршрута установщика ноды.'
grep -Fq '# wpo-node-country-v13' "$PANEL" || die 'Нет геолокации нод.'
grep -Fq '# wpo-node-auto-v20' "$PANEL" || die 'Нет автоматического выбора шаблона.'
grep -Fq '/* wpo-node-heading-v21 */' "$UI" || die 'Не применён интерфейс v21.'
grep -Fq '/* wpo-node-pending-row-v22 */' "$UI" || die 'Не применена компактная сетка v22.'
grep -Fq 'site-template' "$AGENT" || die 'Установщик ноды не поддерживает шаблоны.'
grep -Fq 'for EMAIL_ATTEMPT in 1 2 3' "$AGENT" || die 'Установщик ноды не обновлён до итоговой версии.'
grep -Fq 'wpo-node-agent-reinstall-v23' "$AGENT" || die 'Исправление повторной установки ноды v23 отсутствует.'
grep -Fq '/* wpo-node-indicator-center-v24 */' "$UI" || die 'Центровка индикатора v24 отсутствует.'
grep -Fq '# wpo-node-template-save-v25' "$PANEL" || die 'Мгновенная публикация шаблона v25 отсутствует.'
grep -Fq '# wpo-node-template-sync-v25' "$AUTO" || die 'Синхронизация шаблонов v25 отсутствует.'
grep -Fq 'Шаблон: {esc(site_name)}' "$UI" || die 'Подпись шаблона v25 отсутствует.'
grep -Fq '/* wpo-node-spinner-center-v26 */' "$UI" || die 'Центровка жёлтого/красного индикатора v26 отсутствует.'
grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$AGENT" || die 'Установщик ноды не связан с основной панелью.'
python3 -m py_compile "$PANEL" "$UI" "$GEO" "$AUTO"
bash -n "$AGENT"
if (( BATCH_RESTART && TOUCHED )); then
    echo '→ Перезапускаю панель один раз после всех правок Nodes Lab'
    systemctl reset-failed "$SERVICE" 2>/dev/null || true
    systemctl restart "$SERVICE" || die 'Не удалось запустить панель после установки Nodes Lab.'
fi
# A service can be reported active before Python has bound the HTTP port.
# Only accept the finished controller after its real localhost health route responds.
PANEL_ROUTE="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
[[ "$PANEL_ROUTE" =~ ^/panel-[a-z0-9-]{3,64}$ ]] || die 'Некорректный адрес панели.'
READY=0
for attempt in $(seq 1 12); do
    if systemctl is-active --quiet "$SERVICE" &&
       curl -fsS --max-time 3 "http://127.0.0.1:8090${PANEL_ROUTE}/__health" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done
(( READY == 1 )) || die 'Панель не отвечает на локальный health-запрос после настройки Nodes Lab.'
echo
echo '✓ Компоненты ноды WPO установлены/проверены.'
echo "✓ Фиксированная версия: $REF"
echo "✓ Резервная копия до обновления: $BACKUP"
echo '✓ Геолокация, флаги, индикаторы по центру и мгновенный выбор шаблонов сайтов сохранены.'
echo '✓ Установщик новой ноды включает Xray и VPN-федерацию: VLESS XHTTP + Hysteria2.'
echo 'Другие протоколы отображаются в каталоге и будут активированы после серверной реализации.'
