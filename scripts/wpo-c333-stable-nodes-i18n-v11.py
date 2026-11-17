#!/usr/bin/env python3
"""WPO v11: keep EN stable across Nodes, translate dialogs and editable-field labels.

Requires the existing c333e00 + UI patches v8, v9 and v10.
Applies a single reversible UI-only change to /opt/tproxy-panel/wpp_ui.py.
"""
import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

APP=Path('/opt/tproxy-panel')
TARGET=APP/'wpp_ui.py'
SERVICE='tproxy-panel.service'
MARK='# WPO_C333_STABLE_DYNAMIC_I18N_V11'
EXTRA = json.loads(r'''{"Настройки ноды":"Node settings","конфигурация":"configuration","выбранная нода":"selected node","выбранные ноды":"selected nodes","отдельная конфигурация":"separate configuration","Название и шаблон сайта":"Name and website template","Шаблоны берутся из раздела «Настройки» панели, включая ваши собственные. На подключённом Node Agent 0.2 выбранный шаблон публикуется на домене ноды.":"Templates come from the panel Settings, including your own. With Node Agent 0.2 connected, the selected template is published to the node domain.","Шаблоны берутся из раздела «Настройки» панели, включая ваши собственные.":"Templates come from the panel Settings, including your own.","На подключённом Node Agent 0.2 выбранный шаблон публикуется на домене ноды.":"With Node Agent 0.2 connected, the selected template is published to the node domain.","Стандартная страница ноды":"Standard node page","Стандартный шаблон":"Default template","Название ноды":"Node name","Выбранные ноды":"Selected nodes","выбранные ноды":"selected nodes","одна выбранная нода":"one selected node","Вся сеть":"Entire network","основная и":"main and","дополнительных нод":"additional nodes","дополнительные ноды":"additional nodes","Подключений Happ":"Happ connections","подключений Happ":"Happ connections","протокола":"protocols","нод":"nodes","Новый пользователь":"New user","Сохранено автоматически":"Saved automatically","Установлено автоматически":"Installed automatically","установлен автоматически.":"was installed automatically.","Проверка REALITY":"REALITY check","Параметры доступа":"Access parameters","Сохранение применяется ко всей сети после проверки каждой ноды.":"Changes are applied across the network after each node is verified.","Сохранение применяется ко всем REALITY-подключениям этой ноды.":"Changes apply to all REALITY connections on this node.","Изменения применяются ко всем REALITY-подключениям этой ноды.":"Changes apply to all REALITY connections on this node.","Шаблон сайта на вашем домене настраивается отдельно.":"The website template on your domain is configured separately.","После смены SNI обновите подписки.":"Update subscriptions after changing SNI.","Укажите домены для добавления или удаления":"Enter domains to add or remove","Укажите домены для добавления или удаления.":"Enter domains to add or remove.","Подписка для Happ":"Happ subscription","Текущий шаблон":"Current template","Выбрать шаблон":"Select template","Изменить шаблон":"Change template","Открыть настройку REALITY":"Open REALITY settings","Шаблон сайта":"Website template","Имя ноды":"Node name","Список нод":"Node list","Начальная страница":"Home page","Создание ноды":"Create node","Подключённая нода":"Connected node","настройки ноды":"node settings","Настройки REALITY":"REALITY settings","Открыть настройки REALITY":"Open REALITY settings","Настройки подключения":"Connection settings","Опции подключения":"Connection options","Создать пользователя":"Create user","Пользователь":"User","Нода":"Node"}''')
JS = r'''<script>
(()=>{
'use strict';
const dictionary=__DICTIONARY__;
const extraPairs=__PAIRS__;
const ruToEn=Object.assign(Object.create(null),dictionary);
for(const pair of extraPairs){
 if(!Array.isArray(pair)||pair.length!==2)continue;
 const en=pair[0],ru=pair[1];
 if(typeof ru==='string'&&typeof en==='string'&&/[А-Яа-яЁё]/u.test(ru))ruToEn[ru]=en;
}
const originalText=new WeakMap(),originalAttrs=new WeakMap();
const skip='script,style,noscript,pre,code,svg,select[data-wpo-popup-ready="1"],[contenteditable],[data-wpo-no-translate],.wpo-utility-switches';
const attributes=['title','placeholder','aria-label','alt'];
const isCyrillic=/[А-Яа-яЁё]/u;
let lang='ru';
try{lang=localStorage.getItem('wpo-language')==='en'?'en':'ru'}catch(_){}
let observer=null,scheduled=false;
const queued=new Set(),MAX_QUEUED=64;
const has=(x)=>Object.prototype.hasOwnProperty.call(ruToEn,x);
function translatedWord(input){
 if(has(input))return ruToEn[input];
 return input;
}
function translate(source){
 if(!source||!isCyrillic.test(source))return source;
 const m=source.match(/^(\s*)([\s\S]*?)(\s*)$/);
 if(!m)return source;
 const key=m[2].replace(/\s+/g,' ').trim();
 const left=m[1],right=m[3];
 if(has(key))return left+ruToEn[key]+right;
 const fleet=key.match(/^Вся сеть\s*[·–-]\s*основная и (\d+) дополнительных нод$/u);
 if(fleet)return left+'Entire network · main and '+fleet[1]+' additional nodes'+right;
 const summary=key.match(/^(\d+)\s+нод\s*[×x]\s*(\d+)\s+протокола\s*=\s*(\d+)\s+подключений Happ$/u);
 if(summary)return left+summary[1]+(Number(summary[1])===1?' node':' nodes')+' × '+summary[2]+(Number(summary[2])===1?' protocol':' protocols')+' = '+summary[3]+' Happ connections'+right;
 const openflux=key.match(/^(OpenFlux|Xray)\s+([\d.]+)\s+установлен автоматически\.$/u);
 if(openflux)return left+openflux[1]+' '+openflux[2]+' was installed automatically.'+right;
 const arrow=key.match(/^([↑↓])\s*(.+)$/u);
 if(arrow&&has(arrow[2]))return left+arrow[1]+' '+ruToEn[arrow[2]]+right;
 const decorated=key.match(/^([+＋✓✔⚠!•●]\s*)(.+)$/u);
 if(decorated&&has(decorated[2]))return left+decorated[1]+ruToEn[decorated[2]]+right;
 const shown=key.match(/^Показано\s+(\d+)\s+из\s+(\d+)(\s*·\s*(.+))?$/u);
 if(shown)return left+'Showing '+shown[1]+' of '+shown[2]+
    (shown[4]?' · '+translatedWord(shown[4]):'')+right;
 const cores=key.match(/^Ядер:\s*(.*?)\s*·\s*гипервизор:\s*(.+)$/u);
 if(cores)return left+'Cores: '+cores[1]+' · hypervisor: '+cores[2]+right;
 const duration=key.replace(/(\d+)\s*д\./gu,'$1 d.')
   .replace(/(\d+)\s*ч\./gu,'$1 h.')
   .replace(/(\d+)\s*мин\./gu,'$1 min.')
   .replace(/(\d+)\s*мин\s+назад/gu,'$1 min ago')
   .replace(/(\d+)\s*с\s+назад/gu,'$1 s ago');
 if(duration!==key)return left+duration+right;
 const units={'Б':'B','КБ':'KB','МБ':'MB','ГБ':'GB','ТБ':'TB'};
 const bytes=key.replace(/(^|[\s↑↓·|:])(\d+(?:[,.]\d+)?\s*)(ТБ|ГБ|МБ|КБ|Б)(\/с)?(?=$|[\s↑↓·|:])/gu,
    (all,prefix,num,u,per)=>prefix+num+units[u]+(per?'/s':''));
 if(bytes!==key)return left+bytes+right;
 const split=key.split(/(\s*[·•|]\s*)/);
 if(split.length>1){
   let changed=false;
   for(let i=0;i<split.length;i+=2){
     const part=split[i].trim();
     if(has(part)){split[i]=split[i].replace(part,ruToEn[part]);changed=true;}
     else {
       const suffix=part.match(/^(.+?)\s*(\d+)$/u);
       if(suffix&&has(suffix[1])){
         split[i]=split[i].replace(suffix[1],ruToEn[suffix[1]]);
         changed=true;
       }
     }
   }
   if(changed)return left+split.join('')+right;
 }
 // Long informational notices can contain multiple independently translated sentences.
 const sentences=key.match(/[^.!?]+[.!?]?(?:\s+|$)/gu);
 if(sentences&&sentences.length>1){
   let changed=false;
   const translated=sentences.map(segment=>{
     const part=segment.match(/^(\s*)([\s\S]*?)(\s*)$/);
     if(part&&has(part[2])){
       changed=true;
       return part[1]+ruToEn[part[2]]+part[3];
     }
     return segment;
   });
   if(changed)return left+translated.join('')+right;
 }
 return source;
}
function stateFor(original,old){
 if(!old||(original!==old.ru&&original!==old.en)){
   old={ru:original,en:translate(original)};
 }
 return {record:old,value:lang==='en'?old.en:old.ru};
}
function isInsideSkipped(el){
 return !el||el.nodeType!==1||Boolean(el.closest(skip));
}
function translateText(node){
 const parent=node.parentElement;
 if(isInsideSkipped(parent)||parent.closest('textarea'))return;
 // Never change text used as a native select option value.
 if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))return;
 const current=node.nodeValue;
 if(!current||!current.trim())return;
 const r=stateFor(current,originalText.get(node));
 originalText.set(node,r.record);
 if(r.value!==current)node.nodeValue=r.value;
}
function translateAttributes(el){
 if(isInsideSkipped(el))return;
 let map=originalAttrs.get(el);
 if(!map){map=new Map();originalAttrs.set(el,map);}
 for(const key of attributes){
   if(!el.hasAttribute(key))continue;
   const current=el.getAttribute(key);
   if(!current)continue;
   const r=stateFor(current,map.get(key));
   map.set(key,r.record);
   if(r.value!==current)el.setAttribute(key,r.value);
 }
 // Labels on input buttons can be translated, but never text typed by a user.
 if(el.tagName==='INPUT'&&!el.name&&['button','reset','submit'].includes(el.type)){
   const current=el.value;
   if(current){
     const r=stateFor(current,map.get('button-value'));
     map.set('button-value',r.record);
     if(r.value!==current)el.value=r.value;
   }
 }
}
function scan(root){
 if(!root)return;
 if(root.nodeType===3){translateText(root);return;}
 if(root.nodeType!==1||isInsideSkipped(root))return;
 translateAttributes(root);
 const walk=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
 let n;
 while((n=walk.nextNode())){
   if(n.nodeType===3)translateText(n);
   else if(!isInsideSkipped(n))translateAttributes(n);
 }
}
function controls(){
 document.documentElement.dataset.wpoLanguage=lang;
 document.querySelectorAll('button[data-wpo-lang]').forEach(b=>{
   b.setAttribute('aria-pressed',String(b.dataset.wpoLang===lang));
 });
 const utility=document.querySelector('.wpo-utility-switches');
 if(utility)utility.setAttribute('aria-label',lang==='en'?'Language and theme':'Язык и тема');
}
function observe(){
 if(observer&&document.body)
  observer.observe(document.body,{subtree:true,childList:true});
}
function applyAll(){
 if(observer)observer.disconnect();
 queued.clear();
 scheduled=false;
 scan(document.body);
 controls();
 document.documentElement.classList.remove('wpo-en-prepaint');
 observe();
}
function flush(){
 scheduled=false;
 if(!document.body)return;
 if(observer)observer.disconnect();
 const roots=[...queued];queued.clear();
 if(roots.length>MAX_QUEUED)roots.splice(0,roots.length,document.body);
 for(const root of roots)if(root.isConnected)scan(root);
 observe();
}
function enqueue(node){
 if(!node)return;
 if(node.nodeType===3)node=node.parentElement;
 if(!node||!node.isConnected)return;
 if(isInsideSkipped(node))return;
 queued.add(node);
 if(queued.size>MAX_QUEUED){queued.clear();queued.add(document.body);}
 if(!scheduled){scheduled=true;requestAnimationFrame(flush);}
}
function init(){
 if(!document.body)return;
 applyAll();
 // Only newly inserted DOM is observed. Never listen to our own text or
 // attribute writes: avoids observer storms with WPO's native select adapter.
 observer=new MutationObserver(changes=>{
   if(lang!=='en')return;
   for(const record of changes){
     for(const n of record.addedNodes)enqueue(n);
   }
 });
 observe();
}
document.addEventListener('click',event=>{
 const node=event.target;
 const b=node&&typeof node.closest==='function'?node.closest('button[data-wpo-lang]'):null;
 if(b){
   const next=b.dataset.wpoLang;
   if(next!=='ru'&&next!=='en')return;
   lang=next;
   try{localStorage.setItem('wpo-language',next)}catch(_){}
   controls();
   applyAll();
   return;
 }
 // Dialogs can be pre-rendered and populated when opened. Only rescan an
 // open dialog after a user action instead of rescanning the entire node page.
 requestAnimationFrame(()=>{
   const active=document.querySelector('dialog[open]');
   if(active&&lang==='en')enqueue(active);
 });
});
document.addEventListener('change',()=>{
 if(lang!=='en')return;
 requestAnimationFrame(()=>{
   const active=document.querySelector('dialog[open]');
   if(active)enqueue(active);
 });
});
if(document.readyState==='loading')
 document.addEventListener('DOMContentLoaded',init,{once:true});
else init();
})();
</script>'''

