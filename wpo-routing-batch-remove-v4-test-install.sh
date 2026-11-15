#!/usr/bin/env bash
# TEST ONLY WPO Routing v4. Repairs batch removal and red inactive indicator.
# Does not modify any routing.json, users, keys, Xray, Caddy or VPN nodes.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите sudo на тестовом контроллере WPO.' >&2; exit 2; }

APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
UNIT=tproxy-panel.service
[[ -s "$PANEL" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
   echo 'Нужен контроллер WPO, не отдельная VPN-нода. Ничего не изменено.' >&2
   exit 2
}
systemctl cat "$UNIT" >/dev/null
exec 9>/run/lock/wpo-routing-batch-v4.lock
flock -n 9 || { echo 'Другое обновление WPO уже выполняется.' >&2; exit 2; }

TMP="$(mktemp -d /tmp/wpo-routing-batch-v4.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup(){
  code=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo 'Ошибка запуска или проверки. Возвращаю прежний интерфейс и обработчик.' >&2
    cp -a "$BACKUP/panel.py" "$PANEL" || true
    cp -a "$BACKUP/wpp_ui.py" "$UI" || true
    rm -f "$APP"/__pycache__/panel.*.pyc "$APP"/__pycache__/wpp_ui.*.pyc
    systemctl restart "$UNIT" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TMP"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

REF=3eaa0985eec163a39ddc12e7d967c0c59c063d30
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
  --connect-timeout 12 --max-time 90 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/wpo-routing-batch-remove-v4-patch.py" \
  -o "$TMP/patch.py"
python3 -m py_compile "$TMP/patch.py"
python3 "$TMP/patch.py" --ui-input "$UI" --ui-output "$TMP/ui.py" \
  --app-input "$PANEL" --app-output "$TMP/panel.py"
python3 -m py_compile "$TMP/ui.py" "$TMP/panel.py"

verify(){
  PYTHONPATH="$APP" python3 - "$1" "$2" <<'PY'
import importlib.util,sys,ast
from pathlib import Path
ui_path,app_path=map(Path,sys.argv[1:3])
src=app_path.read_text(encoding="utf-8")
ast.parse(src)
assert '# wpo-routing-explicit-remove-all-v4' in src, 'Не установлен обработчик полного удаления'
assert 'elif operation=="remove-selected": routing_store.update_selected(' in src
assert 'elif operation=="remove-all" and not is_awg: routing_store.delete_profile(' in src
spec=importlib.util.spec_from_file_location("wpo_batch_remove_v4_check",ui_path)
ui=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
items=[{"id":"vless","name":"VLESS XHTTP","protocol":"vless","enabled":True},
       {"id":"hyst","name":"Hysteria2","protocol":"hysteria","enabled":True}]
state={"profiles":{"vless":{"enabled":True,"ru_direct":True,"youtube_proxy":True}}}
html=ui.routing_ui(items,state,"/panel-test","csrf-test")
assert 'data-routing-stored="1"' in html, 'Сохранённые правила не распознаются'
assert 'button.value=&#x27;remove-all&#x27;' in html or "button.value='remove-all'" in html, 'Отсутствует удаление всех правил'
assert 'button.value===&#x27;remove-selected&#x27;' in html or "button.value==='remove-selected'" in html
assert 'name="operation" value="remove-selected"' in html
assert 'name="operation" value="add-selected"' in html
assert 'routing-protocol-status:not(.is-on)' in html and '#ef4444' in html
assert 'data-routing-enabled="1"' in html
assert 'class="routing-toggle is-active"' in html
empty=ui.routing_ui(items,{"profiles":{}},"/panel-test","csrf-test")
assert 'data-routing-stored="0"' in empty
assert 'data-routing-enabled="0"' in empty
print('✓ Реальный HTML: массовое удаление, сохранённые галочки и красный индикатор')
print('✓ Сервер: удаление выбранных правил и отдельно всей маршрутизации')
PY
}
verify "$TMP/ui.py" "$TMP/panel.py"
if cmp -s "$UI" "$TMP/ui.py" && cmp -s "$PANEL" "$TMP/panel.py"; then
    echo '✓ Исправление уже установлено; повторных изменений нет.'
    exit 0
fi

BACKUP_ROOT=/var/lib/tproxy-panel/routing-batch-v4-backups
install -d -m 0700 -o root -g root "$BACKUP_ROOT"
BACKUP="$BACKUP_ROOT/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 -o root -g root "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"
cp -a "$PANEL" "$BACKUP/panel.py"
ROLLBACK=1
install -o root -g root -m 0644 "$TMP/ui.py" "$UI"
install -o root -g root -m 0644 "$TMP/panel.py" "$PANEL"
rm -f "$APP"/__pycache__/panel.*.pyc "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$UNIT"
PANEL_PATH="$(systemctl show -p Environment --value "$UNIT" |
  tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n 1)"
if [[ ! "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]]; then
  PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n 1)"
fi
[[ "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]] || exit 4
HEALTHY=0
for attempt in {1..15}; do
  if systemctl is-active --quiet "$UNIT" &&
     curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
         "http://127.0.0.1:8090$PANEL_PATH/__health" >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
  sleep 1
done
[[ "$HEALTHY" == 1 ]] || exit 4
verify "$UI" "$PANEL"
ROLLBACK=0
echo '✓ Массовое удаление исправлено: выбраны пункты — убираются только они.'
echo '✓ Без дополнительных галочек можно удалить всю текущую маршрутизацию.'
echo '✓ После удаления всех правил статус становится красным («отключена»).'
echo '✓ Ни пользователи, ни ключи, ни VPN-службы не изменены.'
echo "Резервная копия: $BACKUP"
echo 'Обнови страницу «Маршрутизация»: Ctrl+Shift+R (Mac: Cmd+Shift+R).'
