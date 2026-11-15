#!/usr/bin/env bash
# TEST ONLY: compact 4 protocol choices + one non-interactive status tile.
# Backs up the UI module and verifies rendered markup before installing.
set -Eeuo pipefail
umask 077

[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на тестовом контроллере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
UNIT=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Нужна основная WPO-панель (контроллер), не отдельная VPN-нода.' >&2
    exit 2
}
systemctl cat "$UNIT" >/dev/null
exec 9>/run/lock/wpo-routing-status-v3.lock
flock -n 9 || { echo 'Другое обновление интерфейса уже выполняется.' >&2; exit 2; }

TMP="$(mktemp -d /tmp/wpo-routing-v3.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup(){
    code=$?
    trap - EXIT
    if [[ "$ROLLBACK" == 1 ]]; then
        echo 'Проверка WPO не прошла; возвращаю предыдущий интерфейс.' >&2
        cp -a "$BACKUP" "$UI" || true
        rm -f "$APP"/__pycache__/wpp_ui.*.pyc
        systemctl restart "$UNIT" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$TMP"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

REV=535a0f07eaa6df99b94f388093236050d6dee9e0
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
  --connect-timeout 12 --max-time 90 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/wpo-routing-status-toprow-v3-patch.py" \
  -o "$TMP/patch.py"
python3 -m py_compile "$TMP/patch.py"
python3 "$TMP/patch.py" --input "$UI" --output "$TMP/ui.py"
python3 -m py_compile "$TMP/ui.py"

verify(){
  PYTHONPATH="$APP" python3 - "$1" <<'PY'
import importlib.util,sys
spec=importlib.util.spec_from_file_location("wpo_status_v3_check",sys.argv[1])
ui=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
connections=[
    {"id":"awg31","name":"AmneziaWG 3.1","protocol":"awg31","enabled":True},
    {"id":"hyst","name":"Hysteria2","protocol":"hysteria","enabled":True},
    {"id":"vless","name":"VLESS XHTTP","protocol":"vless","enabled":True},
    {"id":"awg20","name":"AmneziaWG 2.0","protocol":"awg20","enabled":True}]
state={"profiles":{"vless":{"enabled":True,"ru_direct":True},
                   "hyst":{"enabled":False}},
       "awg_profiles":{"awg20":{"allowed_ips":["10.0.0.0/8"]}}}
page=ui.routing_ui(connections,state,"/panel-demo","csrf")
assert page.count('data-routing-choice=')==4, 'Не хватает карточек протоколов'
assert page.count('id="routingState"')==1, 'Отсутствует пятый блок статуса'
assert page.count('id="routingStateTitle"')==1, 'Нет подписи статуса'
assert page.count('aria-pressed="true"')==1, 'Должен быть выбран один протокол'
assert page.count('class="routing-protocol-status is-on"')==1, 'Статус не активен'
assert 'data-routing-choice="vless" data-routing-enabled="1"' in page, 'VLESS-статус неверен'
assert 'data-routing-choice="hyst" data-routing-enabled="0"' in page, 'Hysteria-статус неверен'
assert 'data-routing-choice="awg20" data-routing-enabled="1"' in page, 'AWG-статус неверен'
assert 'grid-template-columns:repeat(5,minmax(0,1fr))' in page, 'Карточек не пять в ряду'
assert 'pointer-events:none;user-select:none' in page, 'Статус должен быть некликабельным'
assert 'const enabled=chosen?.dataset.routingEnabled' in page, 'Статус не реагирует на переключение'
assert 'class="routing-status ' not in page, 'Старый статус остался внизу'
assert 'name="operation" value="add-selected"' in page
assert 'name="operation" value="remove-selected"' in page
print('✓ Проверены реальные HTML-карточки и статус выбранного подключения.')
print('✓ Статус не нажимается, маршрутные кнопки и правила сохранены.')
PY
}
verify "$TMP/ui.py"
if cmp -s "$UI" "$TMP/ui.py"; then
    verify "$UI"
    echo '✓ Новый вид уже установлен. Обнови страницу с очисткой кэша.'
    exit 0
fi

BACKUP_DIR=/var/lib/tproxy-panel/routing-status-v3-backups
install -d -m 0700 -o root -g root "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/wpp_ui-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0644 "$TMP/ui.py" "$UI"
rm -f "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$UNIT"
PANEL_PATH="$(systemctl show -p Environment --value "$UNIT" |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n 1)"
if [[ ! "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]]; then
    PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n 1)"
fi
[[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] || exit 4
HEALTHY=0
for i in {1..15}; do
    if systemctl is-active --quiet "$UNIT" &&
       curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
            "http://127.0.0.1:8090$PANEL_PATH/__health" >/dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    sleep 1
done
[[ "$HEALTHY" == 1 ]] || exit 4
verify "$UI"
ROLLBACK=0
echo '✓ Четыре компактные карточки протоколов и пятый статусный блок справа.'
echo '✓ Статус только информационный: зелёная точка при включённой маршрутизации.'
echo '✓ Красная плашка, сохранённые правила и все VPN-подключения не изменены.'
echo "Резервная копия интерфейса: $BACKUP"
echo 'Обнови вкладку «Маршрутизация»: Ctrl+Shift+R (Mac: Cmd+Shift+R).'