ADDON=r'''
# WPO_C333_STABLE_DYNAMIC_I18N_V11
import json as _wpo_v11_json

def _wpo_v11_build(existing_js):
    dictionary_label = 'const dictionary='
    pairs_label = 'const extraPairs='
    if existing_js.count(dictionary_label)!=1 or existing_js.count(pairs_label)!=1:
        raise RuntimeError('WPO original i18n dataset not found; no changes made')
    dictionary_start=existing_js.index(dictionary_label)+len(dictionary_label)
    dictionary, _ = _wpo_v11_json.JSONDecoder().raw_decode(existing_js[dictionary_start:])
    pair_start=existing_js.index(pairs_label)+len(pairs_label)
    pairs, _ = _wpo_v11_json.JSONDecoder().raw_decode(existing_js[pair_start:])
    if (not isinstance(dictionary,dict) or len(dictionary)<600 or
        not isinstance(pairs,list) or len(pairs)<300):
        raise RuntimeError('WPO translation resources are incomplete')
    combined={str(ru):str(en) for en,ru in pairs}
    combined.update(_WPO_V11_EXTRA)
    compiled_pairs=[[en,ru] for ru,en in combined.items()]
    dictionary_json=_wpo_v11_json.dumps(
        dictionary,ensure_ascii=False,separators=(',',':')
    ).replace('<','\\u003c')
    pairs_json=_wpo_v11_json.dumps(
        compiled_pairs,ensure_ascii=False,separators=(',',':')
    ).replace('<','\\u003c')
    return (_WPO_V11_JS_TEMPLATE
            .replace('__DICTIONARY__',dictionary_json)
            .replace('__PAIRS__',pairs_json))

_WPO_V11_EXTRA = _wpo_v11_json.loads(r"""{"Настройки ноды":"Node settings","конфигурация":"configuration","выбранная нода":"selected node","выбранные ноды":"selected nodes","отдельная конфигурация":"separate configuration","Название и шаблон сайта":"Name and website template","Шаблоны берутся из раздела «Настройки» панели, включая ваши собственные. На подключённом Node Agent 0.2 выбранный шаблон публикуется на домене ноды.":"Templates come from the panel Settings, including your own. With Node Agent 0.2 connected, the selected template is published to the node domain.","Шаблоны берутся из раздела «Настройки» панели, включая ваши собственные.":"Templates come from the panel Settings, including your own.","На подключённом Node Agent 0.2 выбранный шаблон публикуется на домене ноды.":"With Node Agent 0.2 connected, the selected template is published to the node domain.","Стандартная страница ноды":"Standard node page","Стандартный шаблон":"Default template","Название ноды":"Node name","Выбранные ноды":"Selected nodes","выбранные ноды":"selected nodes","одна выбранная нода":"one selected node","Вся сеть":"Entire network","основная и":"main and","дополнительных нод":"additional nodes","дополнительные ноды":"additional nodes","Подключений Happ":"Happ connections","подключений Happ":"Happ connections","протокола":"protocols","нод":"nodes","Новый пользователь":"New user","Сохранено автоматически":"Saved automatically","Установлено автоматически":"Installed automatically","установлен автоматически.":"was installed automatically.","Проверка REALITY":"REALITY check","Параметры доступа":"Access parameters","Сохранение применяется ко всей сети после проверки каждой ноды.":"Changes are applied across the network after each node is verified.","Сохранение применяется ко всем REALITY-подключениям этой ноды.":"Changes apply to all REALITY connections on this node.","Изменения применяются ко всем REALITY-подключениям этой ноды.":"Changes apply to all REALITY connections on this node.","Шаблон сайта на вашем домене настраивается отдельно.":"The website template on your domain is configured separately.","После смены SNI обновите подписки.":"Update subscriptions after changing SNI.","Укажите домены для добавления или удаления":"Enter domains to add or remove","Укажите домены для добавления или удаления.":"Enter domains to add or remove.","Подписка для Happ":"Happ subscription","Текущий шаблон":"Current template","Выбрать шаблон":"Select template","Изменить шаблон":"Change template","Открыть настройку REALITY":"Open REALITY settings","Шаблон сайта":"Website template","Имя ноды":"Node name","Список нод":"Node list","Начальная страница":"Home page","Создание ноды":"Create node","Подключённая нода":"Connected node","настройки ноды":"node settings","Настройки REALITY":"REALITY settings","Открыть настройки REALITY":"Open REALITY settings","Настройки подключения":"Connection settings","Опции подключения":"Connection options","Создать пользователя":"Create user","Пользователь":"User","Нода":"Node"}""")
_WPO_V11_JS_TEMPLATE = r"""<script>
(()=>{
'use strict';
const dictionary=__DICTIONARY__;
const extraPairs=__PAIRS__;
const ruToEn=Object.assign(Object.create(null),dictionary);
for(const pair of extraPairs){
 if(!Array.isArray(pair)||pair.length!==2)continue;
 const en=pair[0],ru=pair[1];
 if(typeof ru==='string'&&typeof en==='string'&&/[А-Яа-яЁё]/u.test(ru))ruToEn[ru]=en;
}
const originalText=new WeakMap(),originalAttrs=new WeakMap();
const skip='script,style,noscript,pre,code,svg,select[data-wpo-popup-ready="1"],[contenteditable],[data-wpo-no-translate],.wpo-utility-switches';
const attributes=['title','placeholder','aria-label','alt'];
const isCyrillic=/[А-Яа-яЁё]/u;
let lang='ru';
try{lang=localStorage.getItem('wpo-language')==='en'?'en':'ru'}catch(_){}
let observer=null,scheduled=false;
const queued=new Set(),MAX_QUEUED=64;
const has=(x)=>Object.prototype.hasOwnProperty.call(ruToEn,x);
function translatedWord(input){
 if(has(input))return ruToEn[input];
 return input;
}
function translate(source){
 if(!source||!isCyrillic.test(source))return source;
 const m=source.match(/^(\s*)([\s\S]*?)(\s*)$/);
 if(!m)return source;
 const key=m[2].replace(/\s+/g,' ').trim();
 const left=m[1],right=m[3];
 if(has(key))return left+ruToEn[key]+right;
 const fleet=key.match(/^Вся сеть\s*[·–-]\s*основная и (\d+) дополнительных нод$/u);
 if(fleet)return left+'Entire network · main and '+fleet[1]+' additional nodes'+right;
 const summary=key.match(/^(\d+)\s+нод\s*[×x]\s*(\d+)\s+протокола\s*=\s*(\d+)\s+подключений Happ$/u);
 if(summary)return left+summary[1]+(Number(summary[1])===1?' node':' nodes')+' × '+summary[2]+(Number(summary[2])===1?' protocol':' protocols')+' = '+summary[3]+' Happ connections'+right;
 const openflux=key.match(/^(OpenFlux|Xray)\s+([\d.]+)\s+установлен автоматически\.$/u);
 if(openflux)return left+openflux[1]+' '+openflux[2]+' was installed automatically.'+right;
 const arrow=key.match(/^([↑↓])\s*(.+)$/u);
 if(arrow&&has(arrow[2]))return left+arrow[1]+' '+ruToEn[arrow[2]]+right;
 const decorated=key.match(/^([+＋✓✔⚠!•●]\s*)(.+)$/u);
 if(decorated&&has(decorated[2]))return left+decorated[1]+ruToEn[decorated[2]]+right;
 const shown=key.match(/^Показано\s+(\d+)\s+из\s+(\d+)(\s*·\s*(.+))?$/u);
 if(shown)return left+'Showing '+shown[1]+' of '+shown[2]+
    (shown[4]?' · '+translatedWord(shown[4]):'')+right;
 const cores=key.match(/^Ядер:\s*(.*?)\s*·\s*гипервизор:\s*(.+)$/u);
 if(cores)return left+'Cores: '+cores[1]+' · hypervisor: '+cores[2]+right;
 const duration=key.replace(/(\d+)\s*д\./gu,'$1 d.')
   .replace(/(\d+)\s*ч\./gu,'$1 h.')
   .replace(/(\d+)\s*мин\./gu,'$1 min.')
   .replace(/(\d+)\s*мин\s+назад/gu,'$1 min ago')
   .replace(/(\d+)\s*с\s+назад/gu,'$1 s ago');
 if(duration!==key)return left+duration+right;
 const units={'Б':'B','КБ':'KB','МБ':'MB','ГБ':'GB','ТБ':'TB'};
 const bytes=key.replace(/(^|[\s↑↓·|:])(\d+(?:[,.]\d+)?\s*)(ТБ|ГБ|МБ|КБ|Б)(\/с)?(?=$|[\s↑↓·|:])/gu,
    (all,prefix,num,u,per)=>prefix+num+units[u]+(per?'/s':''));
 if(bytes!==key)return left+bytes+right;
 const split=key.split(/(\s*[·•|]\s*)/);
 if(split.length>1){
   let changed=false;
   for(let i=0;i<split.length;i+=2){
     const part=split[i].trim();
     if(has(part)){split[i]=split[i].replace(part,ruToEn[part]);changed=true;}
     else {
       const suffix=part.match(/^(.+?)\s*(\d+)$/u);
       if(suffix&&has(suffix[1])){
         split[i]=split[i].replace(suffix[1],ruToEn[suffix[1]]);
         changed=true;
       }
     }
   }
   if(changed)return left+split.join('')+right;
 }
 // Long informational notices can contain multiple independently translated sentences.
 const sentences=key.match(/[^.!?]+[.!?]?(?:\s+|$)/gu);
 if(sentences&&sentences.length>1){
   let changed=false;
   const translated=sentences.map(segment=>{
     const part=segment.match(/^(\s*)([\s\S]*?)(\s*)$/);
     if(part&&has(part[2])){
       changed=true;
       return part[1]+ruToEn[part[2]]+part[3];
     }
     return segment;
   });
   if(changed)return left+translated.join('')+right;
 }
 return source;
}
function stateFor(original,old){
 if(!old||(original!==old.ru&&original!==old.en)){
   old={ru:original,en:translate(original)};
 }
 return {record:old,value:lang==='en'?old.en:old.ru};
}
function isInsideSkipped(el){
 return !el||el.nodeType!==1||Boolean(el.closest(skip));
}
function translateText(node){
 const parent=node.parentElement;
 if(isInsideSkipped(parent)||parent.closest('textarea'))return;
 // Never change text used as a native select option value.
 if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))return;
 const current=node.nodeValue;
 if(!current||!current.trim())return;
 const r=stateFor(current,originalText.get(node));
 originalText.set(node,r.record);
 if(r.value!==current)node.nodeValue=r.value;
}
function translateAttributes(el){
 if(isInsideSkipped(el))return;
 let map=originalAttrs.get(el);
 if(!map){map=new Map();originalAttrs.set(el,map);}
 for(const key of attributes){
   if(!el.hasAttribute(key))continue;
   const current=el.getAttribute(key);
   if(!current)continue;
   const r=stateFor(current,map.get(key));
   map.set(key,r.record);
   if(r.value!==current)el.setAttribute(key,r.value);
 }
 // Labels on input buttons can be translated, but never text typed by a user.
 if(el.tagName==='INPUT'&&!el.name&&['button','reset','submit'].includes(el.type)){
   const current=el.value;
   if(current){
     const r=stateFor(current,map.get('button-value'));
     map.set('button-value',r.record);
     if(r.value!==current)el.value=r.value;
   }
 }
}
function scan(root){
 if(!root)return;
 if(root.nodeType===3){translateText(root);return;}
 if(root.nodeType!==1||isInsideSkipped(root))return;
 translateAttributes(root);
 const walk=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
 let n;
 while((n=walk.nextNode())){
   if(n.nodeType===3)translateText(n);
   else if(!isInsideSkipped(n))translateAttributes(n);
 }
}
function controls(){
 document.documentElement.dataset.wpoLanguage=lang;
 document.querySelectorAll('button[data-wpo-lang]').forEach(b=>{
   b.setAttribute('aria-pressed',String(b.dataset.wpoLang===lang));
 });
 const utility=document.querySelector('.wpo-utility-switches');
 if(utility)utility.setAttribute('aria-label',lang==='en'?'Language and theme':'Язык и тема');
}
function observe(){
 if(observer&&document.body)
  observer.observe(document.body,{subtree:true,childList:true});
}
function applyAll(){
 if(observer)observer.disconnect();
 queued.clear();
 scheduled=false;
 scan(document.body);
 controls();
 document.documentElement.classList.remove('wpo-en-prepaint');
 observe();
}
function flush(){
 scheduled=false;
 if(!document.body)return;
 if(observer)observer.disconnect();
 const roots=[...queued];queued.clear();
 if(roots.length>MAX_QUEUED)roots.splice(0,roots.length,document.body);
 for(const root of roots)if(root.isConnected)scan(root);
 observe();
}
function enqueue(node){
 if(!node)return;
 if(node.nodeType===3)node=node.parentElement;
 if(!node||!node.isConnected)return;
 if(isInsideSkipped(node))return;
 queued.add(node);
 if(queued.size>MAX_QUEUED){queued.clear();queued.add(document.body);}
 if(!scheduled){scheduled=true;requestAnimationFrame(flush);}
}
function init(){
 if(!document.body)return;
 applyAll();
 // Only newly inserted DOM is observed. Never listen to our own text or
 // attribute writes: avoids observer storms with WPO's native select adapter.
 observer=new MutationObserver(changes=>{
   if(lang!=='en')return;
   for(const record of changes){
     for(const n of record.addedNodes)enqueue(n);
   }
 });
 observe();
}
document.addEventListener('click',event=>{
 const node=event.target;
 const b=node&&typeof node.closest==='function'?node.closest('button[data-wpo-lang]'):null;
 if(b){
   const next=b.dataset.wpoLang;
   if(next!=='ru'&&next!=='en')return;
   lang=next;
   try{localStorage.setItem('wpo-language',next)}catch(_){}
   controls();
   applyAll();
   return;
 }
 // Dialogs can be pre-rendered and populated when opened. Only rescan an
 // open dialog after a user action instead of rescanning the entire node page.
 requestAnimationFrame(()=>{
   const active=document.querySelector('dialog[open]');
   if(active&&lang==='en')enqueue(active);
 });
});
document.addEventListener('change',()=>{
 if(lang!=='en')return;
 requestAnimationFrame(()=>{
   const active=document.querySelector('dialog[open]');
   if(active)enqueue(active);
 });
});
if(document.readyState==='loading')
 document.addEventListener('DOMContentLoaded',init,{once:true});
else init();
})();
</script>"""
WPO_C333_I18N_JS = _wpo_v11_build(WPO_C333_I18N_JS)
'''

