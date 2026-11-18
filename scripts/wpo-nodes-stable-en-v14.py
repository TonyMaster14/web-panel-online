#!/usr/bin/env python3
"""WPO Nodes: preserve stable 1s polling, translate remaining UI, test branch only.

Safe updater for existing /opt/tproxy-panel/wpp_ui.py. No node registry, client,
connection, Xray or account data is touched. Makes a file backup and rolls back
on a failed service restart. Does not download or execute other components.
"""
import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

UI = Path('/opt/tproxy-panel/wpp_ui.py')
SERVICE = 'tproxy-panel.service'
BACKUP = Path('/var/backups/web-panel-online')
MARKER = '# WPO_NODES_STABLE_EN_V14'

# Exact matches from the user's installed WPO UI snapshot. This is deliberately
# fail-closed: never change a source version with unknown DOM/JS structure.
NAME_FROM_DOM = 'querySelector(".wpo-node-label h3")?.textContent.trim()'
NAME_FROM_DATA = 'querySelector("[data-node-edit]")?.dataset.nodeName'
STATUS_OLD = "el.querySelector('b').textContent=state[0]"
STATUS_NEW = ("el.querySelector('b').textContent="
              "document.documentElement.dataset.wpoLanguage==='en'?"
              "({online:'Online',installing:'Installing',registration:'Registration',"
              "offline:'Offline',error:'Error'}[state[1]]||'Offline'):state[0]")
HEADER_OLD = '<h2>⚙️ Управление нодами</h2>'
HEADER_NEW = ("<h2>⚙️ <span data-wpo-no-translate>"
              '<span class="wpo-v14-ru">Управление нодами</span>'
              '<span class="wpo-v14-en">Node management</span>'
              '</span></h2>')
PORT_OLD = ('<span class="connection-port-empty">Будет назначен'
            '<small>при создании клиента</small></span>')
PORT_NEW = ('<span class="connection-port-empty" data-wpo-no-translate>'
            '<span class="wpo-v14-ru">Будет назначен</span>'
            '<span class="wpo-v14-en">Will be assigned</span>'
            '<small><span class="wpo-v14-ru">при создании клиента</span>'
            '<span class="wpo-v14-en">when a client is created</span></small>'
            '</span>')
SITE_NAME_OLD = ("        site_name=next((str(p.get('name','')) for p in presets "
                 "if p.get('id')==site_id),'Сайт не выбран') "
                 "if site_id else 'Сайт не выбран'")
SITE_NAME_NEW = SITE_NAME_OLD + '''
        # Visible built-in template names only: do not change stored template ids.
        site_name_en={
            'Салон красоты': 'Beauty salon',
            'Автосалон': 'Car dealership',
            'Открытие кофейни': 'Coffee shop opening',
            'Сайт не выбран': 'No website selected',
        }.get(site_name,site_name)'''
TEMPLATE_OLD = ('title="Шаблон: {esc(site_name)}">{icon("settings")} '
                'Шаблон: {esc(site_name)}</p>')
TEMPLATE_NEW = (
    'title="{esc(site_name)}">{icon("settings")} '
    '<span data-wpo-no-translate>'
    '<span class="wpo-v14-ru">Шаблон:</span>'
    '<span class="wpo-v14-en">Template:</span></span> '
    '<span data-wpo-no-translate>'
    '<span class="wpo-v14-ru">{esc(site_name)}</span>'
    '<span class="wpo-v14-en">{esc(site_name_en)}</span></span></p>'
)
CSS_ADDON = '''
# WPO_NODES_STABLE_EN_V14
# Localized labels are independent of the translator's MutationObserver, so
# polling every second cannot turn visible statuses or captions back to RU.
CSS += """
.wpo-v14-en{display:none}
html[data-wpo-language="en"] .wpo-v14-ru{display:none}
html[data-wpo-language="en"] .wpo-v14-en{display:inline}
"""
'''


