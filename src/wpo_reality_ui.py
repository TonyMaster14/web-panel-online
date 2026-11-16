"""Compact node REALITY settings, shared by node and connection views."""
from html import escape
import json
import wpo_reality as reality

def selected_preset(profile):
    # An older saved target can remain functional until explicitly changed;
    # never silently replace its SNI when the dialog is opened.
    value=str(profile.get('preset',''))
    sni=str(profile.get('sni',''))
    if value in reality.PRESETS and reality.PRESETS[value][1]==sni:
        return value
    return next((key for key,(_,host) in reality.PRESETS.items() if host==sni), 'custom')

def editor(path, csrf, nodes=(), fleet=False):
    try: profile=reality.read_profile()
    except (OSError,ValueError): return ''
    e=lambda x:escape(str(x),quote=True)
    chosen=selected_preset(profile)
    options=''.join('<option value="'+key+'"'+(' selected' if chosen==key else '')+'>'+title+' · '+domain+'</option>' for key,(title,domain) in reality.PRESETS.items())
    options+='<option value="custom"'+(' selected' if chosen=='custom' else '')+'>Свой домен</option>'
    node_options='<option value="local">Основная нода</option>'+''.join('<option value="'+e(n['id'])+'">'+e(n.get('name') or n.get('url') or n['id'])+'</option>' for n in nodes)
    scope=('<label>Применение<input value="Вся сеть · основная и '+str(len(nodes))+' дополнительных нод" readonly aria-readonly="true"></label><input type="hidden" name="node_id" value="local">' if fleet else '<label>Нода<select name="node_id">'+node_options+'</select></label>')
    choices=''.join('<button type="button" role="option" data-reality-choice="'+key+'" aria-selected="'+('true' if chosen==key else 'false')+'">'+e(title)+'<small>'+e(domain)+'</small></button>' for key,(title,domain) in reality.PRESETS.items())
    choices+='<button type="button" role="option" data-reality-choice="custom" aria-selected="'+('true' if chosen=="custom" else 'false')+'">Свой домен<small>Укажите SNI вручную</small></button>'
    selected_label=('Свой домен' if chosen=='custom' else reality.PRESETS[chosen][0])
    html='''<dialog id="wpoRealityDialog" class="connection-editor"><form id="wpoRealityForm">
<div class="dialog-head"><div><h2>VLESS TCP REALITY Vision</h2><small>TCP · Vision · общий внешний порт 443</small></div><button type="button" data-reality-close>×</button></div>
<input type="hidden" name="csrf" value="'''+e(csrf)+'''">
<section class="connection-pane">'''+scope+'''<label>IP-адрес<input id="wpoRealityAddress" value="'''+e(profile.get('address',''))+'''" readonly aria-readonly="true" spellcheck="false"></label>
<label>Сайт для REALITY<div class="wpo-reality-picker"><input type="hidden" name="preset" value="'''+e(chosen)+'''"><button type="button" class="wpo-reality-picker-toggle" data-reality-toggle aria-haspopup="listbox" aria-expanded="false"><span data-reality-label>'''+e(selected_label)+'''</span><span aria-hidden="true">⌄</span></button><div class="wpo-reality-picker-menu" role="listbox" data-reality-list hidden>'''+choices+'''</div></div></label>
<label>SNI<input name="sni" value="'''+e(profile['sni'])+'''" required></label>
<label>TLS fingerprint<select name="fingerprint"><option value="firefox">Mozilla Firefox</option><option value="edge">Edge · проверить в клиенте</option></select></label>
<small>Шаблон сайта на вашем домене настраивается отдельно. '''+('Сохранение применяется ко всей сети после проверки каждой ноды.' if fleet else 'Изменения применяются ко всем REALITY-подключениям этой ноды.')+''' После смены SNI обновите подписки.</small>
<details><summary>Параметры доступа</summary><label>Public key<input name="public_key" readonly value="'''+e(profile['public_key'])+'''"></label><label>Short ID<input name="short_id" readonly value="'''+e(profile['short_id'])+'''"></label></details>
<section id="wpoRealityChecks" class="wpo-reality-checks" aria-live="polite" hidden><div class="wpo-reality-checks-head"><strong>Проверка REALITY</strong><span>Реальный туннель · HTTP 204</span></div><div id="wpoRealityChecksList" class="wpo-reality-checks-list"></div></section><p id="wpoRealityResult" role="status"></p></section><div class="actions"><button type="button" data-reality-check>Проверить цель</button><button type="submit" class="primary">Сохранить</button></div></form></dialog>'''
    script='''<script>(()=>{'use strict';
const d=document.getElementById('wpoRealityDialog'),f=document.getElementById('wpoRealityForm');
const out=document.getElementById('wpoRealityResult'),area=document.getElementById('wpoRealityChecks');
const list=document.getElementById('wpoRealityChecksList'),selector=f?.querySelector('[data-reality-list]');
if(!d||!f)return;
const presets=PRESETS, allNodes=NODES, fleet=FLEET;
const actions=Array.from(f.querySelectorAll('.actions button'));
let running=false,cancelRequested=false,closeAfterStop=false,phase='idle',activeAbort=null,verified=null,restoreFailed=false;
function requestKey(nodes,request){return JSON.stringify([nodes.map(n=>n.id),request.preset,request.sni,request.fingerprint])}
function ensureActive(){if(cancelRequested)throw Error('Операция отменена пользователем')}
function requestStop(){
 if(!running){d.close();return}
 cancelRequested=true;closeAfterStop=true;
 if(activeAbort)activeAbort.abort();
 if(phase==='saving'||phase==='rollback'){
  out.textContent='Отмена запрошена. Завершаем текущий запрос и возвращаем прежние настройки. Не закрывайте вкладку.';
 }else{
  out.textContent='Проверка остановлена. Настройки не изменены.';
  d.close();
 }
}
function selected(){return presets[f.elements.preset.value]||null}
function displayPreset(){const p=selected();f.querySelector('[data-reality-label]').textContent=p?p[0]:'Свой домен';f.elements.sni.readOnly=!!p;if(p)f.elements.sni.value=p[1];selector.querySelectorAll('[data-reality-choice]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.realityChoice===f.elements.preset.value)))}
function togglePicker(open){selector.hidden=!open;f.querySelector('[data-reality-toggle]').setAttribute('aria-expanded',String(open))}
f.querySelector('[data-reality-toggle]').addEventListener('click',()=>togglePicker(selector.hidden));
selector.querySelectorAll('[data-reality-choice]').forEach(b=>b.addEventListener('click',()=>{f.elements.preset.value=b.dataset.realityChoice;displayPreset();togglePicker(false);verified=null}));
d.addEventListener('click',e=>{if(!e.target.closest('.wpo-reality-picker'))togglePicker(false)});
d.addEventListener('keydown',e=>{if(e.key==='Escape')togglePicker(false)});
d.addEventListener('cancel',e=>{if(running){e.preventDefault();requestStop()}});
function resetChecks(){area.hidden=true;list.replaceChildren();out.textContent=''}
function nodeRow(title){const row=document.createElement('div'),head=document.createElement('div'),state=document.createElement('span'),caption=document.createElement('strong'),details=document.createElement('div');
row.className='wpo-reality-check-row pending';head.className='wpo-reality-check-row-head';state.className='wpo-reality-led';
caption.textContent=title;head.append(state,caption);details.className='wpo-reality-check-row-details';row.append(head,details);list.append(row);return {row,details}}
function update(row,status,message,chips=[]){row.row.className='wpo-reality-check-row '+status;row.details.replaceChildren();if(message){const text=document.createElement('small');text.textContent=message;row.details.append(text)}for(const chip of chips){const tag=document.createElement('span');tag.className='wpo-reality-chip';tag.textContent=chip;row.details.append(tag)}}
function setRunning(value){
 running=value;actions.forEach(x=>x.disabled=value);
 f.querySelector('[data-reality-toggle]').disabled=value;
 selector.querySelectorAll('button').forEach(x=>x.disabled=value);
 if(f.elements.node_id?.tagName==='SELECT')f.elements.node_id.disabled=value;
 d.querySelector('[data-reality-close]').disabled=false;
 if(!value){phase='idle';activeAbort=null}
}
async function send(id,data,options={}){const body=new URLSearchParams({csrf:f.elements.csrf.value,node_id:id,...data});const response=await fetch(ACTION,{method:'POST',headers:{'X-WPP-Async':'1'},body,signal:options.signal});if(response.redirected)throw Error('Сессия завершена. Обновите страницу.');let result;try{result=await response.json()}catch(_){throw Error('Неверный ответ сервера')};if(!response.ok||!result.ok)throw Error(result.message||'Ошибка REALITY');return result}
function currentNodes(){return fleet?[{id:'local',name:'Основная нода'},...allNodes]:[{id:f.elements.node_id.value,name:f.elements.node_id.selectedOptions?.[0]?.textContent||'Нода'}]}
function isFullCheck(j){return Array.isArray(j.checks)&&j.checks.some(x=>x.status==='ok'&&x.name.includes('REALITY'))&&j.checks.some(x=>x.status==='ok'&&x.name.includes('HTTPS'))}
async function load(){
 if(running)return;
 resetChecks();togglePicker(false);verified=null;cancelRequested=false;closeAfterStop=false;restoreFailed=false;
 const id=fleet?'local':f.elements.node_id.value;
 setRunning(true);phase='reading';activeAbort=new AbortController();
 try{
  const j=await send(id,{read_only:'1'},{signal:activeAbort.signal});
  ensureActive();
  const p=j.profile;
  f.elements.preset.value=(presets[p.preset]&&presets[p.preset][1]===p.sni)?p.preset:(Object.entries(presets).find(([k,v])=>v[1]===p.sni)?.[0]||'custom');
  f.elements.sni.value=p.sni;f.elements.fingerprint.value=p.fingerprint;
  f.elements.public_key.value=p.public_key;f.elements.short_id.value=p.short_id;
  document.getElementById('wpoRealityAddress').value=p.address||'';
  displayPreset();if(f.elements.preset.value==='custom')f.elements.sni.value=p.sni;
 }catch(err){if(!cancelRequested)out.textContent=err.message}
 finally{setRunning(false)}
}
if(!fleet)f.elements.node_id.addEventListener('change',load);
const editForm=document.getElementById('wpoEditNodeForm');if(editForm){const b=document.createElement('button');b.type='button';b.textContent='Настройки REALITY';b.onclick=()=>{f.elements.node_id.value=editForm.elements.id.value;editForm.closest('dialog').close();d.showModal();load()};editForm.append(b)}
document.querySelectorAll('[data-reality-open]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('dialog[open]').forEach(x=>x.close());if(!fleet)f.elements.node_id.value='local';d.showModal();load()}));
d.querySelector('[data-reality-close]').addEventListener('click',requestStop);
async function execute(save){
 if(running)return;
 cancelRequested=false;closeAfterStop=false;restoreFailed=false;
 resetChecks();togglePicker(false);area.hidden=false;setRunning(true);
 const request={preset:f.elements.preset.value,sni:f.elements.sni.value.trim(),fingerprint:f.elements.fingerprint.value};
 const nodes=currentNodes(),key=requestKey(nodes,request),rows=new Map(),original=new Map(),attempted=[];
 let operationFailed=false;
 const reuse=save&&verified?.key===key&&Date.now()-verified.at<120000;
 for(const n of nodes){
  const row=nodeRow(n.name);rows.set(n.id,row);
  if(reuse)update(row,'ok','Цель уже проверена',['REALITY','HTTP 204']);
  else update(row,'pending','Ожидание проверки');
 }
 try{
  if(!reuse){
   phase='checking';activeAbort=new AbortController();
   for(const n of nodes){
    ensureActive();const row=rows.get(n.id);
    try{
     update(row,'pending','TLS 1.3 → HTTP/2 → REALITY Vision → HTTPS');
     const result=await send(n.id,{...request,check_only:'1'},{signal:activeAbort.signal});
     ensureActive();
     if(!isFullCheck(result))throw Error('Нода не подтвердила настоящий REALITY-туннель (HTTP 204)');
     update(row,'ok','Проверка пройдена',['TLS 1.3','HTTP/2','REALITY','HTTP 204'+(result.latency_ms!=null?' · '+result.latency_ms+' мс':'')]);
    }catch(err){
     if(cancelRequested)throw err;
     operationFailed=true;update(row,'error',err.message||'Ошибка проверки REALITY');
    }
   }
   activeAbort=null;
   if(operationFailed){
    verified=null;
    out.textContent=save?'Сохранение отменено: не все ноды прошли проверку. Настройки не менялись.':'Не все ноды подтвердили REALITY. Настройки не менялись.';
    return;
   }
   verified={key,at:Date.now()};
  }
  if(!save){
   out.textContent='REALITY подтверждён на '+nodes.length+' нод(ах). Теперь можно нажать «Сохранить».';
   return;
  }
  // Reuse the result of Check. Each mutating POST still tests the REALITY
  // tunnel on its node, but does not restart the UI's full preflight loop.
  // Remote nodes have separate agents. Read previous settings concurrently,
  // then apply independent writes concurrently; total latency is bounded by
  // the slowest node rather than the sum of all nodes.
  phase='reading';activeAbort=new AbortController();
  await Promise.all(nodes.map(async n=>{
   ensureActive();const row=rows.get(n.id);
   update(row,'pending','Получаем прежние параметры');
   const old=await send(n.id,{read_only:'1'},{signal:activeAbort.signal});
   original.set(n.id,old.profile);
  }));
  ensureActive();
  phase='saving';activeAbort=null;
  const changing=[];
  for(const n of nodes){
   const row=rows.get(n.id),before=original.get(n.id);
   if(before.sni===request.sni&&before.fingerprint===request.fingerprint){
    update(row,'ok','Уже сохранено',['SNI','REALITY']);
   }else changing.push(n);
  }
  // Mutating requests must NEVER be aborted halfway: Promise.allSettled
  // waits for every in-flight node before starting a compensating rollback.
  const statuses=await Promise.allSettled(changing.map(async n=>{
   ensureActive();const row=rows.get(n.id);
   attempted.push(n);update(row,'pending','Сохраняем и проверяем ноду');
   try{
    const saved=await send(n.id,{...request,check_only:'0'});
    if(!isFullCheck(saved))throw Error('Нода не подтвердила REALITY при сохранении');
    const actual=await send(n.id,{read_only:'1'});
    if(actual.profile?.sni!==request.sni||actual.profile?.fingerprint!==request.fingerprint)
      throw Error('Нода не сохранила SNI или fingerprint');
    update(row,'ok','Сохранено и подтверждено',['SNI','REALITY','HTTP 204']);
    ensureActive();
   }catch(err){update(row,'error','Ошибка сохранения: '+err.message);throw err}
  }));
  const failure=statuses.find(item=>item.status==='rejected');
  if(failure)throw failure.reason;
  ensureActive();
  verified=null;
  out.textContent='Сохранено на всех '+nodes.length+' нод(ах). Обновите подписки после смены SNI.';
 }catch(err){
  verified=null;
  if(attempted.length){
   phase='rollback';activeAbort=null;out.textContent='Возвращаем прежние настройки затронутых нод…';
   for(const n of attempted.reverse()){
    const old=original.get(n.id),row=rows.get(n.id);
    if(!old){restoreFailed=true;update(row,'error','Нет прежних параметров для отката');continue}
    try{
     update(row,'pending','Восстанавливаем прежний SNI');
     const oldPreset=(presets[old.preset]&&presets[old.preset][1]===old.sni)?old.preset:'custom';
     await send(n.id,{preset:oldPreset,sni:old.sni,fingerprint:old.fingerprint,check_only:'0'});
     const actual=await send(n.id,{read_only:'1'});
     if(actual.profile?.sni!==old.sni||actual.profile?.fingerprint!==old.fingerprint)
       throw Error('Не удалось подтвердить восстановление');
     update(row,'warning','Прежние настройки восстановлены');
    }catch(failure){
     restoreFailed=true;update(row,'error','Откат не удался: '+failure.message);
    }
   }
   out.textContent=restoreFailed?
     'Часть изменений не удалось откатить. Проверьте красные статусы перед закрытием.':
     (cancelRequested?'Сохранение отменено. Прежние настройки восстановлены.':'Сохранение прервано. Прежние настройки восстановлены.');
  }else if(!cancelRequested){
   out.textContent='Сохранение не выполнено: '+(err.message||'Ошибка соединения')+'. Настройки не изменены.';
  }
 }finally{
  setRunning(false);
  if(closeAfterStop&&!restoreFailed)d.close();
 }
}
f.addEventListener('submit',e=>{e.preventDefault();execute(true)});
f.querySelector('[data-reality-check]').addEventListener('click',()=>execute(false));
displayPreset();
})();</script>'''
    script=script.replace('PRESETS',json.dumps(reality.PRESETS,ensure_ascii=False).replace('<','\\u003c')).replace('NODES',json.dumps([{'id':str(n['id']),'name':str(n.get('name') or n.get('url') or n['id'])} for n in nodes],ensure_ascii=False).replace('<','\\u003c')).replace('FLEET','true' if fleet else 'false').replace('ACTION',json.dumps(path+'/reality-action'))
    style='''<style>
#wpoRealityDialog .connection-pane{display:grid;gap:16px;padding:20px}
#wpoRealityDialog .connection-pane>label{display:flex;flex-direction:column;gap:7px;margin:0;font-size:11px;color:var(--muted)}
#wpoRealityDialog input,#wpoRealityDialog select{box-sizing:border-box;display:block;width:100%;min-width:0;height:40px;margin:0;padding:0 12px;border:1px solid var(--line);border-radius:9px;background-color:var(--input);color:var(--text);font:inherit;font-size:12px;line-height:normal;box-shadow:none}
#wpoRealityDialog select{-webkit-appearance:none;appearance:none;padding-right:36px;cursor:pointer;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 18px) 50%,calc(100% - 14px) 50%;background-size:4px 4px;background-repeat:no-repeat;text-overflow:ellipsis}
#wpoRealityDialog select option{background:var(--surface);color:var(--text)}
#wpoRealityDialog input:focus,#wpoRealityDialog select:focus,
#wpoRealityDialog input:focus-visible,#wpoRealityDialog select:focus-visible{
 outline:1px solid var(--muted)!important;outline-offset:0!important;
 border-color:var(--line)!important;box-shadow:none!important
}
#wpoRealityDialog #wpoRealityAddress{color:var(--muted);background:var(--raised,var(--input));cursor:default}
#wpoRealityDialog .connection-pane>small{font-size:11px;line-height:1.6;color:var(--muted)}
#wpoRealityDialog details{padding:12px;border:1px solid var(--line);border-radius:9px}
#wpoRealityDialog details summary{cursor:pointer;font-size:11px;color:var(--muted)}
#wpoRealityDialog details label{display:block;margin-top:12px}
#wpoRealityDialog details input{margin-top:7px}
#wpoRealityResult{margin:0;font-size:12px;line-height:1.5}
#wpoRealityResult:empty{display:none}
#wpoRealityDialog{
 box-sizing:border-box;width:min(515px,calc(100vw - 28px));
 height:min(700px,calc(100dvh - 30px));max-height:calc(100dvh - 30px);
 padding:18px 20px;overflow:hidden
}
#wpoRealityDialog form{height:100%;min-height:0;display:flex;flex-direction:column}
#wpoRealityDialog .dialog-head{flex:0 0 auto}
#wpoRealityDialog .connection-pane{
 flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain;
 align-content:start;scrollbar-gutter:stable
}
#wpoRealityDialog .actions{
 flex:0 0 auto;display:flex;justify-content:flex-end;align-items:center;
 min-height:62px;margin-top:auto;padding:10px 0 0;border-top:1px solid var(--line)
}
#wpoRealityDialog .connection-pane{gap:13px;padding:12px 2px 18px}
#wpoRealityDialog .connection-pane>label{position:relative;min-width:0}
#wpoRealityDialog .wpo-reality-picker{position:relative;width:100%;min-width:0}
#wpoRealityDialog .wpo-reality-picker-toggle{display:flex;width:100%;height:41px;justify-content:space-between;text-align:left;padding:0 13px;background:var(--input);color:var(--text);border:1px solid var(--line);border-radius:10px;font-size:12px}
#wpoRealityDialog .wpo-reality-picker-toggle:focus-visible{
 outline:1px solid var(--muted)!important;outline-offset:0!important;
 border-color:var(--line)!important;box-shadow:none!important
}
#wpoRealityDialog .wpo-reality-picker-menu{position:absolute;top:calc(100% + 5px);left:0;right:0;z-index:50;max-height:210px;overflow-y:auto;display:grid;gap:3px;padding:6px;border:1px solid var(--line);border-radius:12px;background:var(--surface);box-shadow:0 12px 38px #0006}
#wpoRealityDialog .wpo-reality-picker-menu[hidden]{display:none}
#wpoRealityDialog .wpo-reality-picker-menu button{display:flex;flex-direction:column;align-items:flex-start;gap:2px;padding:9px 12px;border:1px solid transparent;border-radius:8px;background:transparent;text-align:left;font-size:12px}
#wpoRealityDialog .wpo-reality-picker-menu button small{font-size:10px}
#wpoRealityDialog .wpo-reality-picker-menu button:hover,#wpoRealityDialog .wpo-reality-picker-menu button[aria-selected=true]{background:var(--raised);border-color:var(--line)}
#wpoRealityDialog .wpo-reality-checks{padding:12px 13px;border:1px solid var(--line);background:var(--input);border-radius:12px}
#wpoRealityDialog .wpo-reality-checks-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}
#wpoRealityDialog .wpo-reality-checks-head strong{font-size:11px}
#wpoRealityDialog .wpo-reality-checks-head span{font-size:10px;color:var(--muted)}
#wpoRealityDialog .wpo-reality-checks-list{display:grid;gap:7px;max-height:200px;overflow-y:auto}
#wpoRealityDialog .wpo-reality-check-row{padding:9px 10px;border:1px solid var(--line);background:var(--surface);border-radius:9px}
#wpoRealityDialog .wpo-reality-check-row-head{display:flex;gap:8px;align-items:center;font-size:11px}
#wpoRealityDialog .wpo-reality-led{display:block;flex:0 0 8px;width:8px;height:8px;background:var(--muted);border-radius:50%}
#wpoRealityDialog .wpo-reality-check-row.pending .wpo-reality-led{background:var(--amber);animation:wpo-real-pulse .85s ease-in-out infinite alternate}
#wpoRealityDialog .wpo-reality-check-row.ok .wpo-reality-led{background:var(--green)}
#wpoRealityDialog .wpo-reality-check-row.error .wpo-reality-led{background:var(--red)}
#wpoRealityDialog .wpo-reality-check-row.warning .wpo-reality-led{background:var(--amber)}
#wpoRealityDialog .wpo-reality-check-row-details{display:flex;align-items:center;flex-wrap:wrap;gap:5px;margin:5px 0 0 16px}
#wpoRealityDialog .wpo-reality-check-row-details small{font-size:10px;line-height:1.45}
#wpoRealityDialog .wpo-reality-chip{padding:3px 6px;border-radius:6px;background:color-mix(in srgb,var(--green) 12%,transparent);border:1px solid color-mix(in srgb,var(--green) 25%,var(--line));color:var(--green);font-size:9px}
@keyframes wpo-real-pulse{to{opacity:.25;transform:scale(.7)}}
#wpoRealityDialog .actions{justify-content:flex-end}
@media(max-width:580px){
 #wpoRealityDialog{width:calc(100vw - 24px);height:calc(100dvh - 26px);max-height:calc(100dvh - 26px);padding:15px 16px;overflow:hidden}
 #wpoRealityDialog .wpo-reality-picker-menu{max-height:190px}
 #wpoRealityDialog .connection-pane{padding:12px 0 16px;scrollbar-gutter:auto}
}

</style>'''
    return style+html+script