def check_source(source):
    required=(
      '# WPO_C333_MANUAL_LOGIN_V1',
      '# WPO_C333_LANGUAGE_THEME_V1',
      '# WPO_C333_I18N_V8_PRELOAD',
      '# WPO_C333_V9_STABLE_SELECTOR',
      '# WPO_C333_AUDITED_EN_V10',
      'WPO_SELECT_POPOVER_V2_BEGIN',
    )
    for marker in required:
        if marker not in source:
            raise RuntimeError('This WPO build needs the previous stable UI updates: '+marker)
    if 'WPO_NAV_NATIVE_RECOVERY_V2_BEGIN' in source:
        raise RuntimeError('Incompatible legacy navigation patch found')
    if source.count('WPO_C333_I18N_JS = ')<2:
        raise RuntimeError('Expected installed WPO translation layers were not found')

def transform(source):
    check_source(source)
    if MARK in source:return source,True
    updated=source+'\n'+ADDON
    ast.parse(updated,filename=str(TARGET))
    compile(updated,str(TARGET),'exec')
    for important in ('def routing_ui(', 'def theme_button():',
                       '# WPO_SELECT_POPOVER_V2_BEGIN','wppNavigationTimer'):
        if source.count(important)!=updated.count(important):
            raise RuntimeError('WPO functionality was unexpectedly modified: '+important)
    return updated,False

