#!/usr/bin/env python3
"""WPO V20: readonly Main node field in the primary node REALITY dialog only."""
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
MARKER = '# WPO_PRIMARY_REALITY_READONLY_V20'

ADDON = r'''
# WPO_PRIMARY_REALITY_READONLY_V20
# Only the appearance of the main-node selector changes. Keep node_id=local.
_WPO_PRIMARY_REALITY_V20_JS = r"""
function wpoPrimaryRealityReadonlyV20(){
 const d=document.getElementById('wpoRealityDialog');
 const f=document.getElementById('wpoRealityForm');
 const select=f?.querySelector('select[name="node_id"]');
 if(!d||!select||!document.querySelector('.wpo-nodes-page'))return;
 if(typeof d.wpoV20Update==='function'){d.wpoV20Update();return;}
 const label=select.closest('label');
 if(!label)return;
 const readonly=document.createElement('input');
 readonly.type='text';
 readonly.readOnly=true;
 readonly.tabIndex=-1;
 readonly.setAttribute('aria-readonly','true');
 readonly.style.display='none';
 label.append(readonly);
 const update=()=>{
  const main=d.open&&select.value==='local';
  const shell=select.closest('.wpo-popup-select-shell');
  select.style.display=main?'none':'';
  if(shell)shell.style.display=main?'none':'';
  readonly.style.display=main?'block':'none';
  readonly.value=lang==='en'?'Main node':'Основная нода';
 };
 d.wpoV20Update=update;
 new MutationObserver(update).observe(d,{attributes:true,attributeFilter:['open']});
 select.addEventListener('change',update);
 document.addEventListener('click',event=>{
  if(event.target?.closest?.('[data-reality-open]'))requestAnimationFrame(update);
 });
 update();
}
"""
if WPO_C333_I18N_JS.count('function controls(){') != 1:
    raise RuntimeError('V20: language controller changed; no modifications')
WPO_C333_I18N_JS = WPO_C333_I18N_JS.replace(
    'function controls(){',
    _WPO_PRIMARY_REALITY_V20_JS +
    '\nfunction controls(){\n wpoPrimaryRealityReadonlyV20();', 1
)
'''

def prepare(source):
    if MARKER in source:
        print('✓ V20 уже установлен')
        return source, False
    needed = (
        '# WPO_C333_STABLE_DYNAMIC_I18N_V11',
        '# WPO_ALL_NODE_COUNTRY_NAMES_V18',
        '# WPO_NODE_SELECT_REALITY_LABELS_V19',
        'setInterval(refresh,1000)',
    )
    missing = [v for v in needed if v not in source]
    if missing:
        raise RuntimeError('Неизвестная версия WPO: ' + ', '.join(missing))
    if '# WPO_NODES_STABLE_EN_V14' in source:
        raise RuntimeError('Обнаружена несовместимая V14; изменений нет')
    updated = source.rstrip() + '\n\n' + ADDON
    compile(updated, str(UI), 'exec')
    print('✓ Основная нода: серое поле без списка и стрелки')
    print('✓ EN: Main node / RU: Основная нода')
    print('✓ Данные нод и VLESS REALITY не изменяются')
    return updated, True

def running():
    return subprocess.run(['systemctl','is-active','--quiet',SERVICE],check=False).returncode==0

def main():
    parser=argparse.ArgumentParser()
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check',action='store_true')
    modes.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0: raise RuntimeError('Запускайте через sudo')
    if not UI.is_file() or UI.is_symlink():
        raise RuntimeError('Файл WPO не найден')
    updated,changed=prepare(UI.read_text(encoding='utf-8'))
    if args.check or not changed:
        print('✓ Проверка пройдена; без изменений')
        return
    if not running(): raise RuntimeError('Служба WPO не работает, ничего не меняем')
    BACKUPS.mkdir(parents=True,exist_ok=True)
    backup=BACKUPS/('wpp-ui-before-v20-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.py')
    if backup.exists(): raise RuntimeError('Конфликт резервной копии')
    shutil.copy2(UI,backup)
    os.chmod(backup,0o600)
    print('✓ Резервная копия:',backup)
    tmp=None
    replaced=False
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=UI.parent,prefix='.wpo-v20-',suffix='.py',delete=False) as out:
            out.write(updated)
            tmp=Path(out.name)
        old=UI.stat()
        os.chown(tmp,old.st_uid,old.st_gid)
        os.chmod(tmp,stat.S_IMODE(old.st_mode))
        os.replace(tmp,UI)
        replaced=True
        subprocess.run(['systemctl','restart',SERVICE],check=True,timeout=45)
        for _ in range(15):
            if running():
                print('✓ WPO работает. V20 установлен')
                return
            time.sleep(1)
        raise RuntimeError('WPO не запустилась')
    except Exception:
        if replaced:
            shutil.copy2(backup,UI)
            subprocess.run(['systemctl','restart',SERVICE],check=False)
            print('! Восстановлена предыдущая версия')
        raise
    finally:
        if tmp is not None: tmp.unlink(missing_ok=True)

if __name__=='__main__':
    try: main()
    except (OSError,RuntimeError,subprocess.CalledProcessError) as error:
        print('ОШИБКА:',error,file=sys.stderr)
        sys.exit(1)
