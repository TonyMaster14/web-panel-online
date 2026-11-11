#!/usr/bin/env bash
# Nodes Lab v25 — always publish a chosen website immediately on Save.
set -Eeuo pipefail
umask 077
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
AUTO="$APP/wpo_node_autotemplate.py"
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запускайте на основном VPS WPO от root.'; exit 1; }
for file in "$PANEL" "$UI" "$AUTO"; do [[ -s "$file" ]] || { echo "Файл не найден: $file"; exit 1; }; done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Основная служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-auto-v20' "$PANEL" || { echo 'Требуется Nodes Lab v20 или новее.'; exit 1; }
grep -Fq '/* wpo-node-divider-v18' "$UI" || { echo 'Нужен компактный интерфейс v18 или новее.'; exit 1; }

if grep -Fq '# wpo-node-template-save-v25' "$PANEL" &&
   grep -Fq '# wpo-node-template-sync-v25' "$AUTO" &&
   grep -Fq 'Шаблон: {esc(site_name)}' "$UI"; then
    echo 'Nodes Lab v25 уже установлен.'
    exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v25-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
for file in "$PANEL" "$UI" "$AUTO"; do cp -a "$file" "$BACKUP/$(basename "$file")"; done

if ! python3 - "$PANEL" "$UI" "$AUTO" <<'PY_PATCH'
from pathlib import Path
import sys
panel_path, ui_path, auto_path = map(Path, sys.argv[1:])
panel=panel_path.read_text(encoding='utf-8')
ui=ui_path.read_text(encoding='utf-8')
auto=auto_path.read_text(encoding='utf-8')

start_marker='                elif operation=="edit":\n'
end_marker='                elif operation=="rename":\n'
if panel.count(start_marker)!=1:
    raise RuntimeError('Не найден единственный обработчик редактирования ноды; файлы не изменены.')
start=panel.index(start_marker)
end=panel.find(end_marker,start)
if end==-1:
    raise RuntimeError('Не найдена граница обработчика ноды; файлы не изменены.')
previous=panel[start:end]
for expected in (
    'site-template',
    'selected["site_template_id"]=template_id',
    'selected.pop("auto_site_template_id",None)',
    'node_api.save_nodes(NODES_FILE,nodes)',
):
    if expected not in previous:
        raise RuntimeError('Неожиданная версия обработчика '+expected+'; файлы не изменены.')

new_handler='''                elif operation=="edit":
                    # wpo-node-template-save-v25: every Save publishes to the remote agent,
                    # including re-selecting the currently stored template.
                    # Lock with the auto-template worker to avoid a stale auto-push.
                    with wpo_node_auto.registry_lock:
                        nodes=node_api.load_nodes(NODES_FILE); uid=form.get("id","")
                        selected=next((node for node in nodes if node.get("id")==uid),None)
                        if selected is None: raise node_api.NodeError("Нода не найдена.")
                        new_name=node_api.clean_text(form.get("name",""),"Название ноды",80)
                        template_id=str(form.get("site_template","")).strip()
                        presets=all_presets()
                        allowed={str(item.get("id")):item for item in presets if isinstance(item,dict)}
                        if template_id and template_id not in allowed:
                            raise node_api.NodeError("Шаблон не найден в настройках панели.")
                        # Capabilities are advertised by the live agent; older node
                        # registrations did not persist them in the controller registry.
                        # The authenticated POST itself is the authoritative check.
                        if template_id:
                            try:
                                payload=wpo_node_auto._payload(presets,template_id)
                            except (ValueError,OSError) as exc:
                                raise node_api.NodeError("Не удалось подготовить шаблон: "+str(exc)) from exc
                        else:
                            payload={"template_id":"","html":"","assets":[]}
                        try:
                            response=node_api.request(
                                selected,"POST",node_api.API_PREFIX+"/site-template",payload,timeout=35
                            )
                        except node_api.NodeError as exc:
                            raise node_api.NodeError("Сайт ноды не обновлён: "+str(exc)) from exc
                        if str(response.get("template_id",""))!=template_id:
                            raise node_api.NodeError("Нода не подтвердила применение выбранного шаблона.")
                        # Save the label only after the website was actually accepted.
                        selected["site_template_id"]=template_id
                        selected.pop("auto_site_template_id",None)
                        selected["name"]=new_name
                        node_api.save_nodes(NODES_FILE,nodes)
                    if self.headers.get("X-WPP-Async","")=="1":
                        self.send_json({"ok":True,"site_template_id":template_id}); return
'''
panel=panel[:start]+new_handler+panel[end:]

# An auto-assign worker can otherwise overwrite a manually saved page between
# its initial registry check and its subsequent POST. Keep its POST under the
# same registry lock as the manual handler; the lock is reentrant.
old_worker='''                        node_copy = dict(selected)
                    payload = _payload(all_presets(), tid)
                    node_api.request(
                        node_copy, "POST", node_api.API_PREFIX + "/site-template",
                        payload, timeout=30,
                    )
'''
new_worker='''                        # wpo-node-template-sync-v25: serialize auto and manual publishing.
                        payload = _payload(all_presets(), tid)
                        node_api.request(
                            dict(selected), "POST", node_api.API_PREFIX + "/site-template",
                            payload, timeout=30,
                        )
'''
if auto.count(old_worker)!=1:
    raise RuntimeError('Не найдена ожидаемая фоновая отправка; файлы не изменены.')
auto=auto.replace(old_worker,new_worker,1)

old_title='<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p>'
new_title='<p class="wpo-node-template" title="Шаблон: {esc(site_name)}">{icon("settings")} Шаблон: {esc(site_name)}</p>'
if ui.count(old_title)!=1:
    raise RuntimeError('Не найдена единственная подпись шаблона ноды; файлы не изменены.')
ui=ui.replace(old_title,new_title,1)

for path,content in [(panel_path,panel),(ui_path,ui),(auto_path,auto)]:
    compile(content,str(path),'exec')
# All validations complete. Install using temporary files on the same filesystem.
staged=[]
for path,content in [(panel_path,panel),(ui_path,ui),(auto_path,auto)]:
    temporary=path.with_suffix('.py.nodes25tmp')
    temporary.write_text(content,encoding='utf-8')
    temporary.chmod(path.stat().st_mode & 0o777)
    staged.append((temporary,path))
for temporary,path in staged:
    temporary.replace(path)
print('Сохранение любого шаблона теперь публикует сайт сразу; подписи карточек обновлены.')
PY_PATCH
then
    for name in panel.py wpp_ui.py wpo_node_autotemplate.py; do cp -a "$BACKUP/$name" "$APP/$name"; done
    echo 'Изменения не применены. Исходные файлы восстановлены.'
    exit 1
fi

if ! python3 -m py_compile "$PANEL" "$UI" "$AUTO" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
    for name in panel.py wpp_ui.py wpo_node_autotemplate.py; do cp -a "$BACKUP/$name" "$APP/$name"; done
    systemctl restart "$SERVICE" || true
    echo 'Проверка завершилась ошибкой: предыдущая версия восстановлена.'
    exit 1
fi

echo 'Nodes Lab v25 установлен: каждый выбор шаблона применяется при сохранении.'
echo 'Автошаблоны не могут перезаписать ручной выбор.'
echo 'В карточках отображается «Шаблон: ...».'
echo "Резервная копия: $BACKUP"
echo 'Существующие ноды, VPN и ветка GitHub main не изменены.'
