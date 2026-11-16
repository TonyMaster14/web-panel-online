"""Compact node REALITY settings, shared by node and connection views."""
from html import escape
import json
import wpo_reality as reality

def editor(path, csrf, nodes=()):
    try: profile=reality.read_profile()
    except (OSError,ValueError): return ''
    e=lambda x:escape(str(x),quote=True)
    options=''.join('<option value="'+key+'"'+(' selected' if profile.get('preset')==key else '')+'>'+title+' · '+domain+'</option>' for key,(title,domain) in reality.PRESETS.items())
    options+='<option value="custom"'+(' selected' if profile.get('preset')=='custom' else '')+'>Свой домен</option>'
    node_options='<option value="local">Основная нода</option>'+''.join('<option value="'+e(n['id'])+'">'+e(n.get('name') or n.get('url') or n['id'])+'</option>' for n in nodes)
    html='''<dialog id="wpoRealityDialog" class="connection-editor"><form id="wpoRealityForm">
<div class="dialog-head"><div><h2>VLESS TCP REALITY Vision</h2><small>TCP · Vision · общий внешний порт 443</small></div><button type="button" data-reality-close>×</button></div>
<input type="hidden" name="csrf" value="'''+e(csrf)+'''">
<section class="connection-pane"><label>Нода<select name="node_id">'''+node_options+'''</select></label><label>IP-адрес<input id="wpoRealityAddress" value="'''+e(profile.get('address',''))+'''" readonly aria-readonly="true" spellcheck="false"></label>
<label>Сайт для REALITY<select name="preset">'''+options+'''</select></label>
<label>SNI<input name="sni" value="'''+e(profile['sni'])+'''" required></label>
<label>TLS fingerprint<select name="fingerprint"><option value="firefox">Mozilla Firefox</option><option value="edge">Microsoft Edge · проверить в клиенте</option></select></label>
<small>Шаблон сайта на вашем домене настраивается отдельно. Изменения REALITY применяются ко всем его подключениям на этой ноде. После смены параметров обновите подписки.</small>
<details><summary>Параметры доступа</summary><label>Public key<input name="public_key" readonly value="'''+e(profile['public_key'])+'''"></label><label>Short ID<input name="short_id" readonly value="'''+e(profile['short_id'])+'''"></label></details>
<p id="wpoRealityResult" role="status"></p></section><div class="actions"><button type="button" data-reality-check>Проверить цель</button><button type="submit" class="primary">Проверить и сохранить</button></div></form></dialog>'''
    script='''<script>(()=>{const d=document.getElementById('wpoRealityDialog'),f=document.getElementById('wpoRealityForm'),out=document.getElementById('wpoRealityResult');if(!d||!f)return;
const presets=PRESETS;f.elements.fingerprint.value=FINGERPRINT;
function preset(){const p=presets[f.elements.preset.value];f.elements.sni.readOnly=Boolean(p);if(p)f.elements.sni.value=p[1]}preset();f.elements.preset.addEventListener('change',preset);
async function load(){out.textContent='';f.querySelectorAll('button').forEach(b=>b.disabled=true);try{const body=new URLSearchParams({csrf:f.elements.csrf.value,node_id:f.elements.node_id.value,read_only:'1'});const r=await fetch(ACTION,{method:'POST',body});const j=await r.json();if(!r.ok||!j.ok)throw Error(j.message||'Не удалось загрузить REALITY');const p=j.profile;['preset','sni','fingerprint','public_key','short_id'].forEach(k=>f.elements[k].value=p[k]);document.getElementById('wpoRealityAddress').value=p.address||'';preset();f.querySelectorAll('button').forEach(b=>b.disabled=false)}catch(e){out.textContent=e.message;d.querySelector('[data-reality-close]').disabled=false}}
f.elements.node_id.addEventListener('change',load);
const editForm=document.getElementById('wpoEditNodeForm');if(editForm){const b=document.createElement('button');b.type='button';b.textContent='Настройки REALITY';b.onclick=()=>{f.elements.node_id.value=editForm.elements.id.value;editForm.closest('dialog').close();d.showModal();load()};editForm.append(b)}
document.querySelectorAll('[data-reality-open]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('dialog[open]').forEach(x=>x.close());f.elements.node_id.value="local";d.showModal();load()}));d.querySelector('[data-reality-close]').onclick=()=>d.close();
async function submit(check){const buttons=f.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);out.textContent='';try{const body=new URLSearchParams(new FormData(f));body.set('check_only',check?'1':'0');const r=await fetch(ACTION,{method:'POST',headers:{'X-WPP-Async':'1'},body});if(r.redirected)throw Error('Сессия завершена. Обновите страницу.');const j=await r.json();if(!r.ok||!j.ok)throw Error(j.message||'Ошибка REALITY');out.textContent=j.message}catch(e){out.textContent=e.message}finally{buttons.forEach(b=>b.disabled=false)}}f.addEventListener('submit',e=>{e.preventDefault();submit(false)});f.querySelector('[data-reality-check]').onclick=()=>submit(true)})();</script>'''
    script=script.replace('PRESETS',json.dumps(reality.PRESETS)).replace('FINGERPRINT',json.dumps(profile['fingerprint'])).replace('ACTION',json.dumps(path+'/reality-action'))
    style='''<style>
#wpoRealityDialog .connection-pane{display:grid;gap:16px;padding:20px}
#wpoRealityDialog .connection-pane>label{display:flex;flex-direction:column;gap:7px;margin:0;font-size:11px;color:var(--muted)}
#wpoRealityDialog input,#wpoRealityDialog select{box-sizing:border-box;display:block;width:100%;min-width:0;height:40px;margin:0;padding:0 12px;border:1px solid var(--line);border-radius:9px;background-color:var(--input);color:var(--text);font:inherit;font-size:12px;line-height:normal;box-shadow:none}
#wpoRealityDialog select{-webkit-appearance:none;appearance:none;padding-right:36px;cursor:pointer;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 18px) 50%,calc(100% - 14px) 50%;background-size:4px 4px;background-repeat:no-repeat;text-overflow:ellipsis}
#wpoRealityDialog select option{background:var(--surface);color:var(--text)}
#wpoRealityDialog input:focus-visible,#wpoRealityDialog select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#wpoRealityDialog #wpoRealityAddress{color:var(--muted);background:var(--raised,var(--input));cursor:default}
#wpoRealityDialog .connection-pane>small{font-size:11px;line-height:1.6;color:var(--muted)}
#wpoRealityDialog details{padding:12px;border:1px solid var(--line);border-radius:9px}
#wpoRealityDialog details summary{cursor:pointer;font-size:11px;color:var(--muted)}
#wpoRealityDialog details label{display:block;margin-top:12px}
#wpoRealityDialog details input{margin-top:7px}
#wpoRealityResult{margin:0;font-size:12px;line-height:1.5}
#wpoRealityResult:empty{display:none}
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
        return html+editor(path,csrf)
    def nodes_ui(*args,**kwargs):
        html=nodes(*args,**kwargs)
        path=args[3] if len(args)>3 else kwargs['path'];csrf=args[4] if len(args)>4 else kwargs['csrf']
        # First article is the primary node; no expansion of the compact grid.
        html=html.replace('</article>','<button type="button" class="icon-btn wpo-node-icon" data-reality-open title="Настройки REALITY" aria-label="Настройки REALITY">'+ns['icon']('edit')+'</button></article>',1)
        return html+editor(path,csrf,args[0] if args else kwargs.get('nodes',[]))
    ns['connections_ui']=connections_ui;ns['nodes_ui']=nodes_ui
