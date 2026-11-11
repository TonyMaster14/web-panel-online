#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
AUTO="$APP/wpo_node_autotemplate.py"
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью WPO.'; exit 1; }
[[ -s "$PANEL" && -s "$UI" ]] || { echo 'Файлы панели не найдены.'; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq 'def wpo_pending_load' "$PANEL" || { echo 'Nodes Lab не обнаружен.'; exit 1; }
grep -Fq 'all_presets()' "$PANEL" || { echo 'Требуется поддержка шаблонов из Nodes Lab v2.'; exit 1; }
grep -Fq '# wpo-node-country-v13' "$PANEL" || { echo 'Требуется установленный Nodes Lab v13 или новее.'; exit 1; }
grep -Fq '# wpo-node-server-icon-v19' "$UI" || { echo 'Требуется установленный Nodes Lab v19.'; exit 1; }

if grep -Fq '# wpo-node-auto-v20' "$PANEL"; then
  echo 'Nodes Lab v20 уже установлен.'
  exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 15 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-autotemplate-v20.py' -o "$TMP"
python3 - "$TMP" <<'PY_CHECK'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text(encoding='utf-8')
assert all(x in s for x in ['def choose(', 'def start(', 'def _loop(', 'registry_lock'])
compile(s,'wpo_node_autotemplate.py','exec')
PY_CHECK

BACKUP="/var/lib/tproxy-panel/nodes-lab-v20-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$UI" "$BACKUP/wpp_ui.py"
if [[ -f "$AUTO" ]]; then cp -a "$AUTO" "$BACKUP/wpo_node_autotemplate.py"; fi

if ! python3 - "$PANEL" "$UI" "$TMP" "$AUTO" <<'PY_PATCH'
from pathlib import Path
import sys
panel_path,ui_path,auto_source,auto_path=map(Path,sys.argv[1:])
panel=panel_path.read_text(encoding='utf-8')
ui=ui_path.read_text(encoding='utf-8')

def once(source,old,new,label):
    cnt=source.count(old)
    if cnt!=1:
        raise RuntimeError(f'{label}: найдено {cnt} совпадений вместо одного. Ничего не изменено.')
    return source.replace(old,new,1)

panel=once(panel,
    'import shlex\n',
    'import shlex\nimport wpo_node_autotemplate as wpo_node_auto  # wpo-node-auto-v20\n',
    'Импорт автоподбора сайтов')

panel=once(panel,
    'class Handler(BaseHTTPRequestHandler):',
    'wpo_node_auto.start(NODES_FILE,all_presets,node_api)\n\nclass Handler(BaseHTTPRequestHandler):',
    'Запуск автоотправки шаблонов в фоне')

# Reserve a template ONLY when a new node is enrolled. Reservations are
# persisted before responding, and never alter old/renamed nodes.
old='''                added=node_api.add_node(NODES_FILE,{"connection_token":packed})
                registered=node_api.load_nodes(NODES_FILE); display=str(payload.get("name","")).strip()[:80] or "Нода"
                for n in registered:
                    if n.get("id")==added.get("id"):
                        n["name"]=str(n.get("country_name") or display) if n.get("country_code")!="UN" else display; n["name_auto"]=True; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"
                node_api.save_nodes(NODES_FILE,registered); pending.pop(digest,None); wpo_pending_save(pending)'''
new='''                with wpo_node_auto.registry_lock:
                    added=node_api.add_node(NODES_FILE,{"connection_token":packed})
                    registered=node_api.load_nodes(NODES_FILE); display=str(payload.get("name","")).strip()[:80] or "Нода"
                    for n in registered:
                        if n.get("id")==added.get("id"):
                            n["name"]=str(n.get("country_name") or display) if n.get("country_code")!="UN" else display; n["name_auto"]=True; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"
                            try:
                                auto_id=wpo_node_auto.choose(registered,all_presets())
                                if auto_id: n["auto_site_template_id"]=auto_id
                            except Exception as auto_error:
                                print("Node auto-template selection:",type(auto_error).__name__,file=sys.stderr,flush=True)
                    node_api.save_nodes(NODES_FILE,registered)
                pending.pop(digest,None); wpo_pending_save(pending)'''
panel=once(panel,old,new,'Автоподбор только для новой ноды')

# Show the chosen label automatically as soon as delivery is confirmed.
panel=once(panel,
    '"country_code":n.get("country_code","UN"),"name":n.get("name","")',
    '"country_code":n.get("country_code","UN"),"name":n.get("name",""),"site_template_id":n.get("site_template_id","")',
    'Актуальный шаблон в ответе статуса')

ui=once(ui,
    'const state=map[n.status]||map.offline;el.className=',
    'const edit=el.closest(".wpo-node-card")?.querySelector("[data-node-edit]");if(edit&&typeof n.site_template_id==="string"&&edit.dataset.nodeTemplate!==n.site_template_id){location.reload();return}const state=map[n.status]||map.offline;el.className=',
    'Автообновление имени шаблона в карточке')

# Manual template edits always have priority over pending auto-assignments.
panel=once(panel,
    '                        selected["site_template_id"]=template_id',
    '                        selected["site_template_id"]=template_id\n                        selected.pop("auto_site_template_id",None)',
    'Ручной выбор отменяет ожидающий автоподбор')

newmod=auto_source.read_text(encoding='utf-8')
compile(newmod,str(auto_path),'exec')
compile(panel,str(panel_path),'exec')
compile(ui,str(ui_path),'exec')

# Stage every file and only then replace originals.
for path,data in [(auto_path,newmod),(panel_path,panel),(ui_path,ui)]:
    tmp=path.with_suffix(path.suffix+'.v20tmp')
    tmp.write_text(data,encoding='utf-8')
    tmp.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
for path in [auto_path,panel_path,ui_path]:
    path.with_suffix(path.suffix+'.v20tmp').replace(path)
print('Включён рандомный подбор шаблона на регистрации и автоматическая публикация.')
PY_PATCH
then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_autotemplate.py" ]]; then cp -a "$BACKUP/wpo_node_autotemplate.py" "$AUTO"; else rm -f "$AUTO"; fi
  echo 'Обновление не применено, исходный код восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$PANEL" "$UI" "$AUTO" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_autotemplate.py" ]]; then cp -a "$BACKUP/wpo_node_autotemplate.py" "$AUTO"; else rm -f "$AUTO"; fi
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или запуска панели. Выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v20 готов: шаблоны выбираются случайно без повторов, пока есть свободные.'
echo 'Новые ноды получают сайт автоматически после регистрации. Старые ноды не изменяются.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main не затронут.'
