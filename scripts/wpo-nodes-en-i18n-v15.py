#!/usr/bin/env python3
"""WPO V15: carefully fix remaining EN text without modifying HTML or CSS.

Only for an already-installed WPO controller matching the user's tested version.
Updates one status-text assignment and extends the existing I18N translation
function. Does not alter node registry, names, templates, connections, ports,
users, transport config, CSS layout, or the 1-second polling interval.

Usage: sudo python3 wpo-nodes-en-i18n-v15.py --check|--apply
"""
import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path

UI = Path('/opt/tproxy-panel/wpp_ui.py')
SERVICE = 'tproxy-panel.service'
BACKUP_DIR = Path('/var/backups/web-panel-online')
MARKER = '# WPO_NODES_EN_TRANSLATION_V15'
NAME_OLD = 'querySelector(".wpo-node-label h3")?.textContent.trim()'
NAME_FIXED = 'querySelector("[data-node-edit]")?.dataset.nodeName'
STATUS_OLD = "el.querySelector('b').textContent=state[0]"
STATUS_FIXED = (
    "el.querySelector('b').textContent=\n"
    "document.documentElement.dataset.wpoLanguage==='en'?"
    "({online:'Online',installing:'Installing',registration:'Registration',"
    "offline:'Offline',error:'Error'}[state[1]]||'Offline'):state[0]"
)
I18N_ANCHOR = ' const arrow=key.match(/^([↑↓])\\s*(.+)$/u);'
I18N_FRAGMENT = r''' // Keep the original single text node: no parallel RU/EN spans or CSS.
 const title=key.match(/^(⚙(?:\uFE0F)?)\s*(Управление нодами)$/u);
 if(title&&has(title[2]))return left+title[1]+' '+ruToEn[title[2]]+right;
 // Translate labels and *known* built-in template names only.
 // Custom template names are user data and must remain untouched.
 const template=key.match(/^Шаблон\s*:\s*(.*)$/u);
 if(template){
   const name=template[1].trim();
   return left+'Template: '+(has(name)?ruToEn[name]:name)+right;
 }
'''
# Text replacement is applied at runtime to the existing translator only, and
# the language switch's WeakMap stores the exact original Russian string.
I18N_WRAPPER = r'''
# WPO_NODES_EN_TRANSLATION_V15
_WPO_V15_EN_ANCHOR = __WPO_V15_ANCHOR__
_WPO_V15_EN_FRAGMENT = __WPO_V15_FRAGMENT__
if WPO_C333_I18N_JS.count(_WPO_V15_EN_ANCHOR) != 1:
    raise RuntimeError('WPO V15: unknown translator version')
WPO_C333_I18N_JS = WPO_C333_I18N_JS.replace(
    _WPO_V15_EN_ANCHOR,
    _WPO_V15_EN_FRAGMENT + _WPO_V15_EN_ANCHOR,
    1,
)
'''


def prepare(source):
    if MARKER in source:
        return source, False
    if '# WPO_NODES_STABLE_EN_V14' in source:
        raise ValueError('V14 всё ещё установлен. Сначала верните резервную копию V14.')
    required = ('# WPO_C333_I18N_V8_PRELOAD',
                '# WPO_C333_V9_STABLE_SELECTOR',
                '# WPO_C333_AUDITED_EN_V10',
                '# WPO_NODES_I18N_GUARD_V12',
                '# WPO_NODES_EN_QUIET_V13',
                'setInterval(refresh,1000)')
    for token in required:
        if token not in source:
            raise ValueError('Неизвестная версия установленной WPO: отсутствует '+token)
    if source.count(NAME_OLD) == 1:
        source = source.replace(NAME_OLD,NAME_FIXED,1)
    elif source.count(NAME_FIXED) != 1:
        raise ValueError('Не найдено исправление сравнения имени ноды; изменений нет')
    if source.count(STATUS_OLD) == 1:
        source = source.replace(STATUS_OLD,STATUS_FIXED,1)
    elif source.count(STATUS_FIXED) != 1:
        raise ValueError('Неизвестный обработчик статусов; изменений нет')
    if source.count(I18N_ANCHOR) != 1 or source.count('WPO_C333_I18N_JS = _wpo_v12_rebuild(') != 1:
        raise ValueError('Неизвестный переводчик WPO; изменений нет')
    # This is an appended JS-string wrapper, not a change to the rendered HTML.
    import reprlib
    addon = (I18N_WRAPPER.replace('__WPO_V15_ANCHOR__',repr(I18N_ANCHOR))
                         .replace('__WPO_V15_FRAGMENT__',repr(I18N_FRAGMENT)))
    source += '\n'+addon
    compile(source,str(UI),'exec')
    # It must not append markup, change CSS, or create additional labels.
    if 'wpo-v14-ru' in addon or 'CSS +=' in addon or 'data-wpo-no-translate' in addon:
        raise ValueError('V15 safety: unexpected layout mutation')
    return source,True


