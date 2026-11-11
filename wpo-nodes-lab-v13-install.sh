#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR=/opt/tproxy-panel
PANEL="$APP_DIR/panel.py"
UI="$APP_DIR/wpp_ui.py"
GEO="$APP_DIR/wpo_node_geo.py"
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Требуется root на основном VPS.'; exit 1; }
for item in "$PANEL" "$UI"; do [[ -s "$item" ]] || { echo "Не найден $item"; exit 1; }; done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена'; exit 1; }
grep -Fq 'def wpo_pending_load' "$PANEL" || { echo 'Nodes Lab не найден. Ничего не изменено.'; exit 1; }
grep -Fq 'wpo-node-label' "$UI" || { echo 'Неподдерживаемая версия UI нод.'; exit 1; }

if grep -Fq '# wpo-node-country-v13' "$PANEL"; then
  echo 'Обновление геолокации v13 уже установлено.'
  exit 0
fi
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 15 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-geo-v13.py' -o "$TMP"
python3 - "$TMP" <<'PY_CHECK'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text(encoding="utf-8")
assert "def lookup_country(" in s and "def enrich(" in s
compile(s,"wpo_node_geo.py","exec")
PY_CHECK

BACKUP="/var/lib/tproxy-panel/nodes-lab-v13-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$UI" "$BACKUP/wpp_ui.py"
if [[ -f "$GEO" ]]; then cp -a "$GEO" "$BACKUP/wpo_node_geo.py"; fi

if ! python3 - "$PANEL" "$UI" "$TMP" "$GEO" <<'PY_PATCH'
from pathlib import Path
import sys

panel_path,ui_path,geo_source,geo_path=map(Path,sys.argv[1:])
panel=panel_path.read_text(encoding='utf-8')
ui=ui_path.read_text(encoding='utf-8')
def once(source,old,new,label):
    matches=source.count(old)
    if matches!=1:
        raise RuntimeError(f'{label}: найдено {matches} совпадений вместо одного.')
    return source.replace(old,new,1)

panel=once(panel,
    'import shlex\n',
    'import shlex\nimport wpo_node_geo as wpo_node_geo  # wpo-node-country-v13\n',
    'Импорт геолокации')
panel=once(panel,
    'now=int(time.time()); current=node_api.load_nodes(NODES_FILE); changed=False',
    'now=int(time.time()); current=node_api.load_nodes(NODES_FILE); changed=wpo_node_geo.enrich(current,now)',
    'Автообновление страны для неизвестных нод')
panel=once(panel,
    '"nodes":[{"id":n.get("id"),"status":n.get("status","online")} for n in current]',
    '"nodes":[{"id":n.get("id"),"status":n.get("status","online"),"country_code":n.get("country_code","UN"),"name":n.get("name","")} for n in current]',
    'Страна в ответе статуса')
panel=once(panel,
    'n["name"]=display; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"',
    'n["name"]=str(n.get("country_name") or display) if n.get("country_code")!="UN" else display; n["name_auto"]=True; n["status"]="online"; n["status_detail"]="Агент зарегистрирован"',
    'Имя новой ноды из страны')
panel=once(panel,
    'selected["name"]=new_name',
    'selected["name"]=new_name; selected["name_auto"]=False',
    'Сохранение пользовательских имён')

ui=once(ui,
    'const state=map[n.status]||map.offline;el.className=',
    'if(n.name&&el.closest(".wpo-node-card")?.querySelector(".wpo-node-label h3")?.textContent.trim()!==n.name){location.reload();return}if(n.country_code&&n.country_code!=="UN"&&el.closest(".wpo-node-card")?.querySelector(".wpo-node-flag")?.textContent.includes("🌐")){location.reload();return}const state=map[n.status]||map.offline;el.className=',
    'Автообновление карточки при появлении флага')

compile(panel,str(panel_path),'exec')
compile(ui,str(ui_path),'exec')
geo=geo_source.read_text(encoding='utf-8')
compile(geo,str(geo_path),'exec')
for target,value in [(geo_path,geo),(panel_path,panel),(ui_path,ui)]:
    tmp=target.with_suffix(target.suffix+'.v13tmp')
    tmp.write_text(value,encoding='utf-8')
    tmp.chmod(target.stat().st_mode & 0o777 if target.exists() else 0o644)
    tmp.replace(target)
print('Геолокация нод обновлена. Имена, заданные вручную, сохраняются.')
PY_PATCH
then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_geo.py" ]]; then cp -a "$BACKUP/wpo_node_geo.py" "$GEO"; else rm -f "$GEO"; fi
  echo 'Ошибка проверки: исходные файлы восстановлены.'
  exit 1
fi
if ! python3 -m py_compile "$PANEL" "$UI" "$GEO" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/panel.py" "$PANEL"
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  if [[ -f "$BACKUP/wpo_node_geo.py" ]]; then cp -a "$BACKUP/wpo_node_geo.py" "$GEO"; else rm -f "$GEO"; fi
  systemctl restart "$SERVICE" || true
  echo 'Ошибка при запуске. Панель возвращена к предыдущей версии.'
  exit 1
fi
echo "Nodes Lab v13: добавлена повторная геолокация нод по IP, с сохранением ручных названий."
echo 'Откройте раздел Ноды: информация обновится автоматически при следующей проверке.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main не изменён. На VPS ноды изменения не требуются.'
