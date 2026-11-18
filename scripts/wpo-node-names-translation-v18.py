#!/usr/bin/env python3
"""WPO V18: translate node country names in cards and node settings.

Translation affects display only; all saved names, polling and settings remain intact.
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
MARKER = '# WPO_ALL_NODE_COUNTRY_NAMES_V18'
ADDON = "\n# WPO_ALL_NODE_COUNTRY_NAMES_V18\n# Only visible node names are localised. Stored server names stay unchanged.\n_WPO_V18_JS = \"\\nconst wpoV18Countries={\\\"Польша\\\":\\\"Poland\\\",\\\"Швеция\\\":\\\"Sweden\\\",\\\"Нидерланды\\\":\\\"Netherlands\\\",\\\"Германия\\\":\\\"Germany\\\",\\\"Финляндия\\\":\\\"Finland\\\",\\\"Великобритания\\\":\\\"United Kingdom\\\",\\\"США\\\":\\\"United States\\\",\\\"Франция\\\":\\\"France\\\",\\\"Канада\\\":\\\"Canada\\\",\\\"Норвегия\\\":\\\"Norway\\\",\\\"Дания\\\":\\\"Denmark\\\",\\\"Чехия\\\":\\\"Czechia\\\",\\\"Австрия\\\":\\\"Austria\\\",\\\"Швейцария\\\":\\\"Switzerland\\\",\\\"Испания\\\":\\\"Spain\\\",\\\"Италия\\\":\\\"Italy\\\",\\\"Литва\\\":\\\"Lithuania\\\",\\\"Латвия\\\":\\\"Latvia\\\",\\\"Эстония\\\":\\\"Estonia\\\",\\\"Румыния\\\":\\\"Romania\\\",\\\"Болгария\\\":\\\"Bulgaria\\\",\\\"Турция\\\":\\\"Turkey\\\",\\\"Казахстан\\\":\\\"Kazakhstan\\\",\\\"Россия\\\":\\\"Russia\\\",\\\"Украина\\\":\\\"Ukraine\\\",\\\"Япония\\\":\\\"Japan\\\",\\\"Сингапур\\\":\\\"Singapore\\\",\\\"Гонконг\\\":\\\"Hong Kong\\\",\\\"ОАЭ\\\":\\\"United Arab Emirates\\\",\\\"Исландия\\\":\\\"Iceland\\\",\\\"Ирландия\\\":\\\"Ireland\\\",\\\"Бельгия\\\":\\\"Belgium\\\",\\\"Не указано\\\":\\\"Not specified\\\",\\\"Южная Корея\\\":\\\"South Korea\\\",\\\"Китай\\\":\\\"China\\\",\\\"Тайвань\\\":\\\"Taiwan\\\",\\\"Беларусь\\\":\\\"Belarus\\\",\\\"Молдавия\\\":\\\"Moldova\\\",\\\"Грузия\\\":\\\"Georgia\\\",\\\"Словения\\\":\\\"Slovenia\\\",\\\"Сербия\\\":\\\"Serbia\\\",\\\"Хорватия\\\":\\\"Croatia\\\",\\\"Мексика\\\":\\\"Mexico\\\",\\\"Австралия\\\":\\\"Australia\\\",\\\"Новая Зеландия\\\":\\\"New Zealand\\\",\\\"Индия\\\":\\\"India\\\",\\\"Бразилия\\\":\\\"Brazil\\\",\\\"Кипр\\\":\\\"Cyprus\\\",\\\"Греция\\\":\\\"Greece\\\"};\\ntry{\\n const ruRegions=new Intl.DisplayNames(['ru'],{type:'region'});\\n const enRegions=new Intl.DisplayNames(['en'],{type:'region'});\\n const A='ABCDEFGHIJKLMNOPQRSTUVWXYZ';\\n for(const a of A)for(const b of A){\\n  const code=a+b;\\n  const ruName=ruRegions.of(code),enName=enRegions.of(code);\\n  if(ruName&&enName&&/[А-Яа-яЁё]/u.test(ruName)&&\\n    !Object.prototype.hasOwnProperty.call(wpoV18Countries,ruName))\\n   wpoV18Countries[ruName]=enName;\\n }\\n}catch(_){}\\nconst wpoV18EnglishToRussian=Object.create(null);\\nfor(const [ruName,enName] of Object.entries(wpoV18Countries)){\\n if(!Object.prototype.hasOwnProperty.call(wpoV18EnglishToRussian,enName))\\n  wpoV18EnglishToRussian[enName]=ruName;\\n}\\nfunction wpoV18LocalizedName(input){\\n const text=String(input||'').trim();\\n const ruName=Object.prototype.hasOwnProperty.call(wpoV18Countries,text)?text:wpoV18EnglishToRussian[text];\\n if(!ruName)return null;\\n return lang==='en'?wpoV18Countries[ruName]:ruName;\\n}\\nfunction wpoV18UpdateNames(){\\n const page=document.querySelector('.wpo-nodes-page');if(!page)return;\\n for(const card of page.querySelectorAll('.wpo-node-card')){\\n  const edit=card.querySelector('[data-node-edit]');\\n  const name=card.querySelector('.wpo-node-label h3');if(!name)continue;\\n  if(edit){\\n   const localized=wpoV18LocalizedName(edit.dataset.nodeName||'');\\n   if(localized){\\n    if(name.textContent!==localized)name.textContent=localized;\\n    if(name.title!==localized)name.title=localized;\\n   }\\n  }else{\\n   const inner=name.querySelector('.wpo-node-main-name');if(!inner)continue;\\n   if(!inner.dataset.wpoV18Original)inner.dataset.wpoV18Original=inner.textContent.trim();\\n   const localized=wpoV18LocalizedName(inner.dataset.wpoV18Original);\\n   if(localized&&inner.textContent!==localized)inner.textContent=localized;\\n  }\\n }\\n}\\nfunction wpoV18EditorName(){\\n const form=document.getElementById('wpoEditNodeForm');\\n const dialog=document.getElementById('wpoEditNodeDialog');\\n const input=form?.elements?.name;\\n if(!form||!dialog?.open||!input||input.dataset.wpoV18Dirty==='1')return;\\n const raw=input.dataset.wpoV18Original;if(!raw)return;\\n const localized=wpoV18LocalizedName(raw);\\n if(localized&&input.value!==localized)input.value=localized;\\n}\\nfunction wpoV18BindNameEditor(){\\n const form=document.getElementById('wpoEditNodeForm');\\n const input=form?.elements?.name;\\n if(!form||!input||form.dataset.wpoV18Ready==='1')return;\\n form.dataset.wpoV18Ready='1';\\n input.addEventListener('input',()=>{input.dataset.wpoV18Dirty='1';});\\n document.addEventListener('click',e=>{\\n  const button=e.target?.closest?.('[data-node-edit]');if(!button)return;\\n  input.dataset.wpoV18Original=button.dataset.nodeName||'';\\n  input.dataset.wpoV18Dirty='0';\\n  wpoV18EditorName();\\n });\\n form.addEventListener('formdata',e=>{\\n  if(input.dataset.wpoV18Dirty!=='1'&&input.dataset.wpoV18Original)\\n   e.formData.set('name',input.dataset.wpoV18Original);\\n });\\n}\\nfunction wpoV18SyncNameLanguage(){\\n wpoV18UpdateNames();\\n wpoV18BindNameEditor();\\n wpoV18EditorName();\\n}\\n\"\nif WPO_C333_I18N_JS.count('function controls(){') != 1:\n    raise RuntimeError('WPO V18: language controls changed; refusing to load')\nWPO_C333_I18N_JS = WPO_C333_I18N_JS.replace(\n    'function controls(){',\n    _WPO_V18_JS+'\\nfunction controls(){\\n wpoV18SyncNameLanguage();',1)\n"
def patch(source):
    if MARKER in source:
        print('✓ V18 уже установлен — изменений нет')
        return source, False
    for needed in ('# WPO_LANGUAGE_SAFE_V15', '# WPO_LANGUAGE_SCOPE_PORT_V16',
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
    print('✓ Все страны нод: RU / EN, старые и добавленные позднее')
    print('✓ Основная и дополнительные ноды: имена на выбранном языке')
    print('✓ Node settings: перевод имени страны в поле редактирования')
    print('✓ Неизменённое имя сохраняется в исходном виде')
    print('✓ Пользовательские названия и конфигурации не затрагиваются')
    print('✓ Статусы, автообновление и размер карточек сохранены')
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
    backup = BACKUP_DIR / ('wpp_ui-before-v18-' +
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
                                         prefix='.wpo-v18-', suffix='.py',
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
                print('✓ Служба WPO работает; V18 установлен')
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
    parser = argparse.ArgumentParser(description='WPO V18: RU/EN node country names')
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
