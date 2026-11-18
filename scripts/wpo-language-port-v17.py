#!/usr/bin/env python3
"""WPO V17: correct AWG port translation without duplicate markup or relayout.

Requires the existing working V15+V16 language patches and preserves stable
Nodes polling, stored names, node settings, client/connection data and CSS.
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
MARKER = '# WPO_AWG_PORT_LANGUAGE_V17'
ANCHOR = 'function controls(){\\n wpoV16Scope();'
INJECTION = r'''function wpoV17Port(){
 // Change only the existing AWG port caption. Never add another DOM element.
 document.querySelectorAll('.connection-port-empty').forEach(el=>{
  const label=lang==='en'?'Custom port':'Свой порт';
  if(el.textContent!==label)el.textContent=label;
 });
}
'''
ADDON = r'''
# WPO_AWG_PORT_LANGUAGE_V17
# The existing language switch calls controls() on initial render and RU/EN
# changes. Force the AWG caption there instead of relying on dictionary lookup.
if WPO_C333_I18N_JS.count('function controls(){\n wpoV16Scope();') != 1:
    raise RuntimeError('WPO V17: V16 language control not found; no changes applied')
WPO_C333_I18N_JS = WPO_C333_I18N_JS.replace(
    'function controls(){\n wpoV16Scope();',
    ''' + repr(INJECTION) + r''' + 'function controls(){\n wpoV16Scope();\n wpoV17Port();',
    1)
'''


def patch(source):
    if MARKER in source:
        print('✓ V17 уже установлен — изменений нет')
        return source, False
    for needed in ('# WPO_LANGUAGE_SAFE_V15', '# WPO_LANGUAGE_SCOPE_PORT_V16',
                   '# WPO_NODES_EN_QUIET_V13',
                   'querySelector("[data-node-edit]")?.dataset.nodeName'):
        if needed not in source:
            raise RuntimeError('Неизвестная установленная версия WPO: нет ' + needed)
    if '# WPO_NODES_STABLE_EN_V14' in source:
        raise RuntimeError('V14 должен быть отменён; ничего не изменено')
    if source.count('<span class="connection-port-empty">Свой порт</span>') != 1:
        raise RuntimeError('Не найден единственный шаблон подписи AWG PORT; изменений нет')
    if source.count(ANCHOR) != 1:
        raise RuntimeError('Не найден переключатель RU/EN из V16; изменений нет')
    result = source + '\n' + ADDON
    compile(result, str(UI), 'exec')
    print('✓ Подключения: «Свой порт» (RU) / «Custom port» (EN)')
    print('✓ Изменяется только текст существующего элемента')
    print('✓ REALITY Scope и перевод настроек нод сохранены')
    print('✓ Обновление статусов нод и исправление перезагрузок сохранены')
    print('✓ Размеры таблицы и карточек не изменены')
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
    backup = BACKUP_DIR / ('wpp_ui-before-v17-' +
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
                                         prefix='.wpo-v17-', suffix='.py',
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
                print('✓ Служба WPO работает; V17 установлен')
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
    parser = argparse.ArgumentParser(description='WPO V17: RU/EN AWG port caption')
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
