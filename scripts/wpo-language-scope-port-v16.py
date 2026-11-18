#!/usr/bin/env python3
"""WPO v16: localised AWG placeholder and REALITY scope, without UI relayout.

Safe incremental patch for the existing V15 WPO UI. All edits are confined to
one static placeholder and the existing RU/EN client-side translator. Does not
touch node-status polling, connections, server config, user data, or GitHub.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

UI = Path('/opt/tproxy-panel/wpp_ui.py')
SERVICE = 'tproxy-panel.service'
BACKUPS = Path('/var/backups/web-panel-online')
MARKER = '# WPO_LANGUAGE_SCOPE_PORT_V16'

# This fragment renders the AWG 2.0 and AWG 3.1 rows from one code location.
# Preserve the existing container and its CSS classes. Remove the <small> line.
PORT_OLD = ('<span class="connection-port-empty">Будет назначен'
            '<small>при создании клиента</small></span>')
PORT_NEW = '<span class="connection-port-empty">Свой порт</span>'

# Runs only on document ready, language toggle, or a deliberate click/dialog.
# No MutationObserver, interval, page reload, or nested HTML element is added.
JS_SCOPE = r'''function wpoV16Scope(){
 document.querySelectorAll('input[readonly]').forEach(input=>{
  const initial=input.getAttribute('value')||input.dataset.wpoV16ScopeOriginal||input.value;
  const match=initial.match(/^Вся сеть\s*[·–-]\s*основная и\s*(\d+)\s+дополнительных нод(?:ы|а)?$/u);
  if(!match)return;
  const count=Number(match[1]);
  if(!Number.isSafeInteger(count))return;
  const tail=count%10===1&&count%100!==11?'дополнительная нода':
   count%10>=2&&count%10<=4&&(count%100<12||count%100>14)?'дополнительных ноды':'дополнительных нод';
  const ru='Вся сеть · основная и '+count+' '+tail;
  const en='Entire network · main and '+count+' additional '+(count===1?'node':'nodes');
  input.dataset.wpoV16ScopeOriginal=initial;
  const target=lang==='en'?en:ru;
  if(input.value!==target)input.value=target;
 });
}
'''
JS_ADD_MAP = "ruToEn['Свой порт']='Custom port';\n"


def change(source):
    if MARKER in source:
        print('✓ V16 уже установлен — повторно ничего не меняем')
        return source, False
    requirements = ('# WPO_LANGUAGE_SAFE_V15', '# WPO_NODES_EN_QUIET_V13',
                    'setInterval(refresh,1000)',
                    'querySelector("[data-node-edit]")?.dataset.nodeName')
    for marker in requirements:
        if marker not in source:
            raise RuntimeError('Версия WPO отличается от проверенной. Нет: '+marker)
    if '# WPO_NODES_STABLE_EN_V14' in source:
        raise RuntimeError('В установленной WPO остался повреждённый V14. Сначала откати его.')
    if source.count(PORT_OLD) != 1:
        raise RuntimeError('Не найден исходный текст AWG PORT. Изменений нет.')
    updated = source.replace(PORT_OLD, PORT_NEW, 1)
    # V15 defines the final JS string, so modifications below are appended
    # as a wrapper, not edits to the original translator implementation.
    addon = r'''
# WPO_LANGUAGE_SCOPE_PORT_V16
# Keep one text node per label, without injecting more DOM elements or CSS.
if WPO_C333_I18N_JS.count('const originalText=new WeakMap()')!=1:
    raise RuntimeError('WPO v16: i18n data anchor missing')
WPO_C333_I18N_JS=WPO_C333_I18N_JS.replace(
    'const originalText=new WeakMap()',
    ''' + repr(JS_ADD_MAP) + r'''+ 'const originalText=new WeakMap()',1)
if WPO_C333_I18N_JS.count('function controls(){')!=1:
    raise RuntimeError('WPO v16: language switch anchor missing')
WPO_C333_I18N_JS=WPO_C333_I18N_JS.replace(
    'function controls(){',
    ''' + repr(JS_SCOPE) + r'''+ 'function controls(){\n wpoV16Scope();',1)
# REALITY scope may be populated when its dialog opens; refresh once per click.
_anchor=' // Dialogs can be pre-rendered and populated when opened.'
if WPO_C333_I18N_JS.count(_anchor)!=1:
    raise RuntimeError('WPO v16: dialog anchor missing')
WPO_C333_I18N_JS=WPO_C333_I18N_JS.replace(
    _anchor,' requestAnimationFrame(wpoV16Scope);\n'+_anchor,1)
'''
    updated += '\n'+addon
    compile(updated, str(UI), 'exec')
    print('✓ AWG 2.0 и 3.1: «Свой порт» / «Custom port»')
    print('✓ REALITY: «Вся сеть · основная и N нод» (склонение по числу)')
    print('✓ REALITY EN: «Entire network · main and N additional nodes»')
    print('✓ Число нод берётся из текущих данных панели, 1/2/3/4/5+ обработаны')
    print('✓ Двойной текст, размеры таблицы и статусный опрос не изменяются')
    return updated, True


def running():
    return subprocess.run(['systemctl','is-active','--quiet',SERVICE],
                          check=False).returncode==0


def apply(source):
    updated, required = change(source)
    if not required:
        return
    if not running():
        raise RuntimeError('Служба WPO не была запущена до обновления. Изменений нет.')
    BACKUPS.mkdir(parents=True,exist_ok=True)
    backup = BACKUPS / ('wpp_ui-before-v16-'+
                        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.py')
    if backup.exists():
        raise RuntimeError('Имя резервной копии уже существует. Изменений нет.')
    shutil.copy2(UI,backup)
    os.chmod(backup,0o600)
    print('✓ Резервная копия:',backup)
    tmp = None
    applied = False
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=UI.parent,
                                         prefix='.wpo-v16-',suffix='.py',delete=False) as f:
            f.write(updated)
            tmp=Path(f.name)
        original=UI.stat()
        os.chmod(tmp,stat.S_IMODE(original.st_mode))
        os.chown(tmp,original.st_uid,original.st_gid)
        os.replace(tmp,UI)
        applied=True
        subprocess.run(['systemctl','restart',SERVICE],check=True,timeout=45)
        for _ in range(15):
            if running():
                print('✓ Служба WPO запущена, V16 применён')
                print('✓ Ноды, пользователи, подключения и настройки не менялись')
                return
            time.sleep(1)
        raise RuntimeError('Служба WPO не запустилась после исправления')
    except Exception:
        if applied:
            shutil.copy2(backup,UI)
            subprocess.run(['systemctl','restart',SERVICE],check=False)
            print('! Из-за ошибки предыдущий файл WPO восстановлен')
        raise
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description='WPO v16: RU/EN Scope and Custom port')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true',help='Проверить без изменений')
    group.add_argument('--apply',action='store_true',help='Создать резервную копию и применить')
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise RuntimeError('Нужен sudo')
    if not UI.is_file() or UI.is_symlink():
        raise RuntimeError('Файл установленной WPO не найден')
    source=UI.read_text(encoding='utf-8')
    if args.check:
        change(source)
        print('✓ Проверка завершена, файлы не менялись')
    else:
        apply(source)


if __name__=='__main__':
    try:
        main()
    except (RuntimeError,OSError,subprocess.CalledProcessError) as error:
        print('ОШИБКА:',error,file=sys.stderr)
        sys.exit(1)
