#!/usr/bin/env bash
# WPO popup-only custom dropdown enhancement (not the VPN configuration).
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на основной панели WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || { echo 'Установленная панель WPO не найдена. Изменений нет.' >&2; exit 2; }
systemctl is-active --quiet "$SERVICE" || { echo 'Служба панели не активна. Изменений нет.' >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-popup-style.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Сбой проверки: прежний интерфейс восстановлен из $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap finish EXIT
python3 - "$TARGET" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys

original = Path(sys.argv[1]).read_text(encoding='utf-8')
START = '# WPO_CUSTOM_SELECT_POPOVER_BEGIN'
END = '# WPO_CUSTOM_SELECT_POPOVER_END'
if original.count(START) != original.count(END) or original.count(START) > 1:
    raise RuntimeError('Обнаружены несовместимые маркеры оформления; изменений нет.')
if not all(x in original for x in ('CSS = ', 'COMMON_JS = ', 'def connections_ui(', 'ASSET_REV =')):
    raise RuntimeError('Неизвестная версия интерфейса WPO; изменений нет.')
CSS_PATCH = r'''
/* WPO custom select popover: the open menu is styled too. */
.wpo-popup-select-shell{display:block;position:relative;min-width:0;width:100%;max-width:100%}
.wpo-popup-select-shell .wpo-popup-select-source{position:absolute!important;width:1px!important;height:1px!important;opacity:0!important;pointer-events:none!important;clip-path:inset(50%)!important}
.wpo-popup-select-trigger{box-sizing:border-box!important;display:flex!important;align-items:center;justify-content:space-between;gap:12px;width:100%!important;min-width:0;max-width:100%;height:41px;min-height:41px;margin:0;padding:0 12px 0 13px;border:1px solid var(--line)!important;border-radius:10px;background:var(--input)!important;color:var(--text)!important;box-shadow:none!important;font:500 12px/1.4 "Segoe UI",system-ui,sans-serif;text-align:left;cursor:pointer;transition:border-color .16s ease,background .16s ease}
.wpo-popup-select-trigger:hover:not(:disabled){border-color:color-mix(in srgb,var(--muted) 60%,var(--line))!important}
.wpo-popup-select-trigger:focus-visible{outline:1px solid var(--muted);outline-offset:0}
.wpo-popup-select-trigger[aria-expanded=true]{border-color:var(--accent)!important}
.wpo-popup-select-trigger:disabled{opacity:1!important;color:var(--muted)!important;cursor:not-allowed}
.wpo-popup-select-value{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.wpo-popup-select-chevron{display:block;flex:0 0 auto;width:16px;height:16px;stroke:var(--muted);transition:transform .14s ease}
.wpo-popup-select-trigger[aria-expanded=true] .wpo-popup-select-chevron{transform:rotate(180deg)}
.wpo-popup-select-menu[popover]{box-sizing:border-box;position:fixed;inset:auto;margin:0;padding:6px;min-width:0;border:1px solid var(--line);border-radius:11px;background:var(--surface);color:var(--text);box-shadow:0 16px 38px #0006;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;z-index:2147483647}
.wpo-popup-select-option{box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;min-height:35px;margin:1px 0;padding:8px 10px;border:0;border-radius:7px;background:transparent;color:var(--text);font:500 12px/1.35 "Segoe UI",system-ui,sans-serif;text-align:left;white-space:normal;overflow-wrap:anywhere;cursor:pointer}
.wpo-popup-select-option:hover:not(:disabled),.wpo-popup-select-option.is-active{background:var(--raised);color:var(--text)}
.wpo-popup-select-option[aria-selected=true]{background:var(--tint);color:var(--accent)}
.wpo-popup-select-option[aria-selected=true].is-active{background:color-mix(in srgb,var(--accent) 17%,var(--surface))}
.wpo-popup-select-option:disabled{opacity:.42;cursor:not-allowed}
.wpo-popup-select-option .wpo-popup-check{font-size:14px;color:var(--accent);flex:0 0 auto}
.clients-toolbar .wpo-popup-select-shell{flex:0 1 160px;min-width:128px;max-width:175px}
.clients-toolbar .wpo-popup-select-shell:has(#clientSort){min-width:118px}
.update-control .wpo-popup-select-shell{width:100%;max-width:none}
@media(max-width:700px){.clients-toolbar .wpo-popup-select-shell{flex:1 1 120px;min-width:0;max-width:none}}
@media(prefers-reduced-motion:reduce){.wpo-popup-select-trigger,.wpo-popup-select-chevron{transition:none}}
'''
JS_PATCH = r'''<script>
(()=>{
  'use strict';
  const selector='#connectionProtocol,#clientFilter,#protocolFilter,#clientSort,#wpoEditNodeDialog select[name="site_template"],dialog select[name="site_template"],.wpo-node-edit select[name="site_template"],#panelRelease,#xrayRelease,#openfluxRelease';
  if(typeof HTMLElement.prototype.showPopover!=='function')return;
  let opened=null, highlighted=-1;
  const pop=document.createElement('div');
  pop.className='wpo-popup-select-menu';pop.id='wpo-select-menu';
  pop.setAttribute('popover','manual');pop.setAttribute('role','listbox');
  const openOptions=()=>Array.from(pop.querySelectorAll('.wpo-popup-select-option'));
  function close(focus){
    if(!opened)return;
    const prev=opened;opened=null;
    prev.button.setAttribute('aria-expanded','false');
    if(pop.matches(':popover-open'))pop.hidePopover();
    if(focus&&prev.button.isConnected&&!prev.button.disabled)prev.button.focus({preventScroll:true});
  }
  function sync(entry){
    const {select,button}=entry;
    const selected=select.options[select.selectedIndex];
    button.querySelector('.wpo-popup-select-value').textContent=selected?selected.textContent.trim():'Выберите значение';
    button.disabled=select.disabled;
    if(opened===entry&&select.disabled)close(false);
  }
  function highlight(index){
    const buttons=openOptions();
    if(index<0||index>=buttons.length||buttons[index].disabled)return;
    highlighted=index;
    buttons.forEach((node,i)=>node.classList.toggle('is-active',i===index));
    buttons[index].scrollIntoView({block:'nearest'});
  }
  function render(entry){
    pop.replaceChildren();
    const selected=entry.select.selectedIndex;
    Array.from(entry.select.options).forEach((option,index)=>{
      if(option.hidden)return;
      const item=document.createElement('button');
      item.type='button';item.className='wpo-popup-select-option';
      item.dataset.index=String(index);item.setAttribute('role','option');
      item.setAttribute('aria-selected',String(index===selected));
      item.disabled=option.disabled;
      const label=document.createElement('span');label.textContent=option.textContent.trim();
      item.append(label);
      if(index===selected){const check=document.createElement('span');check.className='wpo-popup-check';check.textContent='✓';check.setAttribute('aria-hidden','true');item.append(check)}
      pop.append(item);
    });
    highlighted=selected;
    const found=pop.querySelector('.wpo-popup-select-option[data-index="'+selected+'"]');
    if(!found||found.disabled)highlighted=Array.from(entry.select.options).findIndex(o=>!o.disabled&&!o.hidden);
    const active=pop.querySelector('.wpo-popup-select-option[data-index="'+highlighted+'"]');
    if(active)active.classList.add('is-active');
  }
  function position(entry){
    const r=entry.button.getBoundingClientRect();
    const vw=document.documentElement.clientWidth,vh=document.documentElement.clientHeight;
    const width=Math.min(Math.max(r.width,160),Math.max(120,vw-16));
    const below=Math.max(0,vh-r.bottom-8),above=Math.max(0,r.top-8);
    const goUp=below<Math.min(175,pop.scrollHeight)&&above>below;
    const room=goUp?above:below;
    const limit=Math.max(70,Math.min(320,room-4));
    pop.style.width=width+'px';pop.style.maxHeight=limit+'px';
    pop.style.left=Math.max(8,Math.min(r.left,vw-width-8))+'px';
    pop.style.top=(goUp?Math.max(8,r.top-Math.min(pop.scrollHeight,limit)-5):Math.min(vh-8,r.bottom+5))+'px';
  }
  function open(entry){
    sync(entry);if(entry.select.disabled)return;
    if(opened===entry){close(false);return;}
    close(false);render(entry);
    const parent=entry.button.closest('dialog')||document.body;
    if(pop.parentElement!==parent)parent.append(pop);
    opened=entry;entry.button.setAttribute('aria-expanded','true');
    pop.style.visibility='hidden';
    try{pop.showPopover();position(entry);pop.style.visibility='visible'}
    catch(e){pop.style.visibility='visible';close(false);return}
    const active=pop.querySelector('.wpo-popup-select-option[data-index="'+highlighted+'"]');
    if(active)active.scrollIntoView({block:'nearest'});
  }
  function commit(index){
    const entry=opened;if(!entry)return;
    const option=entry.select.options[index];if(!option||option.disabled||option.hidden)return;
    const changed=entry.select.selectedIndex!==index;
    entry.select.selectedIndex=index;
    sync(entry);close(true);
    if(changed){entry.select.dispatchEvent(new Event('input',{bubbles:true}));entry.select.dispatchEvent(new Event('change',{bubbles:true}));}
  }
  function step(entry,delta){
    if(opened!==entry)open(entry);if(opened!==entry)return;
    const choices=Array.from(entry.select.options);
    let index=highlighted;
    for(let n=0;n<choices.length;n++){
      index=(index+delta+choices.length)%choices.length;
      if(!choices[index].disabled&&!choices[index].hidden){highlight(index);break;}
    }
  }
  function enhance(select){
    if(select.dataset.wpoPopupReady==='1'||select.multiple)return;
    const shell=document.createElement('span');shell.className='wpo-popup-select-shell';
    const button=document.createElement('button');button.type='button';button.className='wpo-popup-select-trigger';
    button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls',pop.id);
    const label=select.getAttribute('aria-label')||select.id||select.name||'Выбор';
    button.setAttribute('aria-label',label);
    const value=document.createElement('span');value.className='wpo-popup-select-value';
    const arrow=document.createElementNS('http://www.w3.org/2000/svg','svg');
    arrow.setAttribute('viewBox','0 0 24 24');arrow.setAttribute('fill','none');arrow.setAttribute('stroke-width','2.1');
    arrow.classList.add('wpo-popup-select-chevron');
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','m6 9 6 6 6-6');path.setAttribute('stroke-linecap','round');path.setAttribute('stroke-linejoin','round');arrow.append(path);
    button.append(value,arrow);
    select.before(shell);shell.append(select,button);
    select.dataset.wpoPopupReady='1';select.classList.add('wpo-popup-select-source');select.tabIndex=-1;
    const entry={select,button};
    sync(entry);
    button.addEventListener('click',()=>open(entry));
    button.addEventListener('keydown',event=>{
      const key=event.key;
      if(key==='Escape'&&opened===entry){event.preventDefault();close(true);return;}
      if(key==='ArrowDown'||key==='ArrowUp'){event.preventDefault();step(entry,key==='ArrowDown'?1:-1);return;}
      if(key==='Enter'||key===' '){event.preventDefault();if(opened===entry)commit(highlighted);else open(entry);return;}
      if(key==='Home'||key==='End'){
        event.preventDefault();if(opened!==entry)open(entry);
        const choices=Array.from(select.options).map((option,index)=>({option,index})).filter(x=>!x.option.disabled&&!x.option.hidden);
        if(choices.length)highlight(key==='Home'?choices[0].index:choices[choices.length-1].index);
      }
    });
    select.addEventListener('change',()=>sync(entry));
    select.addEventListener('input',()=>sync(entry));
    new MutationObserver(()=>{sync(entry);if(opened===entry){render(entry);position(entry);}})
      .observe(select,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['disabled','selected','label','hidden']});
  }
  function scan(root){
    if(root.nodeType!==1&&root.nodeType!==9)return;
    if(root.nodeType===1&&root.matches&&root.matches(selector))enhance(root);
    if(root.querySelectorAll)root.querySelectorAll(selector).forEach(enhance);
  }
  pop.addEventListener('click',event=>{
    const option=event.target.closest('.wpo-popup-select-option');
    if(option&&!option.disabled)commit(Number(option.dataset.index));
  });
  document.addEventListener('pointerdown',event=>{
    if(opened&&!opened.button.contains(event.target)&&!pop.contains(event.target))close(false);
  },true);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&opened){event.preventDefault();close(true);}},true);
  window.addEventListener('resize',()=>{if(opened)position(opened)});
  window.addEventListener('scroll',event=>{if(opened&&!pop.contains(event.target))close(false)},true);
  const init=()=>{
    document.body.append(pop);scan(document);
    new MutationObserver(records=>{for(const record of records){for(const node of record.addedNodes)scan(node)}})
      .observe(document.body,{childList:true,subtree:true});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
</script>'''
asset = "ASSET_REV = hashlib.sha256((CSS + COMMON_JS).encode('utf-8')).hexdigest()[:12]"
patch = '\n\n' + START + '\n' + 'CSS += ' + repr(CSS_PATCH) + '\n' + 'COMMON_JS += ' + repr(JS_PATCH) + '\n' + asset + '\n' + END + '\n'
if START in original:
    first = original.index(START)
    last = original.index(END, first) + len(END)
    patched = original[:first] + patch.strip('\n') + original[last:]
else:
    patched = original.rstrip() + patch
compile(patched, sys.argv[2], 'exec')
Path(sys.argv[2]).write_text(patched, encoding='utf-8')
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TMP/patched.py" "$TARGET"; then
  echo 'WPO: раскрывающиеся списки уже обновлены. Изменений нет.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/select-popup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-ui-popup.XXXXXXXX.py")"
cp "$TMP/patched.py" "$STAGE"
chown --reference="$TARGET" "$STAGE"
chmod --reference="$TARGET" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$TARGET"
python3 -m py_compile "$TARGET"
systemctl restart "$SERVICE"
READY=0
for i in $(seq 1 15); do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo 'WPO не ответила после обновления; выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Обновлены раскрывающиеся меню в Подключениях, Пользователях, Нодах и Обновлениях.'
echo "✓ Изменён только интерфейс. Резервная копия: $BACKUP"
