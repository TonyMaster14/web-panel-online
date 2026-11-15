#!/usr/bin/env bash
# TEST BRANCH: align routing action bar and replace selected-rule check with red dot.
# UI-only. Routing persistence, users, VPN and AmneziaWG server logic are unchanged.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запускайте sudo на тестовом контроллере WPO.' >&2; exit 2; }

APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
UNIT=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
    ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Основная WPO-панель не найдена. Никаких изменений.' >&2; exit 2
}

exec 9>/run/lock/wpo-routing-v6-ui.lock
flock -n 9 || { echo 'Другое обновление интерфейса уже выполняется.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-routing-v6.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup(){
  result=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo 'Проверка WPO не пройдена — восстанавливаю предыдущий интерфейс.' >&2
    cp -a "$BACKUP" "$UI" || true
    rm -f "$APP"/__pycache__/wpp_ui.*.pyc
    systemctl restart "$UNIT" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$WORK"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

REF=501b45a2db628962eb9dbc49a6f4cc5a305f9e52
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
     --connect-timeout 12 --max-time 90 \
     "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/wpo-routing-action-alignment-v6-patch.py" \
     -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
python3 "$WORK/patch.py" --input "$UI" --output "$WORK/ui.py"
python3 -m py_compile "$WORK/ui.py"

verify(){
    PYTHONPATH="$APP" python3 - "$1" <<'PY'
import importlib.util,sys
spec=importlib.util.spec_from_file_location("wpo_routing_visual_v6_check",sys.argv[1])
ui=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
conns=[
    {"id":"vless","protocol":"vless","name":"VLESS XHTTP","enabled":True},
    {"id":"hyst","protocol":"hysteria","name":"Hysteria2","enabled":True},
    {"id":"wg20","protocol":"awg20","name":"AmneziaWG 2.0","enabled":True},
]
state={"profiles":{"vless":{"enabled":True,"ru_direct":True},
                   "hyst":{"enabled":True,"youtube_proxy":True}}}
html=ui.routing_ui(conns,state,"/panel-demo","csrf")
assert 'wpo-routing-action-alignment-red-dot-v6' in html
assert 'content:"✓"' not in html, 'Синяя галочка осталась'
assert 'label.routing-toggle.is-active:has(input:checked)::after' in html
assert 'right:14px;top:50%' in html and 'width:16px;height:16px' in html
assert 'border:1.5px solid #ef4444;border-radius:50%' in html
assert 'display:flex;align-items:center;justify-content:flex-end' in html
assert 'flex-direction:column;align-items:stretch;gap:10px' in html
assert html.count('class="routing-actions-primary"') == 2
assert html.count('class="routing-actions-secondary"') == 2
assert html.count('name="operation" value="add-selected"') == 2
assert html.count('name="operation" value="remove-selected"') == 2
assert "button.value='remove-all'" in html
assert 'data-awg-form="1"' in html and 'Скачать JSON' in html
print('✓ Проверены реальные HTML/CSS: ровные кнопки и красная точка справа')
print('✓ В VLESS/Hysteria2 и AmneziaWG сохранены исходные действия')
PY
}
verify "$WORK/ui.py"
if cmp -s "$UI" "$WORK/ui.py"; then
    verify "$UI"
    echo '✓ Исправление уже установлено. Обновите страницу без кэша.'
    exit 0
fi

BACKUP_DIR=/var/lib/tproxy-panel/routing-v6-backups
install -d -m 0700 -o root -g root "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/wpp_ui-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0644 "$WORK/ui.py" "$UI"
rm -f "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$UNIT"

PANEL_PATH="$(systemctl show -p Environment --value "$UNIT" |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
if [[ ! "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]]; then
  PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' \
      /etc/systemd/system/tproxy-panel.service | head -n1)"
fi
[[ "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]] || exit 4
READY=0
for try in {1..15}; do
    if systemctl is-active --quiet "$UNIT" &&
       curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
           "http://127.0.0.1:8090$PANEL_PATH/__health" >/dev/null 2>&1; then
       READY=1; break
    fi
    sleep 1
done
[[ "$READY" == 1 ]] || exit 4
verify "$UI"
ROLLBACK=0
echo '✓ Кнопки «Добавить» и «Убрать» стоят рядом, по правому краю.'
echo '✓ Галочка заменена красным кружком у отмеченных для удаления правил.'
echo '✓ При обычном добавлении красный кружок не появляется.'
echo '✓ Сохранённые правила, пользователи, ключи и VPN не изменены.'
echo "Резервная копия: $BACKUP"
echo 'Обновите «Маршрутизацию» с очисткой кэша: Ctrl+Shift+R / Cmd+Shift+R.'
