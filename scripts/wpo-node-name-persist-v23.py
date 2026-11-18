#!/usr/bin/env python3
"""WPO V23: persist manually renamed nodes, and save the node editor without reloading.

Patches the installed controller and UI only, not the registry or connections.
Preserves automatic geo names for nodes not manually renamed.
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

ROOT = Path('/opt/tproxy-panel')
PANEL = ROOT / 'panel.py'
UI = ROOT / 'wpp_ui.py'
SERVICE = 'tproxy-panel.service'
BACKUPS = Path('/var/backups/web-panel-online')
MARK_PANEL = '# WPO_NODE_RENAME_PERSIST_V23'
MARK_UI = '# WPO_NODE_RENAME_NO_RELOAD_V23'

JS_OLD = 'editDlg.close();location.reload()'
JS_NEW = r"""{
 const uid=f.elements.id.value;
 const saved=String(d.name??f.elements.name.value??'').trim();
 const edit=Array.from(document.querySelectorAll('[data-node-edit]')).find(x=>x.dataset.nodeEdit===uid);
 const card=edit?.closest('.wpo-node-card');
 const template=String(d.site_template_id??f.elements.site_template.value??'');
 if(edit){
  const wasTemplate=edit.dataset.nodeTemplate||'';
  edit.dataset.nodeName=saved;
  edit.dataset.nodeTemplate=template;
  const heading=card?.querySelector('.wpo-node-label h3');
  if(heading){heading.textContent=saved;heading.title=saved;}
  if(wasTemplate!==template){
   const hint=card?.querySelector('.wpo-node-template');
   if(hint){
    const chosen=f.elements.site_template.selectedOptions?.[0]?.textContent?.trim()||'Стандартная страница ноды';
    const text=Array.from(hint.childNodes).find(n=>n.nodeType===Node.TEXT_NODE);
    if(text)text.nodeValue=' Шаблон: '+chosen;
    else hint.append(document.createTextNode(' Шаблон: '+chosen));
    hint.title='Шаблон: '+chosen;
   }
  }
 }
 const reality=document.querySelector('#wpoRealityForm select[name="node_id"]');
 if(reality)for(const option of reality.options){if(option.value===uid)option.textContent=saved;}
 window.showPanelToast?.(
  document.documentElement.dataset.wpoLanguage==='en'?'Node saved':'Нода сохранена',
  'success'
 );
}
editDlg.close()"""

STATUS_BEGIN_OLD = 'now=int(time.time()); current=node_api.load_nodes(NODES_FILE); changed=wpo_node_geo.enrich(current,now)'
STATUS_BEGIN_NEW = '''now=int(time.time()); current=node_api.load_nodes(NODES_FILE)
             # Take an immutable snapshot before polling remote nodes.
             wpo_v23_before={str(n.get("id")):dict(n) for n in current if isinstance(n,dict)}
             changed=wpo_node_geo.enrich(current,now)'''
STATUS_SAVE_OLD = 'if changed: node_api.save_nodes(NODES_FILE,current)\n            pending=wpo_pending_load(); pending_rows=[]'
STATUS_SAVE_NEW = '''if changed:
                 # Merge only observed changes into the latest registry. A
                 # concurrent user rename or node enrollment always wins.
                 with wpo_node_auto.registry_lock:
                     live=node_api.load_nodes(NODES_FILE)
                     observed={str(n.get("id")):n for n in current if isinstance(n,dict)}
                     dirty=False
                     fields=("status","status_detail","status_checked_at","version",
                             "capabilities","geo_checked_at","country_code",
                             "country_name","name","name_auto")
                     for row in live:
                         uid=str(row.get("id"))
                         before=wpo_v23_before.get(uid)
                         after=observed.get(uid)
                         if before is None or after is None: continue
                         for field in fields:
                             original=before.get(field)
                             updated=after.get(field)
                             if updated!=original and row.get(field)==original:
                                 row[field]=updated
                                 dirty=True
                     if dirty: node_api.save_nodes(NODES_FILE,live)
                     current=live
             pending=wpo_pending_load(); pending_rows=[]'''


def indent_replace(source, needle, replacement, base):
    """Keep exact runtime indentation when replacing a controller statement."""
    if source.count(needle) != 1:
        raise RuntimeError('Неожиданный обработчик фонового обновления; изменений нет')
    pos = source.index(needle)
    begin = source.rfind('\n', 0, pos) + 1
    indent = source[begin:pos]
    if not indent or indent.strip() or any(x not in ' \t' for x in indent):
        raise RuntimeError('Неизвестные отступы обработчика статусов')
    lines = replacement.split('\n')
    adjusted = [lines[0]]
    for line in lines[1:]:
        if line and not line.startswith(' ' * base):
            raise RuntimeError('Неверный отступ во встроенном патче')
        adjusted.append(indent + line[base:])
    return source.replace(needle, '\n'.join(adjusted), 1)


def patch_panel(source):
    if MARK_PANEL in source:
        print('✓ V23: сохранение имён уже исправлено')
        return source, False
    start_anchor = '                elif operation=="edit":\n'
    end_anchor = '                elif operation=="rename":\n'
    if source.count(start_anchor) != 1:
        raise RuntimeError('Не найден обработчик редактирования ноды в panel.py')
    start = source.index(start_anchor)
    end = source.find(end_anchor, start)
    if end < 0:
        raise RuntimeError('Не найдена граница обработчика редактирования')
    block = source[start:end]
    if 'with wpo_node_auto.registry_lock:' not in block or 'selected.pop("auto_site_template_id",None)' not in block:
        raise RuntimeError('Неизвестная версия обработчика Save (ожидалась V25)')
    name_anchor = '                        selected["name"]=new_name\n                        node_api.save_nodes(NODES_FILE,nodes)'
    # Compare before assigning: only an explicit rename disables automatic country naming.
    name_fixed = '''                        if new_name!=str(selected.get("name") or ""):
                            selected["name_auto"]=False
                        selected["name"]=new_name
                        node_api.save_nodes(NODES_FILE,nodes)'''
    if block.count(name_anchor) != 1:
        raise RuntimeError('Не найдена точка сохранения имени; изменений нет')
    block = block.replace(name_anchor, name_fixed, 1)
    old_response = 'self.send_json({"ok":True,"site_template_id":template_id}); return'
    new_response = 'self.send_json({"ok":True,"site_template_id":template_id,"name":new_name}); return'
    if block.count(old_response) != 1:
        raise RuntimeError('Неизвестный JSON-ответ Save; изменений нет')
    block = block.replace(old_response, new_response, 1)
    updated = source[:start] + block + source[end:]
    if '# wpo-node-enrollment-race-v1' in updated:
        print('✓ Защита фонового опроса от гонки уже установлена')
    elif updated.count(STATUS_BEGIN_OLD) == 1 and updated.count(STATUS_SAVE_OLD) == 1:
        updated = indent_replace(updated, STATUS_BEGIN_OLD, STATUS_BEGIN_NEW, 13)
        updated = indent_replace(updated, STATUS_SAVE_OLD, STATUS_SAVE_NEW, 13)
        print('✓ Защита от устаревшей записи фонового опроса добавлена')
    else:
        raise RuntimeError('Неизвестная версия /nodes-status; безопасное обновление невозможно')
    updated = updated.rstrip() + '\n\n' + MARK_PANEL + '\n'
    compile(updated, str(PANEL), 'exec')
    return updated, True


def patch_ui(source):
    if MARK_UI in source:
        print('✓ V23: сохранение карточек уже исправлено')
        return source, False
    for marker in ('# WPO_ALL_NODE_COUNTRY_NAMES_V18',
                   '# WPO_REALITY_NODE_FIXED_LOCALIZED_V22'):
        if marker not in source:
            raise RuntimeError('Неизвестная версия WPO UI: нет ' + marker)
    if source.count(JS_OLD) != 1 or source.count('id="wpoEditNodeForm"') != 1:
        raise RuntimeError('Не найден однозначный обработчик Save в интерфейсе')
    updated = source.replace(JS_OLD, JS_NEW, 1).rstrip() + '\n\n' + MARK_UI + '\n'
    compile(updated, str(UI), 'exec')
    return updated, True


def service_active():
    return subprocess.run(['systemctl','is-active','--quiet',SERVICE],
                          check=False).returncode == 0


def main():
    parser = argparse.ArgumentParser(description='WPO V23: permanent node name changes')
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument('--check', action='store_true')
    options.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Необходимо sudo')
    for path in (PANEL, UI):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Не найден файл WPO: ' + str(path))
    original = {path:path.read_text(encoding='utf-8') for path in (PANEL, UI)}
    panel, panel_changed = patch_panel(original[PANEL])
    ui, ui_changed = patch_ui(original[UI])
    if not panel_changed and not ui_changed:
        print('✓ V23 уже установлен, ничего не меняем')
        return
    if panel_changed != ui_changed:
        raise RuntimeError('Неполная предыдущая установка V23; изменений нет')
    if args.check:
        print('✓ Проверка пройдена. Файлы WPO не изменены.')
        return
    if not service_active():
        raise RuntimeError('WPO не работала до обновления; изменений нет')
    os.umask(0o077)
    backup_dir = BACKUPS / ('node-names-v23-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    if backup_dir.exists():
        raise RuntimeError('Резервная копия с таким именем уже существует')
    backup_dir.mkdir(parents=True, mode=0o700)
    for path in (PANEL, UI):
        shutil.copy2(path, backup_dir/path.name)
        os.chmod(backup_dir/path.name,0o600)
    print('✓ Резервные копии:', backup_dir)
    staged = []
    replaced = []
    try:
        for path, data in ((PANEL,panel),(UI,ui)):
            with tempfile.NamedTemporaryFile('w', encoding='utf-8',
                    dir=path.parent, prefix='.wpo-v23-', suffix='.py',
                    delete=False) as file:
                file.write(data)
                temporary = Path(file.name)
            staged.append(temporary)
            old = path.stat()
            os.chown(temporary, old.st_uid, old.st_gid)
            os.chmod(temporary, stat.S_IMODE(old.st_mode))
        for path, temporary in zip((PANEL,UI),staged):
            os.replace(temporary,path)
            replaced.append(path)
        subprocess.run(['systemctl','restart',SERVICE],check=True,timeout=45)
        for _ in range(20):
            if service_active():
                print('✓ WPO работает. V23 установлен.')
                print('✓ Ручные названия сохраняются в реестре; автоимена остаются у новых нод.')
                print('✓ Карточки обновляются после Save без перезагрузки страницы.')
                return
            time.sleep(1)
        raise RuntimeError('WPO не запустилась после установки')
    except Exception:
        if replaced:
            for path in replaced:
                shutil.copy2(backup_dir/path.name,path)
            subprocess.run(['systemctl','restart',SERVICE],check=False)
            print('! Восстановлены оба файла прежней версии')
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('ОШИБКА:', error, file=sys.stderr)
        sys.exit(1)