def healthy():
    if subprocess.run(['systemctl','is-active','--quiet',SERVICE],check=False).returncode != 0:
        return False
    try:
        c=HTTPConnection('127.0.0.1',8090,timeout=3)
        try:
            c.request('GET','/')
            r=c.getresponse()
            return 200 <= r.status < 500
        finally:
            c.close()
    except OSError:
        return False


def install():
    if not UI.is_file() or UI.is_symlink():
        raise ValueError('WPO отсутствует либо путь является ссылкой')
    current=UI.read_text(encoding='utf-8')
    updated, changed=prepare(current)
    if not changed:
        print('✓ V15 уже установлен. Повторные изменения не нужны.')
        return
    if not healthy():
        raise RuntimeError('Служба WPO не отвечает ДО установки. Ничего не изменено.')
    BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    backup=BACKUP_DIR/('wpp_ui-before-v15-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.py')
    with backup.open('xb') as f:
        f.write(UI.read_bytes())
    shutil.copystat(UI,backup)
    os.chmod(backup,0o600)
    print('✓ Резервная копия:',backup)
    temp=None
    replaced=False
    try:
        with tempfile.NamedTemporaryFile('w',dir=UI.parent,delete=False,
                                         prefix='.wpo-v15-',suffix='.py',encoding='utf8') as f:
            f.write(updated)
            temp=Path(f.name)
        s=UI.stat()
        os.chmod(temp,stat.S_IMODE(s.st_mode))
        os.chown(temp,s.st_uid,s.st_gid)
        os.replace(temp,UI)
        replaced=True
        subprocess.run(['systemctl','restart',SERVICE],timeout=45,check=True)
        for _ in range(15):
            if healthy():
                print('✓ Ноды: сохранено исправление перезагрузок при EN')
                print('✓ Заголовок: Node management (без дублирования)')
                print('✓ Карточки: Template + перевод встроенных шаблонов')
                print('✓ Статусы: Online / Installing / Registration / Offline / Error')
                print('✓ RU/EN: перевод одной строки, без дополнительного HTML и CSS')
                print('✓ PORT и размеры таблицы подключений не изменены')
                print('✓ Служба WPO работает')
                return
            time.sleep(1)
        raise RuntimeError('Служба WPO не отвечает после обновления.')
    except Exception:
        if replaced:
            shutil.copy2(backup,UI)
            subprocess.run(['systemctl','restart',SERVICE],check=False)
            print('! Ошибка: восстановлена прежняя версия интерфейса',file=sys.stderr)
        raise
    finally:
        if temp and temp.exists():
            temp.unlink()


def main():
    parser=argparse.ArgumentParser(description='WPO V15: safe RU/EN translation')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true',help='validate the patch without changing files')
    mode.add_argument('--apply',action='store_true',help='backup, patch, restart and verify')
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError('Запустите с sudo')
    if args.check:
        if not UI.is_file():
            raise ValueError('Не найден /opt/tproxy-panel/wpp_ui.py')
        result, changed=prepare(UI.read_text(encoding='utf-8'))
        print('✓ Проверка V15:', 'готово к установке' if changed else 'уже установлено')
    else:
        install()


if __name__=='__main__':
    try:
        main()
    except (OSError,RuntimeError,ValueError,subprocess.CalledProcessError) as exc:
        print('ОШИБКА:',exc,file=sys.stderr)
        sys.exit(1)