def install(ns):
    connections=ns['connections_ui'];nodes=ns['nodes_ui']
    def connections_ui(*args,**kwargs):
        html=connections(*args,**kwargs)
        path=args[2] if len(args)>2 else kwargs['path'];csrf=args[3] if len(args)>3 else kwargs['csrf']
        # The same shared node settings are reachable from the connection pencil.
        html=html.replace('</div></section><div class="actions"><button type="button" data-close-connection>',
            '<div class="cdn-settings-box" data-reality-settings hidden><button type="button" data-reality-open>Настройки REALITY основной ноды</button><small style="display:block;margin-top:8px;color:var(--muted);line-height:1.5">IP автоматически · TCP 443 · SNI и TLS fingerprint</small></div></div></section><div class="actions"><button type="button" data-close-connection>',1)
        html+='''<script>(()=>{const f=document.getElementById('connectionForm'),d=document.getElementById('connectionEditor'),b=f?.querySelector('[data-reality-settings]');if(!b)return;function sync(){b.hidden=f.elements.protocol.value!=='reality'}f.elements.protocol.addEventListener('change',sync);new MutationObserver(sync).observe(d,{attributes:true,attributeFilter:['open']});sync()})();</script>'''
        import wpp_nodes
        public_nodes=[wpp_nodes.public_node(n) for n in wpp_nodes.load_nodes('/var/lib/tproxy-panel/nodes.json')]
        return html+editor(path,csrf,public_nodes,fleet=True)
    def nodes_ui(*args,**kwargs):
        html=nodes(*args,**kwargs)
        path=args[3] if len(args)>3 else kwargs['path'];csrf=args[4] if len(args)>4 else kwargs['csrf']
        # Place the primary-node pencil inside the SAME bottom-right actions
        # row as the remote nodes' edit/delete buttons, not below the card.
        # The label can contain an inline server icon; do not depend on its
        # rendered SVG/HTML when locating the single primary-card meta row.
        boundary=html.find('</article>')
        if boundary<0:
            raise RuntimeError("WPO: основная карточка не найдена; карандаш не добавлен.")
        primary=html[:boundary]
        anchor='<div class="wpo-node-meta-row"><p class="wpo-node-template wpo-main-node-label">'
        if primary.count(anchor)!=1:
            raise RuntimeError("WPO: основная карточка изменилась; карандаш не добавлен.")
        start=primary.index(anchor)
        end=primary.find('</p></div>',start)
        if end<0:
            raise RuntimeError("WPO: нижний ряд основной ноды изменился; карандаш не добавлен.")
        pencil='<button type="button" class="icon-btn wpo-node-icon" data-reality-open title="Настройки REALITY" aria-label="Настройки REALITY">'+ns['icon']('edit')+'</button>'
        primary=primary[:end+4]+'<div class="wpo-node-actions">'+pencil+'</div>'+primary[end+4:]
        html=primary+html[boundary:]
        return html+editor(path,csrf,args[0] if args else kwargs.get('nodes',[]))
    ns['connections_ui']=connections_ui;ns['nodes_ui']=nodes_ui
