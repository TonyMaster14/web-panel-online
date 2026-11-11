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
