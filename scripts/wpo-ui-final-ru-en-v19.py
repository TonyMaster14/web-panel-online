#!/usr/bin/env python3
"""WPO V19: final Node menu and VLESS REALITY display labels.

Only visible UI labels change; saved settings, connections and polling stay intact.
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
BACKUP_DIR = Path('/var/backups/web-panel-online')
MARKER = '# WPO_NODE_SELECT_REALITY_LABELS_V19'
ADDON = "\n# WPO_NODE_SELECT_REALITY_LABELS_V19\n# Presentation layer only: no persisted names, IDs, options or server settings.\n_WPO_V19_JS = \"\\nconst wpoV19LongReality=/VLESS\\\\s+(?:TCP\\\\s+)?REALITY\\\\s*(?:[·•|/–—-]\\\\s*|\\\\s+)(?:TCP\\\\s+)?Vision\\\\b/giu;\\nfunction wpoV19ShortReality(value){return String(value||'').replace(wpoV19LongReality,'VLESS REALITY');}\\nfunction wpoV19Choice(value){\\n const text=wpoV19ShortReality(value),key=text.trim();\\n if(key==='Основная нода'||key==='Main node')return lang==='en'?'Main node':'Основная нода';\\n if(typeof wpoV18LocalizedName==='function'){\\n  const localized=wpoV18LocalizedName(key);\\n  if(localized)return text.replace(key,localized);\\n }\\n return text;\\n}\\nfunction wpoV19ConnectionName(){\\n const form=document.getElementById('connectionForm'),field=form?.querySelector('input[name=\\\"name\\\"]');\\n if(!field)return;\\n const id=form.querySelector('input[name=\\\"id\\\"]')?.value||'';\\n if(field.dataset.wpoV19ConnectionId!==id){\\n  field.dataset.wpoV19ConnectionId=id;delete field.dataset.wpoV19Original;field.dataset.wpoV19Dirty='0';\\n }\\n if(field.dataset.wpoV19Dirty==='1')return;\\n const shown=wpoV19ShortReality(field.value);\\n if(shown!==field.value){field.dataset.wpoV19Original=field.value;field.value=shown;}\\n}\\nfunction wpoV19Update(){\\n if(!document.body)return;\\n const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);\\n let node;\\n while((node=walker.nextNode())){\\n  const parent=node.parentElement;\\n  if(!parent||parent.closest('script,style,noscript,pre,code,svg,select,textarea,[contenteditable],.wpo-utility-switches'))continue;\\n  if(!node.nodeValue||!node.nodeValue.includes('VLESS'))continue;\\n  const updated=wpoV19ShortReality(node.nodeValue);\\n  if(updated!==node.nodeValue)node.nodeValue=updated;\\n }\\n // Visual copies only. Never rewrite underlying SELECT options or their values.\\n for(const el of document.querySelectorAll('.wpo-popup-select-value,.wpo-popup-select-option>span:first-child')){\\n  const updated=wpoV19Choice(el.textContent);\\n  if(updated!==el.textContent)el.textContent=updated;\\n }\\n wpoV19ConnectionName();\\n}\\nfunction wpoV19Bind(){\\n if(document.documentElement.dataset.wpoV19Ready==='1')return;\\n document.documentElement.dataset.wpoV19Ready='1';\\n const f=document.getElementById('connectionForm'),name=f?.querySelector('input[name=\\\"name\\\"]');\\n if(f&&name){\\n  name.addEventListener('input',()=>{name.dataset.wpoV19Dirty='1';});\\n  f.addEventListener('formdata',event=>{\\n   if(name.dataset.wpoV19Dirty!=='1'&&name.dataset.wpoV19Original)\\n    event.formData.set('name',name.dataset.wpoV19Original);\\n  });\\n }\\n let scheduled=false;\\n const schedule=()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;wpoV19Update();});};\\n document.addEventListener('click',schedule);\\n document.addEventListener('change',schedule);\\n document.addEventListener('keydown',event=>{\\n  if(['Enter',' ','ArrowDown','ArrowUp','Home','End'].includes(event.key))schedule();\\n });\\n}\\nfunction wpoV19Sync(){wpoV19Bind();wpoV19Update();}\\n\"\nif WPO_C333_I18N_JS.count('function controls(){') != 1:\n    raise RuntimeError('WPO V19: missing language controls')\nWPO_C333_I18N_JS = WPO_C333_I18N_JS.replace(\n    'function controls(){',\n    _WPO_V19_JS+'\\nfunction controls(){\\n wpoV19Sync();',1)\n"

def patch(source):
    if MARKER in source:
        print('✓ V19 уже установлен — изменений нет')
        return source, False
    for needed in ('# WPO_ALL_NODE_COUNTRY_NAMES_V18', '# WPO_LANGUAGE_SAFE_V15', '# WPO_LANGUAGE_SCOPE_PORT_V16',
                   '# WPO_NODES_EN_QUIET_V13',
                   'querySelector("[data-node-edit]")?.dataset.nodeName'):
        if needed not in source:
            raise RuntimeError('Неизвестная версия WPO: нет ' + needed)
    if '# WPO_NODES_STABLE_EN_V14' in source:
        raise RuntimeError('Сначала откати V14')
    if source.count('id="wpoEditNodeForm"') != 1 or source.count('data-node-name=') != 1:
        raise RuntimeError('Неизвестная форма нод; изменений нет')
    if 'setInterval(refresh,1000)' not in source:
        raise RuntimeError('Неизвестный код обновления нод; изменений нет')
    result = source + '\n' + ADDON
    compile(result, str(UI), 'exec')
    print('✓ Главное меню нод: Основная нода / Main node')
    print('✓ Списки дополнительных нод: страны на RU / EN')
    print('✓ Название в интерфейсе: VLESS REALITY без TCP Vision')
    print('✓ Карточки, формы, списки и окна без дублированных надписей')
    print('✓ Сохранённые имена, ID, настройки и опрос нод не меняются')
    return result, True


def running():
    return subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE],
                          check=False).returncode == 0


def apply(source):
    updated, changed = patch(source)
    if not changed:
        return
    if not running():
        raise RuntimeError('Служба WPO до установки не активна. Изменений нет.')
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / ('wpp_ui-before-v19-' +
                          datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.py')
    if backup.exists():
        raise RuntimeError('Резервная копия с таким именем уже существует')
    shutil.copy2(UI, backup)
    os.chmod(backup, 0o600)
    print('✓ Резервная копия:', backup)
    temp = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=UI.parent,
                                         prefix='.wpo-v19-', suffix='.py',
                                         delete=False) as stream:
            stream.write(updated)
            temp = Path(stream.name)
        old_stat = UI.stat()
        os.chmod(temp, stat.S_IMODE(old_stat.st_mode))
        os.chown(temp, old_stat.st_uid, old_stat.st_gid)
        os.replace(temp, UI)
        replaced = True
        subprocess.run(['systemctl', 'restart', SERVICE], check=True, timeout=45)
        for _ in range(15):
            if running():
                print('✓ Служба WPO работает; V19 установлен')
                return
            time.sleep(1)
        raise RuntimeError('Служба WPO не активна после установки')
    except Exception:
        if replaced:
            shutil.copy2(backup, UI)
            subprocess.run(['systemctl', 'restart', SERVICE], check=False)
            print('! Прежняя версия восстановлена из резервной копии')
        raise
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='WPO V19: Node menu and REALITY display labels')
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument('--check', action='store_true', help='Проверка без изменений')
    option.add_argument('--apply', action='store_true', help='Резервная копия и обновление')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Необходимо sudo')
    if not UI.is_file() or UI.is_symlink():
        raise RuntimeError('Не найден обычный файл установленной WPO')
    source = UI.read_text(encoding='utf-8')
    if args.check:
        patch(source)
        print('✓ Проверка успешна; файл WPO не изменён')
    else:
        apply(source)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('ОШИБКА:', error, file=sys.stderr)
        sys.exit(1)
