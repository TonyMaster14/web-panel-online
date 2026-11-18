#!/usr/bin/env python3
"""WPO V26: on first focus put text insertion caret at end of editable values.

Works across pages and dynamically added dialogs. Does not change field values,
saving logic, disabled/read-only inputs, or selection on subsequent clicks.
"""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import argparse

UI=Path('/opt/tproxy-panel/wpp_ui.py')
SERVICE='tproxy-panel.service'
BACKUPS=Path('/var/backups/web-panel-online')
MARKER='# WPO_EDIT_CARET_TO_END_V26'
ANCHOR="window.addEventListener('pageshow',wppFinishNavigation);"

ADDON = r'''
# WPO_EDIT_CARET_TO_END_V26
# COMMON_JS is injected into the shared app.js (including dynamic dialogs).
_WPO_CARET_TO_END_JS_V26 = r"""
;(()=>{
  'use strict';
  const fieldTypes=new Set(['text','search','tel','url','email','password','number']);
  function editable(el){
    if(!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement))return false;
    if(el.disabled||el.readOnly)return false;
    if(el instanceof HTMLInputElement && !fieldTypes.has(el.type))return false;
    return true;
  }
  document.addEventListener('focusin',event=>{
    const field=event.target;
    if(!editable(field))return;
    // The browser sets the click insertion point after the focus event.
    // A frame callback runs after that. Later clicks in the same focused
    // field are unaffected, so editing in the middle remains possible.
    requestAnimationFrame(()=>{
      if(document.activeElement!==field||!field.isConnected||!editable(field))return;
      try{
        const end=field.value.length;
        field.setSelectionRange(end,end);
      }catch(_e){
        // Native input[type=number] (and some email inputs) do not support
        // selectionRange; never alter their type or number validation.
      }
    });
  },true);
})();
"""
if COMMON_JS.count("window.addEventListener('pageshow',wppFinishNavigation);") != 1:
    raise RuntimeError('WPO V26: shared JS changed; no modifications')
COMMON_JS = COMMON_JS.replace(
    "window.addEventListener('pageshow',wppFinishNavigation);",
    "window.addEventListener('pageshow',wppFinishNavigation);\n" + _WPO_CARET_TO_END_JS_V26,
    1
)
ASSET_REV = hashlib.sha256(
    (CSS + COMMON_JS + globals().get("WPO_SELECT_POPOVER_V2_JS", "")).encode("utf-8")
).hexdigest()[:12]
'''

def prepare(source):
    if MARKER in source:
        print('✓ V26 уже установлен, изменений нет')
        return source,False
    if source.count(ANCHOR)!=1 or 'COMMON_JS = """<script>' not in source:
        raise RuntimeError('Общий скрипт WPO не найден в ожидаемой версии; изменений нет')
    if source.count('ASSET_REV = hashlib.sha256(') < 1:
        raise RuntimeError('Кеширование ресурсов WPO не найдено; изменений нет')
    updated=source.rstrip()+'\n\n'+ADDON
    compile(updated,str(UI),'exec')
    print('✓ В редактируемых текстовых полях курсор при первом фокусе ставится в конец')
    print('✓ Неактивные поля, значения, сохранение и VLESS REALITY не затрагиваются')
    return updated,True

def active():
    return subprocess.run(['systemctl','is-active','--quiet',SERVICE],check=False).returncode==0

def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--check',action='store_true')
    g.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if os.geteuid()!=0: raise RuntimeError('Требуется sudo')
    if not UI.is_file() or UI.is_symlink(): raise RuntimeError('Основной файл WPO не найден')
    target,modified=prepare(UI.read_text(encoding='utf-8'))
    if a.check or not modified: return
    if not active(): raise RuntimeError('WPO не работала до установки; изменений нет')
    BACKUPS.mkdir(parents=True,exist_ok=True)
    backup=BACKUPS/('wpp-ui-before-v26-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.py')
    if backup.exists(): raise RuntimeError('Резервная копия с таким именем уже существует')
    shutil.copy2(UI,backup);os.chmod(backup,0o600)
    print('✓ Резервная копия:',backup)
    tmp=None;replaced=False
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=UI.parent,
                                         prefix='.wpo-v26-',suffix='.py',delete=False) as out:
            out.write(target);tmp=Path(out.name)
        old=UI.stat()
        os.chown(tmp,old.st_uid,old.st_gid)
        os.chmod(tmp,stat.S_IMODE(old.st_mode))
        os.replace(tmp,UI);replaced=True
        subprocess.run(['systemctl','restart',SERVICE],check=True,timeout=45)
        for _ in range(15):
            if active():
                print('✓ V26 установлен. WPO работает.')
                return
            time.sleep(1)
        raise RuntimeError('WPO не запустилась')
    except Exception:
        if replaced:
            shutil.copy2(backup,UI)
            subprocess.run(['systemctl','restart',SERVICE],check=False)
            print('! Прежний файл восстановлен')
        raise
    finally:
        if tmp: tmp.unlink(missing_ok=True)

if __name__=='__main__':
    try: main()
    except (OSError,RuntimeError,subprocess.CalledProcessError) as error:
        print('ОШИБКА:',error,file=sys.stderr);sys.exit(1)
