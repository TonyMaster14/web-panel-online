#!/usr/bin/env python3
"""WPO: isolated, reversible updates over last working c333e00 UI.

Install in two steps:
  --check-login / --apply-login     remove automatic login + style sign-in button
  --check-buttons / --apply-buttons add RU/EN and sun/moon, without changing navigation

Only /opt/tproxy-panel/wpp_ui.py is ever replaced; backups and rollback enabled.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

APP = Path("/opt/tproxy-panel")
TARGET = APP / "wpp_ui.py"
SERVICE = "tproxy-panel.service"
I18N_URL = "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/02f1908bfb0e19f9e3e134732cbf3a3ffe96e0b0/scripts/wpo-c333-i18n.json"
I18N_BLOB = "e4a8a3fa4905e35c89b7688112553865b9ef0202"
LOGIN_MARK = "# WPO_C333_MANUAL_LOGIN_V1"
BUTTON_MARK = "# WPO_C333_LANGUAGE_THEME_V1"

LOGIN_CSS = r"""
.login-card #loginSubmit{position:relative!important;box-sizing:border-box!important;display:flex!important;align-items:center!important;justify-content:center!important;width:min(184px,100%)!important;min-height:43px!important;height:43px!important;margin:6px auto 0!important;padding:0 34px!important;gap:0!important;cursor:pointer!important;touch-action:manipulation}
.login-card #loginSubmit b{font-size:17px!important;font-weight:750!important;line-height:1.2!important;text-align:center!important}
.login-card #loginSubmit span{position:absolute!important;right:14px!important;top:50%!important;transform:translateY(-50%)!important;font-size:18px!important;line-height:1!important;pointer-events:none!important}
.login-card #loginSubmit:hover span{transform:translate(2px,-50%)!important}
"""

BUTTON_CSS = r"""
/* WPO: only new header/login controls. All selects and node cards untouched. */
.wpo-utility-switches{display:inline-flex!important;align-items:center!important;gap:12px!important;min-width:0;vertical-align:middle}
.wpo-utility-switches .wpo-language-switch{display:inline-flex!important;align-items:center!important;box-sizing:border-box!important;width:90px!important;min-width:90px!important;height:38px!important;margin:0!important;padding:3px!important;border:1px solid var(--line)!important;border-radius:999px!important;background:var(--input)!important}
.wpo-utility-switches .wpo-language-switch button{box-sizing:border-box!important;display:grid!important;place-items:center!important;flex:1 1 0!important;min-width:0!important;height:30px!important;margin:0!important;padding:0!important;border:0!important;border-radius:999px!important;background:transparent!important;color:var(--muted)!important;font:700 11px/1 system-ui,sans-serif!important;transform:none!important;box-shadow:none!important;cursor:pointer!important}
.wpo-utility-switches .wpo-language-switch button[aria-pressed="true"]{background:var(--text)!important;color:var(--input)!important;box-shadow:0 1px 5px #0002!important}
.wpo-utility-switches .wpo-language-switch button:focus-visible,.wpo-utility-switches .wpo-theme-pill:focus-visible{outline:2px solid var(--accent)!important;outline-offset:2px!important}
.wpo-utility-switches button.wpo-theme-pill{box-sizing:border-box!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;flex:0 0 38px!important;width:38px!important;min-width:38px!important;max-width:38px!important;height:38px!important;min-height:38px!important;max-height:38px!important;margin:0!important;padding:0!important;border:1px solid var(--line)!important;border-radius:50%!important;background:var(--input)!important;color:var(--text)!important;cursor:pointer!important;transform:none!important}
.wpo-utility-switches .wpo-theme-pill .theme-label{display:none!important}
.wpo-utility-switches .wpo-theme-pill svg{display:block!important;width:18px!important;height:18px!important;flex:0 0 18px!important}
:root[data-theme="light"] .wpo-utility-switches .wpo-theme-moon{display:none!important}
:root:not([data-theme="light"]) .wpo-utility-switches .wpo-theme-sun{display:none!important}
.login-theme{right:34px!important}
.appbar-tools .wpo-utility-switches{margin:0!important}
@media(max-width:700px){
 .login-theme{right:22px!important}
 .wpo-utility-switches{gap:10px!important}
 .wpo-utility-switches .wpo-language-switch{width:82px!important;min-width:82px!important;height:36px!important}
 .wpo-utility-switches .wpo-language-switch button{height:28px!important}
 .wpo-utility-switches button.wpo-theme-pill{flex:0 0 36px!important;width:36px!important;min-width:36px!important;max-width:36px!important;height:36px!important;min-height:36px!important;max-height:36px!important}
}
"""

LANGUAGE_JS = r"""<script>
(()=>{
'use strict';
const dictionary=__DICTIONARY__;
const savedText=new WeakMap(),savedAttrs=new WeakMap();
const skip='script,style,noscript,textarea,code,pre,svg,button,select,option,form,dialog,[contenteditable],[data-wpo-no-translate],.wpo-utility-switches';
let language='ru';
try{language=localStorage.getItem('wpo-language')==='en'?'en':'ru'}catch(_){}
const originalTitle=document.title;
function translate(s){
 const m=s.match(/^(\s*)([\s\S]*?)(\s*)$/);
 if(!m)return s;
 const key=m[2].replace(/\s+/g,' ');
 return Object.prototype.hasOwnProperty.call(dictionary,key)?m[1]+dictionary[key]+m[3]:s;
}
function apply(){
 if(!document.body)return;
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 let node;
 while((node=walker.nextNode())){
   const el=node.parentElement;
   if(!el||el.closest(skip))continue;
   const current=node.nodeValue;
   let record=savedText.get(node);
   if(!record||(current!==record.ru&&current!==record.en)){
     record={ru:current,en:translate(current)};
     savedText.set(node,record);
   }
   const desired=language==='en'?record.en:record.ru;
   if(current!==desired)node.nodeValue=desired;
 }
 for(const el of document.querySelectorAll('[placeholder],[title],[aria-label]')){
   if(el.closest(skip))continue;
   let map=savedAttrs.get(el);
   if(!map){map=new Map();savedAttrs.set(el,map)}
   for(const name of ['placeholder','title','aria-label']){
     if(!el.hasAttribute(name))continue;
     const current=el.getAttribute(name);
     let record=map.get(name);
     if(!record||(current!==record.ru&&current!==record.en)){
       record={ru:current,en:translate(current)};
       map.set(name,record);
     }
     const desired=language==='en'?record.en:record.ru;
     if(current!==desired)el.setAttribute(name,desired);
   }
 }
 const parts=originalTitle.match(/^(.*?)\s*[·]\s*WPO$/);
 if(parts){
   const key=parts[1].trim();
   document.title=language==='en'&&dictionary[key]?dictionary[key]+' · WPO':originalTitle;
 }
 document.documentElement.lang=language;
 document.querySelectorAll('button[data-wpo-lang]').forEach(button=>{
   button.setAttribute('aria-pressed',String(button.dataset.wpoLang===language));
 });
}
document.addEventListener('click',event=>{
 const t=event.target;
 const button=t&&typeof t.closest==='function'?t.closest('button[data-wpo-lang]'):null;
 if(!button)return;
 const next=button.dataset.wpoLang;
 if(next!=='ru'&&next!=='en')return;
 language=next;
 try{localStorage.setItem('wpo-language',language)}catch(_){}
 apply();
});
if(document.readyState==='loading')
 document.addEventListener('DOMContentLoaded',apply,{once:true});
else apply();
})();
</script>"""

NEW_THEME = '''def theme_button():
    return ("""<div class="wpo-utility-switches" aria-label="Язык и тема">
      <div class="wpo-language-switch" role="group" aria-label="Язык интерфейса">
        <button type="button" data-wpo-lang="ru" aria-pressed="true">RU</button>
        <button type="button" data-wpo-lang="en" aria-pressed="false">EN</button>
      </div>
      <button type="button" class="quiet wpo-theme-pill" data-theme-toggle aria-label="Переключить тему">
        <svg class="wpo-theme-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>
        <svg class="wpo-theme-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.6 15.5A9 9 0 0 1 8.5 3.4 9 9 0 1 0 20.6 15.5Z"/></svg>
        <span class="theme-label" hidden>Тёмная тема</span>
      </button>
    </div>""")'''

OLD_THEME = """def theme_button(): return '<button type="button" class="quiet" data-theme-toggle>'+icon('sun')+'<span class="theme-label">Тёмная тема</span><i class="theme-track" aria-hidden="true"></i></button>'"""


def only_one(source, fragment):
    count=source.count(fragment)
    if count!=1:
        raise RuntimeError(f"Неизвестная версия интерфейса WPO: {fragment[:55]} встречается {count} раз.")


def verify_original(source):
    for marker in ("# WPO_SELECT_POPOVER_V2_BEGIN", "def login_ui(path):",
                   "def theme_button():", "def routing_ui("):
        if marker not in source:
            raise RuntimeError("Отсутствует рабочий компонент WPO: "+marker)
    for bad in ("WPO_LOGIN_LANGUAGE_THEME_V1_BEGIN",
                "WPO_NAV_NATIVE_RECOVERY_V2_BEGIN", "WPO_SAFE_C333E00_BUTTONS_BEGIN"):
        if bad in source:
            raise RuntimeError("Обнаружена старая неисправная правка "+bad+"; сначала восстановите рабочую WPO.")


def apply_login(source):
    if LOGIN_MARK in source:
        return source, "Автологин уже отключён"
    only_one(source, "def login_ui(path):")
    start=source.index("def login_ui(path):")
    end=source.index("\n\ndef hidden(csrf",start)
    login=source[start:end]
    old='<button class="primary login-submit" id="loginSubmit"><b>Войти в панель</b>'
    new='<button type="submit" class="primary login-submit" id="loginSubmit"><b>Вход</b>'
    if login.count(old)!=1 or 'autoTimer=null' not in login or 'queueAutoLogin' not in login:
        raise RuntimeError("Не найден исходный автологин c333e00.")
    login=login.replace(old,new,1)
    needle="<script>(()=>{{const form=document.getElementById('loginForm')"
    if login.count(needle)!=1:
        raise RuntimeError("Скрипт автологина не совпадает с c333e00.")
    a=login.index(needle); b=login.index("</script>",a)+len("</script>")
    safe_js = """<script>
(()=>{
 'use strict';
 const form=document.getElementById('loginForm');
 const password=document.getElementById('loginPassword');
 const toggle=document.getElementById('loginPasswordToggle');
 const submit=document.getElementById('loginSubmit');
 if(!form||!password||!toggle||!submit)return;
 toggle.addEventListener('click',()=>{
   const visible=password.type==='text';
   password.type=visible?'password':'text';
   toggle.textContent=visible?'Показать':'Скрыть';
   toggle.setAttribute('aria-pressed',String(!visible));
   password.focus({preventScroll:true});
 });
 // Browser-native POST only after a click on Вход or Enter.
 form.addEventListener('submit',()=>{
   const label=submit.querySelector('b');
   if(label)label.textContent='Вход…';
 });
})();
</script>"""
    # The HTML is inside a Python f-string. Double JS braces without altering {esc(path)}.
    login=login[:a]+safe_js.replace("{","{{").replace("}","}}")+login[b:]
    if any(s in login for s in ("autoTimer=", "queueAutoLogin", "requestSubmit(", "startWatch()")):
        raise RuntimeError("Автоматический вход не удалён.")
    if 'method="post" action="{esc(path)}/login"' not in login:
        raise RuntimeError("POST-маршрут формы не найден.")
    updated=source[:start]+login+source[end:]
    updated+="\n"+LOGIN_MARK+"\nCSS += "+repr(LOGIN_CSS)+"\n"
    updated+="ASSET_REV = hashlib.sha256((CSS + COMMON_JS + globals().get('WPO_SELECT_POPOVER_V2_JS','')).encode('utf-8')).hexdigest()[:12]\n"
    return updated, "Автологин отключён, Вход по нажатию и Enter"


def fetch_dictionary():
    raw=urlopen(Request(I18N_URL,headers={"User-Agent":"WPO-Safe-UI"}),timeout=25).read()
    blob=hashlib.sha1(b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw).hexdigest()
    if blob!=I18N_BLOB:
        raise RuntimeError("Словарь перевода не прошёл контроль целостности.")
    dictionary=json.loads(raw.decode("utf-8"))
    if not isinstance(dictionary,dict) or len(dictionary)<600:
        raise RuntimeError("Словарь перевода неполный.")
    return dictionary


def apply_buttons(source):
    if LOGIN_MARK not in source:
        raise RuntimeError("Сначала отключите автологин командой --apply-login.")
    if BUTTON_MARK in source:
        return source, "Язык и тема уже установлены"
    only_one(source,OLD_THEME)
    if ("document.querySelectorAll('[data-theme-toggle] span')" not in source or
        "b.querySelector('span').textContent=" not in source):
        raise RuntimeError("Обнаружен неожиданный обработчик темы, изменений нет.")
    dictionary=fetch_dictionary()
    # Encode data safely so no translation can terminate a <script> element.
    dictionary_json=json.dumps(dictionary,ensure_ascii=False,separators=(",",":")).replace("<","\\u003c")
    javascript=LANGUAGE_JS.replace("__DICTIONARY__",dictionary_json)
    if "MutationObserver(" in javascript or "stopImmediatePropagation" in javascript:
        raise RuntimeError("Небезопасный JavaScript в новом переключателе.")
    updated=source.replace(OLD_THEME,NEW_THEME,1)
    updated+="\n"+BUTTON_MARK+"\nCSS += "+repr(BUTTON_CSS)+"\n"
    updated+="WPO_C333_I18N_JS = "+repr(javascript)+"\n"
    updated+="_WPO_C333_LOGIN_BASE = login_ui\n"
    updated+="def login_ui(path):\n    return _WPO_C333_LOGIN_BASE(path).replace('</body></html>',WPO_C333_I18N_JS+'</body></html>',1)\n"
    updated+="_WPO_C333_PAGE_BASE = page_layout\n"
    updated+="def page_layout(*args, **kwargs):\n    return _WPO_C333_PAGE_BASE(*args, **kwargs).replace('</body></html>',WPO_C333_I18N_JS+'</body></html>',1)\n"
    updated+="ASSET_REV = hashlib.sha256((CSS + COMMON_JS + globals().get('WPO_SELECT_POPOVER_V2_JS','') + WPO_C333_I18N_JS).encode('utf-8')).hexdigest()[:12]\n"
    return updated, "RU/EN и солнце/луна добавлены без перехвата навигации"


def verify_change(original,updated,mode):
    ast.parse(updated,filename=str(TARGET))
    compile(updated,str(TARGET),"exec")
    if (updated.count("# WPO_SELECT_POPOVER_V2_BEGIN")!=1 or
        updated.count("def routing_ui(")!=original.count("def routing_ui(")):
        raise RuntimeError("Рабочие выпадающие списки или маршрутизация изменены.")
    if mode.endswith("buttons") and (
        "WPO_C333_I18N_JS" not in updated or
        "data-wpo-lang=" not in updated or
        original.count("wppNavigationTimer")!=updated.count("wppNavigationTimer")):
        raise RuntimeError("Проверка безопасной навигации не пройдена.")


def service_ok():
    if subprocess.run(["systemctl","is-active","--quiet",SERVICE]).returncode:
        return False
    try:
        from urllib.error import HTTPError
        try:
            reply=urlopen("http://127.0.0.1:8090/",timeout=2)
            code=reply.status
        except HTTPError as exc:
            code=exc.code
        return 200<=code<500
    except Exception:
        return False


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("mode",choices=["--check-login","--apply-login","--check-buttons","--apply-buttons"])
    # Argparse does not treat --prefixed strings as positional; parse directly below.
    mode=sys.argv[1] if len(sys.argv)==2 else ""
    if mode not in {"--check-login","--apply-login","--check-buttons","--apply-buttons"}:
        raise SystemExit("Использование: --check-login | --apply-login | --check-buttons | --apply-buttons")
    if mode.startswith("--apply") and os.geteuid()!=0:
        raise SystemExit("Используйте sudo для применения.")
    if not TARGET.is_file() or TARGET.is_symlink() or not (APP/"panel.py").is_file():
        raise SystemExit("Установленная WPO не найдена, изменений нет.")
    source=TARGET.read_text(encoding="utf-8")
    verify_original(source)
    updated,message=apply_login(source) if mode.endswith("login") else apply_buttons(source)
    verify_change(source,updated,mode)
    if updated==source:
        print("✓ "+message)
        return
    if mode.startswith("--check"):
        print("✓ Совместимость подтверждена: "+message)
        print("✓ Проверка не меняла файлов и не перезапускала службу.")
        return
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=Path("/var/backups/web-panel-online")/("safe-ui-"+stamp+"-"+str(os.getpid()))
    backup.mkdir(parents=True,exist_ok=False,mode=0o700)
    shutil.copy2(TARGET,backup/"wpp_ui.py")
    fd,temp=tempfile.mkstemp(prefix=".wpp-safe-ui-",suffix=".py",dir=APP)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            out.write(updated)
        original_mode=stat.S_IMODE(TARGET.stat().st_mode)
        os.chmod(temp,original_mode)
        os.chown(temp,TARGET.stat().st_uid,TARGET.stat().st_gid)
        os.replace(temp,TARGET)
        subprocess.run(["systemctl","restart",SERVICE],check=True)
        for _ in range(15):
            if service_ok():
                print("✓ "+message)
                print("✓ Служба WPO отвечает. Копия: "+str(backup/"wpp_ui.py"))
                return
            time.sleep(1)
        raise RuntimeError("HTTP-проверка WPO не пройдена.")
    except Exception:
        shutil.copy2(backup/"wpp_ui.py",TARGET)
        subprocess.run(["systemctl","restart",SERVICE],check=False)
        print("✖ Ошибка. Исходный интерфейс возвращён из "+str(backup),file=sys.stderr)
        raise
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


if __name__=="__main__":
    main()
