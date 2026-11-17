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
NEW_MARK='# WPO_C333_I18N_V3_BIDIRECTIONAL'
OLD_MARK='# WPO_C333_LANGUAGE_THEME_V1'

LANGUAGE_JS = r'''<script>
(()=>{
'use strict';
const dictionary=__DICTIONARY__;
const extraPairs=[["ID","ID"],["ENABLED","ВКЛЮЧЕНО"],["CONNECTION","ПОДКЛЮЧЕНИЕ"],["ROUTE","МАРШРУТ"],["PORT","ПОРТ"],["PROTOCOL","ПРОТОКОЛ"],["CLIENTS","КЛИЕНТЫ"],["Enabled","Включено"],["Disabled","Отключено"],["Direct","Напрямую"],["Main panel domain","Основной домен панели"],["Main connection","Основное подключение"],["Main node","Основная нода"],["Online","В сети"],["Installing","Установка"],["Registration","Регистрация"],["Offline","Не в сети"],["Error","Ошибка"],["Add node","Добавить ноду"],["Template","Шаблон"],["Node management","Управление нодами"],["Server resources","Ресурсы сервера"],["Cumulative traffic","Суммарный трафик"],["Total traffic","Всего трафика"],["Proxy traffic","Трафик прокси"],["CPU","Процессор"],["Memory","Память"],["Swap","Подкачка"],["Disk","Диск"],["Clients","Клиенты"],["Subscriptions","Подписки"],["Subscription","Подписка"],["Traffic","Трафик"],["Total","Всего"],["Transferring data","Передают трафик"],["Online now","Сейчас в сети"],["Services and version","Службы и версия"],["Running","Работает"],["Stopped","Остановлено"],["Server status","Состояние сервера"],["Upload","Отправка"],["Download","Получение"],["Sent","Отправлено"],["Received","Получено"],["Last measurement","Последний замер"],["Users and subscriptions","Пользователи и подписки"],["Management","Управление"],["Access / QR","Доступ / QR"],["Separate link","Отдельная ссылка"],["Search by client name","Поиск по имени клиента"],["All clients","Все клиенты"],["All protocols","Все протоколы"],["Default order","Обычный порядок"],["Access","Доступ"],["Protocols","Протоколы"],["Users","Пользователи"],["User","Пользователь"],["No traffic","Нет трафика"],["Subscriptions and individual client connections","Подписки и отдельные подключения клиентов"],["Transferring traffic","Передают трафик"],["VPS uptime","Время работы VPS"],["Xray uptime","Время работы Xray"],["Xray memory","Память Xray"],["Xray tasks","Задачи Xray"],["Load","Нагрузка"],["Proxy traffic only. Activity means traffic in the last 90 seconds, not the number of connected devices.","Только трафик прокси. Активность означает передачу данных за последние 90 секунд, а не число подключённых устройств."],["Update center","Центр обновлений"],["Update management","Управление обновлениями"],["Update lists","Обновить списки"],["Refresh lists","Обновить списки"],["Stable · automatic","Стабильная · автоматически"],["Automatically install new versions","Автоматически устанавливать новые версии"],["Automatically update Xray and OpenFlux","Автоматически обновлять Xray и OpenFlux"],["Every 6 hours WPP checks GitHub and installs only a new stable release.","Раз в 6 часов WPO проверяет GitHub и устанавливает только новую стабильную версию."],["You can install a new version or return to the previous one. The rollback copy is kept only during installation.","Можно установить новую версию или вернуться к предыдущей. Копия для отката хранится только во время установки."],["WEB PANEL ONLINE","WEB PANEL ONLINE"],["Interface, connection manager, and service modules","Интерфейс, управление подключениями и служебные модули"],["Components","Компоненты"],["Core","Основное"],["Installed version","Установленная версия"],["Available version","Доступная версия"],["Version","Версия"],["Install","Установить"],["Load version list","Загрузить список версий"],["Versions loaded.","Версии загружены."],["Xray and OpenFlux update independently of the panel","Xray и OpenFlux обновляются независимо от панели"],["Done","Готово"],["Automatically","Автоматически"],["Diagnostics and recovery","Диагностика и восстановление"],["Diagnostics","Диагностика"],["Recovery","Восстановление"],["Public CDN","Публичный CDN"],["WPP origin","Исходный сервер WPO"],["DNS, TLS, edge responses and caching","DNS, TLS, ответы CDN и кэширование"],["HTTPS, Host and Caddy test route","HTTPS, Host и проверочный маршрут Caddy"],["Provider method, path and local inbound","Метод провайдера, путь и локальный входящий порт"],["The check finds issues, and recovery safely rebuilds only local WPP components.","Проверка выявляет проблемы, а восстановление безопасно пересоздаёт только локальные компоненты WPO."],["No VLESS CDN connections created","Подключения VLESS CDN ещё не созданы"],["Check","Проверить"],["No check has been run yet","Проверка ещё не запускалась"],["Results and recommendations will appear here.","Здесь появятся результаты и рекомендации."],["Site templates","Шаблоны сайтов"],["Create a custom placeholder","Создать свой шаблон"],["Create","Создать"],["Preview","Предпросмотр"],["Apply","Применить"],["Click Preview to see the site. Apply publishes it to the domain immediately.","Нажмите «Предпросмотр», чтобы увидеть сайт. «Применить» сразу опубликует его на домене."],["Name, description, and custom HTML. The template will appear in this collection.","Название, описание и свой HTML. Шаблон появится в этой коллекции."],["Beauty salon","Салон красоты"],["Car showroom","Автосалон"],["Car service","Автосервис"],["Open coffee shop","Открытие кофейни"],["Technical works","Технические работы"],["Medical clinic","Медицинская клиника"],["Smartphone repair","Ремонт смартфонов"],["Diagnostic center","Центр диагностики"],["Settings backup","Резервная копия настроек"],["Stored on your computer","Хранится на вашем компьютере"],["Download backup","Скачать резервную копию"],["Select archive","Выбрать архив"],["Install backup","Установить копию"],["Administrator password","Пароль администратора"],["New password","Новый пароль"],["Save password","Сохранить пароль"],["Settings","Настройки"],["Dashboard","Главная"],["Updates","Обновления"],["Connection manager","Управление подключениями"],["Connection","Подключение"],["Connections","Подключения"],["Nodes","Ноды"],["Node","Нода"],["Select connection","Выберите подключение"],["Select protocol","Выберите протокол"],["Select node","Выберите ноду"],["Select template","Выберите шаблон"],["New user","Новый пользователь"],["Add user","Добавить пользователя"],["Create client","Создать клиента"],["Save","Сохранить"],["Cancel","Отмена"],["Delete","Удалить"],["Edit","Изменить"],["Copy","Копировать"],["Copied","Скопировано"],["Open","Открыть"],["Close","Закрыть"],["Back","Назад"],["Next","Далее"],["Refresh","Обновить"],["Update","Обновить"],["Status","Статус"],["Services","Службы"],["Name","Название"],["Date","Дата"],["Time","Время"],["Domain","Домен"],["Port","Порт"],["Protocol","Протокол"],["No connections","Нет подключений"],["No clients","Нет клиентов"],["No nodes","Нет нод"],["Loading","Загрузка"],["Loading…","Загрузка…"],["Waiting","Ожидание"],["Unknown","Неизвестно"],["Available","Доступно"],["Unavailable","Недоступно"],["Active","Активно"],["Inactive","Неактивно"],["Automatic","Автоматически"],["Manual","Вручную"],["On","Вкл."],["Off","Выкл."],["Traffic statistics","Статистика трафика"],["Upload traffic","Отправленный трафик"],["Download traffic","Полученный трафик"],["Sent traffic","Отправленный трафик"],["Received traffic","Полученный трафик"],["Copy link","Скопировать ссылку"],["Copy config","Скопировать конфигурацию"],["QR code","QR-код"],["Client status","Статус клиента"],["No updates available","Нет доступных обновлений"],["All services running","Все службы работают"],["Not used","Не используется"],["Not configured","Не настроено"],["Not assigned","Не назначено"],["Will be assigned when a client is created","Будет назначен при создании клиента"],["Security","Безопасность"],["Country","Страна"],["View","Просмотр"],["Main panel","Основная панель"],["Main domain","Основной домен"],["1 h","1 ч"],["6 h","6 ч"],["24 h","24 ч"],["24 hours","24 часа"],["Last 24 hours","Последние 24 часа"],["Last 1 hour","Последний час"],["Last 6 hours","Последние 6 часов"],["Separate connection","Отдельное подключение"],["Search","Поиск"],["Client","Клиент"],["Client access","Доступ клиента"],["Client connections","Подключения клиента"],["Summary","Сводка"],["None","Нет"],["Default","По умолчанию"]];
const enToRu=Object.create(null);
const ruToEn=Object.create(null);
for(const [ru,en] of Object.entries(dictionary)){
  if(!Object.prototype.hasOwnProperty.call(enToRu,en))enToRu[en]=ru;
  ruToEn[ru]=en;
}
for(const [en,ru] of extraPairs){enToRu[en]=ru;ruToEn[ru]=en;}
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
const has=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
function translate(text,target){
 const lookup=target==='en'?ruToEn:enToRu;
 const m=text.match(/^(\s*)([\s\S]*?)(\s*)$/);
 if(!m)return text;
 const key=m[2];
 if(has(lookup,key))return m[1]+lookup[key]+m[3];
 const number=key.match(/^(\d+)\s+(users?|clients?|subscriptions?)$/i);
 if(number){
   const n=Number(number[1]),form=number[2].toLowerCase();
   if(target==='ru'){
     const many=n%100>=11&&n%100<=14||n%10<1||n%10>4;
     const few=n%10>=2&&n%10<=4&&!many;
     const noun=form.startsWith('user')?'пользоват':form.startsWith('client')?'клиент':'подпис';
     const word=noun==='пользоват'?(many?'пользователей':few?'пользователя':'пользователь'):noun==='клиент'?(many?'клиентов':few?'клиента':'клиент'):(many?'подписок':few?'подписки':'подписка');
     return m[1]+number[1]+' '+word+m[3];
   }
 }
 const prefix=key.match(/^(\d+)\s*[·.]\s*(.+)$/);
 if(prefix&&has(lookup,prefix[2]))return m[1]+prefix[1]+' · '+lookup[prefix[2]]+m[3];
 const pieces=key.split(/(\s*[·•|:]\s*)/);
 if(pieces.length>1){
   let changed=false;
   for(let i=0;i<pieces.length;i+=2){
     const segment=pieces[i].trim();
     if(has(lookup,segment)){
       pieces[i]=pieces[i].replace(segment,lookup[segment]);
       changed=true;
     }
   }
   if(changed)return m[1]+pieces.join('')+m[3];
 }
 return text;
}
function restoreOrTranslate(current,state){
 if(!state||current!==state.source&&current!==state.ru&&current!==state.en){
   state={source:current,ru:translate(current,'ru'),en:translate(current,'en')};
 }
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
  if(!current||!current.trim())return;
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
  document.title=native?translate(native[1],language)+' · WPO':translate(pageTitle,language);
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
        print('✓ Переводчик v3 уже установлен; изменений нет.')
        return
    print('✓ Проверка исходника пройдена. Словарь:',count,'переводов.')
    if mode=='--check':
        print('✓ Режим проверки: сервер и файлы не изменены.')
        return
    if not healthy():
        raise SystemExit('WPO не отвечает до обновления. Ничего не изменено.')
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir=Path('/var/backups/web-panel-online')/('i18n-v3-'+timestamp+'-'+str(os.getpid()))
    backup_dir.mkdir(parents=True,mode=0o700,exist_ok=False)
    shutil.copy2(TARGET,backup_dir/'wpp_ui.py')
    descriptor,tmp=tempfile.mkstemp(prefix='.wpo-i18n-v3-',suffix='.py',dir=APP)
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
                print('✓ Двусторонний перевод RU/EN обновлён для всех основных разделов.')
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
