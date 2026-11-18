#!/usr/bin/env python3
"""WPO V21: visually match the readonly main-node field to the IP address field."""
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
MARKER = '# WPO_PRIMARY_REALITY_GREY_V21'
ANCHOR = " readonly.style.display='none';"
STYLES = """ readonly.style.display='none';
 readonly.style.color='var(--muted)';
 readonly.style.backgroundColor='var(--raised,var(--input))';
 readonly.style.cursor='default';
 readonly.style.caretColor='transparent';
 readonly.style.setProperty('-webkit-text-fill-color','var(--muted)');"""


def prepare(source):
    if MARKER in source:
        print('✓ V21 уже установлен. Изменений нет.')
        return source, False
    if '# WPO_PRIMARY_REALITY_READONLY_V20' not in source:
        raise RuntimeError('Не установлена V20; изменений нет.')
    if 'readonly.readOnly=true;' not in source or source.count(ANCHOR) != 1:
        raise RuntimeError('Неизвестная версия поля основной ноды; изменений нет.')
    result = source.replace(ANCHOR, STYLES, 1).rstrip() + '\n\n' + MARKER + '\n'
    compile(result, str(UI), 'exec')
    print('✓ Основная нода выглядит как поле IP-адреса (серый фон и текст).')
    print('✓ EN/RU, блокировка выбора и VLESS REALITY не изменяются.')
    return result, True


def running():
    return subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE], check=False).returncode == 0


def main():
    parser = argparse.ArgumentParser(description='WPO readonly Main node grey style V21')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Нужен sudo')
    if not UI.is_file() or UI.is_symlink():
        raise RuntimeError('Не найден обычный файл WPO')
    updated, changed = prepare(UI.read_text(encoding='utf-8'))
    if args.check or not changed:
        return
    if not running():
        raise RuntimeError('Служба WPO не активна; изменений нет')
    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = BACKUPS / ('wpp-ui-before-v21-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.py')
    if backup.exists():
        raise RuntimeError('Резервная копия с таким именем существует')
    shutil.copy2(UI, backup)
    os.chmod(backup, 0o600)
    print('✓ Резервная копия:', backup)
    tmp = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=UI.parent,
                                         prefix='.wpo-v21-', suffix='.py', delete=False) as stream:
            stream.write(updated)
            tmp = Path(stream.name)
        old = UI.stat()
        os.chown(tmp, old.st_uid, old.st_gid)
        os.chmod(tmp, stat.S_IMODE(old.st_mode))
        os.replace(tmp, UI)
        replaced = True
        subprocess.run(['systemctl', 'restart', SERVICE], check=True, timeout=45)
        for _ in range(15):
            if running():
                print('✓ WPO работает. V21 установлен.')
                return
            time.sleep(1)
        raise RuntimeError('Служба WPO не запустилась')
    except Exception:
        if replaced:
            shutil.copy2(backup, UI)
            subprocess.run(['systemctl', 'restart', SERVICE], check=False)
            print('! Откат к прежней версии выполнен')
        raise
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as err:
        print('ОШИБКА:', err, file=sys.stderr)
        sys.exit(1)
