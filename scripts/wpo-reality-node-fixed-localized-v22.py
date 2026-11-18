#!/usr/bin/env python3
"""WPO V22: show a fixed, localized read-only node field in each node's REALITY dialog.

UI-only patch. Preserves actual node_id, selection, configuration and the VLESS REALITY title.
Requires V20 and V21, and does not change the connections editor.
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
MARKER = '# WPO_REALITY_NODE_FIXED_LOCALIZED_V22'

OLD = """  const main=d.open&&select.value==='local';
  const shell=select.closest('.wpo-popup-select-shell');
  select.style.display=main?'none':'';
  if(shell)shell.style.display=main?'none':'';
  readonly.style.display=main?'block':'none';
  readonly.value=lang==='en'?'Main node':'Основная нода';"""

NEW = """  const showing=d.open;
  const shell=select.closest('.wpo-popup-select-shell');
  select.style.display=showing?'none':'';
  if(shell)shell.style.display=showing?'none':'';
  readonly.style.display=showing?'block':'none';
  const isPrimary=select.value==='local';
  const original=isPrimary?'Основная нода':(select.selectedOptions?.[0]?.textContent?.trim()||select.value||'');
  const localized=typeof wpoV18LocalizedName==='function'?wpoV18LocalizedName(original):null;
  readonly.value=isPrimary?(lang==='en'?'Main node':'Основная нода'):(localized||original);"""


def patch(source):
    if MARKER in source:
        print('✓ V22 уже установлен — изменений нет')
        return source, False
    for expected in ('# WPO_PRIMARY_REALITY_READONLY_V20',
                     '# WPO_PRIMARY_REALITY_GREY_V21',
                     '# WPO_ALL_NODE_COUNTRY_NAMES_V18'):
        if expected not in source:
            raise RuntimeError('Ожидаемая версия WPO не найдена: ' + expected)
    if source.count(OLD) != 1:
        raise RuntimeError('Неизвестная версия редактора ноды — изменений нет')
    updated = source.replace(OLD, NEW, 1).rstrip() + '\n\n' + MARKER + '\n'
    compile(updated, str(UI), 'exec')
    print('✓ В настройках основной и дополнительных нод вместо выбора показано серое неизменяемое поле')
    print('✓ RU/EN: Main node/Основная нода; Sweden/Швеция и другие страны')
    print('✓ Работает с нодами, добавленными позднее')
    print('✓ VLESS REALITY, node_id и сохранённые конфигурации не изменены')
    return updated, True


def service_active():
    return subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE],
                          check=False).returncode == 0


def main():
    parser = argparse.ArgumentParser(description='WPO V22: fixed localized node field')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true', help='Проверить, ничего не меняя')
    modes.add_argument('--apply', action='store_true', help='Установить с резервной копией')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Запускайте через sudo')
    if not UI.is_file() or UI.is_symlink():
        raise RuntimeError('Установленная WPO не найдена')
    updated, changed = patch(UI.read_text(encoding='utf-8'))
    if args.check or not changed:
        return
    if not service_active():
        raise RuntimeError('Служба WPO не работает до обновления; изменений нет')
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / ('wpp-ui-before-v22-' +
                           datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.py')
    if backup.exists():
        raise RuntimeError('Резервная копия уже существует')
    shutil.copy2(UI, backup)
    os.chmod(backup, 0o600)
    print('✓ Резервная копия:', backup)
    temp = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=UI.parent,
                                         prefix='.wpo-v22-', suffix='.py',
                                         delete=False) as stream:
            stream.write(updated)
            temp = Path(stream.name)
        old_stat = UI.stat()
        os.chown(temp, old_stat.st_uid, old_stat.st_gid)
        os.chmod(temp, stat.S_IMODE(old_stat.st_mode))
        os.replace(temp, UI)
        replaced = True
        subprocess.run(['systemctl', 'restart', SERVICE], check=True, timeout=45)
        for _ in range(15):
            if service_active():
                print('✓ WPO активна; V22 установлен')
                return
            time.sleep(1)
        raise RuntimeError('Служба WPO не запустилась')
    except Exception:
        if replaced:
            shutil.copy2(backup, UI)
            subprocess.run(['systemctl', 'restart', SERVICE], check=False)
            print('! Возвращена прежняя версия WPO')
        raise
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print('ОШИБКА:', exc, file=sys.stderr)
        sys.exit(1)