def change(source):
    if MARKER in source:
        return source, False
    if ("WPO_C333_I18N_JS" not in source
            or "WPO_C333_LANGUAGE_THEME_V1" not in source
            or "setInterval(refresh,1000)" not in source):
        raise ValueError('Неизвестная версия интерфейса WPO. Изменений нет.')
    if source.count(NAME_FROM_DOM) == 1:
        source = source.replace(NAME_FROM_DOM, NAME_FROM_DATA, 1)
        print('✓ Зафиксировано сравнение исходного имени ноды (без перезагрузки при EN)')
    elif source.count(NAME_FROM_DATA) == 1:
        print('✓ Исправление перезагрузок уже установлено — сохраняем его')
    else:
        raise ValueError('Не найден безопасный механизм сравнения имени ноды. Изменений нет.')

    modifications = (
        (STATUS_OLD, STATUS_NEW, '✓ Статусы нод: В сети / Online и остальные RU/EN'),
        (HEADER_OLD, HEADER_NEW, '✓ Заголовок «Управление нодами» на EN'),
        (PORT_OLD, PORT_NEW, '✓ Колонка PORT: «Будет назначен при создании клиента» на EN'),
        (SITE_NAME_OLD, SITE_NAME_NEW, '✓ Встроенные шаблоны нод: названия на EN'),
        (TEMPLATE_OLD, TEMPLATE_NEW, '✓ Подпись «Шаблон» на карточках нод на EN'),
    )
    for old, new, message in modifications:
        if source.count(old) != 1:
            raise ValueError('Не найден точный фрагмент интерфейса: '+message)
        source = source.replace(old, new, 1)
        print(message)
    source += '\n'+CSS_ADDON
    compile(source,str(UI),'exec')
    return source, True


def service_up():
    return subprocess.run(['systemctl','is-active','--quiet',SERVICE],
                          check=False).returncode == 0


def restart():
    subprocess.run(['systemctl','restart',SERVICE],check=True,timeout=45)


def apply(source):
    if not service_up():
        raise RuntimeError('Служба WPO не активна до изменений. Установка отменена.')
    target, changed = change(source)
    if not changed:
        print('✓ V14 уже установлен. Повторное применение не требуется.')
        return
    BACKUP.mkdir(parents=True,exist_ok=True)
    backup = BACKUP/('wpp_ui-before-v14-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.py')
    if backup.exists():
        raise RuntimeError('Файл резервной копии с такой датой уже существует.')
    shutil.copy2(UI,backup)
    os.chmod(backup,0o600)
    print('✓ Резервная копия создана:',backup)
    tmp = None
    changed_live = False
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=UI.parent,
                                         prefix='.wpo-v14-',suffix='.py',
                                         delete=False) as fp:
            fp.write(target)
            tmp = Path(fp.name)
        old_stat = UI.stat()
        os.chmod(tmp,stat.S_IMODE(old_stat.st_mode))
        os.chown(tmp,old_stat.st_uid,old_stat.st_gid)
        os.replace(tmp,UI)
        changed_live = True
        restart()
        for _ in range(15):
            if service_up():
                print('✓ Служба WPO работает')
                print('✓ Ноды и подключения не переустанавливались')
                print('✓ Готово: WPO Nodes EN V14 (тестовая версия)')
                return
            time.sleep(1)
        raise RuntimeError('Служба WPO не запустилась после изменения.')
    except Exception:
        if changed_live:
            shutil.copy2(backup,UI)
            print('! Возвращаем исходный wpp_ui.py из резервной копии')
            subprocess.run(['systemctl','restart',SERVICE],check=False)
        raise
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description='WPO: safe Nodes EN update')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true',help='Check without changes')
    mode.add_argument('--apply',action='store_true',help='Backup and apply changes')
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise SystemExit('Нужен sudo.')
    if not UI.is_file() or UI.is_symlink():
        raise SystemExit('WPO не найдена или путь является ссылкой. Изменений нет.')
    src=UI.read_text(encoding='utf-8')
    if args.check:
        _, modified=change(src)
        print('✓ Проверка завершена. Изменения:', 'доступны' if modified else 'уже установлены')
    else:
        apply(src)


if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as e:
        print('ОШИБКА:',e,file=sys.stderr)
        sys.exit(1)
