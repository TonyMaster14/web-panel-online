#!/usr/bin/env python3
"""WPO c333e00: restore complete dynamic RU/EN on the existing safe UI.

Edits only /opt/tproxy-panel/wpp_ui.py; backs up and rolls back on failure.
No changes to routes, node/protocol IDs, backend data or form field names.
"""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

APP=Path('/opt/tproxy-panel')
TARGET=APP/'wpp_ui.py'
SERVICE='tproxy-panel.service'
NEW_MARK='# WPO_C333_I18N_V2_COMPLETE'
OLD_MARK='# WPO_C333_LANGUAGE_THEME_V1'

LANGUAGE_JS = r'''<script>
(()=>{
'use strict';
const dictionary=__DICTIONARY__;
const textStates=new WeakMap();
const attrStates=new WeakMap();
const skip='script,style,noscript,textarea,code,pre,svg,[contenteditable],[data-wpo-no-translate],.wpo-utility-switches';
const attrNames=['title','placeholder','aria-label','alt'];
const observeOptions={subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attrNames};
let language='ru';
try{language=localStorage.getItem('wpo-language')==='en'?'en':'ru'}catch(_){}
const pageTitle=document.title;
const queuedRoots=new Set();
let scheduled=false;
let observer=null;
const has=key=>Object.prototype.hasOwnProperty.call(dictionary,key);
function translate(text){
  const m=text.match(/^(\s*)([\s\S]*?)(\s*)$/);
  if(!m)return text;
  const core=m[2].replace(/\s+/g,' ');
  if(has(core))return m[1]+dictionary[core]+m[3];
  const pieces=core.split(/(\s*[·•|:]\s*)/);
  if(pieces.length>1){
    let changed=false;
    for(let i=0;i<pieces.length;i+=2){
      const part=pieces[i].trim();
      if(has(part)){
        const original=pieces[i];
        pieces[i]=original.replace(part,dictionary[part]);
        changed=true;
      }
    }
    if(changed)return m[1]+pieces.join('')+m[3];
  }
  const numbered=core.match(/^(.+?)\s*(\(\d+\)|\d+)$/);
  if(numbered&&has(numbered[1]))return m[1]+dictionary[numbered[1]]+' '+numbered[2]+m[3];
  return text;
}
function restoreOrTranslate(current,state){
  if(!state||current!==state.ru&&current!==state.en)
    state={ru:current,en:translate(current)};
  return {state,desired:language==='en'?state.en:state.ru};
}
function validElement(el){
  return el&&el.nodeType===1&&!(el.matches(skip)||el.closest(skip));
}
function translateText(node){
  const parent=node.parentElement;
  if(!validElement(parent))return;
  // An <option> without a value attribute submits its text as its value.
  // Preserve these options so language never changes connection/protocol IDs.
  if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))return;
  const current=node.nodeValue;
  if(!current||!/[А-ЯЁа-яё]/u.test(current)&&!textStates.has(node))return;
  const info=restoreOrTranslate(current,textStates.get(node));
  textStates.set(node,info.state);
  if(current!==info.desired)node.nodeValue=info.desired;
}
function translateAttributes(el){
  if(!validElement(el))return;
  let attrs=attrStates.get(el);
  if(!attrs){attrs=new Map();attrStates.set(el,attrs)}
  for(const name of attrNames){
    if(!el.hasAttribute(name))continue;
    const current=el.getAttribute(name);
    const info=restoreOrTranslate(current,attrs.get(name));
    attrs.set(name,info.state);
    if(current!==info.desired)el.setAttribute(name,info.desired);
  }
  if(el.tagName==='INPUT'&&!el.name&&['submit','button','reset'].includes(el.type)){
    const current=el.value;
    const info=restoreOrTranslate(current,attrs.get('input-label'));
    attrs.set('input-label',info.state);
    if(current!==info.desired)el.value=info.desired;
  }
}
function scan(root){
  if(!root)return;
  if(root.nodeType===3){translateText(root);return}
  if(root.nodeType!==1||!validElement(root))return;
  translateAttributes(root);
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
  let node;
  while((node=walker.nextNode())){
    if(node.nodeType===3){translateText(node);continue}
    if(validElement(node))translateAttributes(node);
  }
}
function updateControls(){
  document.documentElement.lang=language;
  document.querySelectorAll('button[data-wpo-lang]').forEach(button=>{
    button.setAttribute('aria-pressed',String(button.dataset.wpoLang===language));
  });
  const switchGroup=document.querySelector('.wpo-utility-switches');
  if(switchGroup)switchGroup.setAttribute('aria-label',language==='en'?'Language and theme':'Язык и тема');
  const native=pageTitle.match(/^(.+?)\s*[·—–]\s*WPO$/);
  if(native&&language==='en'&&has(native[1]))document.title=dictionary[native[1]]+' · WPO';
  else document.title=pageTitle;
}
function observe(){
  if(observer&&document.body)observer.observe(document.body,observeOptions);
}
function fullApply(){
  if(observer)observer.disconnect();
  queuedRoots.clear();
  scheduled=false;
  scan(document.body);
  updateControls();
  observe();
}
function flush(){
  scheduled=false;
  if(!document.body)return;
  if(observer)observer.disconnect();
  let roots=[...queuedRoots];queuedRoots.clear();
  if(roots.length>80)roots=[document.body];
  for(const root of roots){
    if(root.isConnected)scan(root);
  }
  observe();
}
function enqueue(root){
  if(!root)return;
  if(root.nodeType===3)root=root.parentElement;
  if(!root||!root.isConnected)return;
  queuedRoots.add(root);
  if(queuedRoots.size>80){queuedRoots.clear();queuedRoots.add(document.body)}
  if(!scheduled){scheduled=true;requestAnimationFrame(flush)}
}
function start(){
  if(!document.body)return;
  fullApply();
  observer=new MutationObserver(records=>{
    for(const record of records){
      if(record.type==='childList'){
        for(const node of record.addedNodes)enqueue(node);
      }else if(record.type==='characterData'){
        enqueue(record.target);
      }else if(record.type==='attributes'){
        enqueue(record.target);
      }
    }
  });
  observe();
}
document.addEventListener('click',event=>{
  const target=event.target;
  const button=target&&typeof target.closest==='function'?target.closest('button[data-wpo-lang]'):null;
  if(!button)return;
  const next=button.dataset.wpoLang;
  if(next!=='en'&&next!=='ru')return;
  language=next;
  try{localStorage.setItem('wpo-language',language)}catch(_){}
  fullApply();
});
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});
else start();
})();
</script>'''