def healthy():
    if subprocess.run(['systemctl','is-active','--quiet',SERVICE]).returncode:return False
    try:
        try:
            response=urlopen('http://127.0.0.1:8090/',timeout=2)
            code=response.status
            response.close()
        except HTTPError as error:code=error.code
        return 200<=code<500
    except Exception:return False

def main():
    mode=sys.argv[1] if len(sys.argv)==2 else ''
    if mode not in ('--check','--apply'):
        raise SystemExit('Usage: --check | --apply')
    if mode=='--apply' and os.geteuid()!=0:
        raise SystemExit('Use sudo for applying WPO updates')
    if not TARGET.is_file() or TARGET.is_symlink() or not (APP/'panel.py').is_file():
        raise SystemExit('Installed WPO not found; nothing has changed')
    original=TARGET.read_text(encoding='utf-8')
    updated,already=transform(original)
    if already:
        print('✓ WPO stable v11 translation already installed')
        return
    print('✓ WPO current installation verified; stable translation v11 compatible')
    if mode=='--check':
        print('✓ Check-only: no changes made')
        return
    if not healthy():
        raise RuntimeError('WPO was unhealthy before patch; no changes made')
    backup=Path('/var/backups/web-panel-online')/('safe-i18n-v11-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(os.getpid()))
    backup.mkdir(parents=True,mode=0o700,exist_ok=False)
    shutil.copy2(TARGET,backup/'wpp_ui.py')
    fd,tmp=tempfile.mkstemp(prefix='.wpo-i18n-v11-',suffix='.py',dir=APP)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:out.write(updated)
        saved=TARGET.stat()
        os.chmod(tmp,stat.S_IMODE(saved.st_mode))
        os.chown(tmp,saved.st_uid,saved.st_gid)
        os.replace(tmp,TARGET)
        subprocess.run(['systemctl','restart',SERVICE],check=True)
        for i in range(20):
            if healthy():
                print('✓ EN translations and stable Nodes interaction installed')
                print('✓ Backup:',backup/'wpp_ui.py')
                return
            time.sleep(1)
        raise RuntimeError('WPO did not respond after the update')
    except Exception:
        shutil.copy2(backup/'wpp_ui.py',TARGET)
        subprocess.run(['systemctl','restart',SERVICE],check=False)
        print('✖ Installation failed, previous WPO interface restored',file=sys.stderr)
        raise
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

if __name__=='__main__':main()