def rewrite(source):
    if '# WPO_C333_MANUAL_LOGIN_V1' not in source or OLD_MARK not in source:
        raise RuntimeError('Нужны рабочая WPO c333e00 и предыдущие патчи языка/входа. Ничего не изменено.')
    if NEW_MARK in source:
        return source, 0
    if 'WPO_NAV_NATIVE_RECOVERY_V2_BEGIN' in source:
        raise RuntimeError('Обнаружена несовместимая версия WPO. Ничего не изменено.')
    lines=source.splitlines(keepends=True)
    candidates=[i for i,line in enumerate(lines) if line.startswith('WPO_C333_I18N_JS = ')]
    if len(candidates)!=1:
        raise RuntimeError('Не найдена единственная переменная перевода WPO; остановка.')
    index=candidates[0]
    old_js=ast.literal_eval(lines[index].split(' = ',1)[1].strip())
    if not isinstance(old_js,str) or 'const dictionary=' not in old_js or 'data-wpo-lang' not in old_js:
        raise RuntimeError('Не удалось проверить прежний переводчик WPO.')
    start=old_js.index('const dictionary=')+len('const dictionary=')
    dictionary,_=json.JSONDecoder().raw_decode(old_js[start:])
    if not isinstance(dictionary,dict) or len(dictionary)<600:
        raise RuntimeError('Словарь перевода неполный. Остановка.')
    replacement=LANGUAGE_JS.replace('__DICTIONARY__',json.dumps(dictionary,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c'))
    if '__DICTIONARY__' in replacement or 'new MutationObserver(' not in replacement:
        raise RuntimeError('Сборка переводчика не прошла проверку.')
    lines[index]='WPO_C333_I18N_JS = '+repr(replacement)+'\n'
    updated=''.join(lines)+'\n'+NEW_MARK+'\n'
    ast.parse(updated,filename=str(TARGET))
    compile(updated,str(TARGET),'exec')
    for critical in ('# WPO_SELECT_POPOVER_V2_BEGIN','def routing_ui(','def theme_button():'):
        if source.count(critical)!=updated.count(critical):
            raise RuntimeError('Обнаружено изменение рабочего кода WPO: '+critical)
    if source.count('wppNavigationTimer')!=updated.count('wppNavigationTimer'):
        raise RuntimeError('Проверка навигации не пройдена.')
    return updated,len(dictionary)


def healthy():
    if subprocess.run(['systemctl','is-active','--quiet',SERVICE]).returncode!=0:
        return False
    try:
        try:
            response=urlopen('http://127.0.0.1:8090/',timeout=2)
            code=response.status
            response.close()
        except HTTPError as e:
            code=e.code
        return 200 <= code < 500
    except Exception:
        return False


def main():
    mode=sys.argv[1] if len(sys.argv)==2 else ''
    if mode not in ('--check','--apply'):
        raise SystemExit('Использование: --check | --apply')
    if mode=='--apply' and os.geteuid()!=0:
        raise SystemExit('Для установки требуется sudo.')
    if not TARGET.is_file() or TARGET.is_symlink() or not (APP/'panel.py').is_file():
        raise SystemExit('Установленная панель WPO не найдена. Ничего не изменено.')
    source=TARGET.read_text(encoding='utf-8')
    updated,count=rewrite(source)
    if updated==source:
        print('✓ Переводчик v2 уже установлен; изменений нет.')
        return
    print('✓ Проверка исходника пройдена. Словарь:',count,'переводов.')
    if mode=='--check':
        print('✓ Режим проверки: сервер и файлы не изменены.')
        return
    if not healthy():
        raise SystemExit('WPO не отвечает до обновления. Ничего не изменено.')
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir=Path('/var/backups/web-panel-online')/('i18n-v2-'+timestamp+'-'+str(os.getpid()))
    backup_dir.mkdir(parents=True,mode=0o700,exist_ok=False)
    shutil.copy2(TARGET,backup_dir/'wpp_ui.py')
    descriptor,tmp=tempfile.mkstemp(prefix='.wpo-i18n-v2-',suffix='.py',dir=APP)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as file:
            file.write(updated)
        attrs=TARGET.stat()
        os.chmod(tmp,stat.S_IMODE(attrs.st_mode))
        os.chown(tmp,attrs.st_uid,attrs.st_gid)
        os.replace(tmp,TARGET)
        subprocess.run(['systemctl','restart',SERVICE],check=True)
        for _ in range(20):
            if healthy():
                print('✓ Обновлён перевод кнопок, форм и динамических меню.')
                print('✓ Проверен ответ WPO. Резервная копия:',backup_dir/'wpp_ui.py')
                return
            time.sleep(1)
        raise RuntimeError('WPO не ответила после установки.')
    except Exception:
        shutil.copy2(backup_dir/'wpp_ui.py',TARGET)
        subprocess.run(['systemctl','restart',SERVICE],check=False)
        print('✖ Ошибка, возвращена резервная копия:',backup_dir/'wpp_ui.py',file=sys.stderr)
        raise
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


if __name__=='__main__':
    main()
