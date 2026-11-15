#!/usr/bin/env bash
# TEST BRANCH: visually modernize routing action buttons.
# UI-only: leaves user profiles, route state, subscriptions and VPN untouched.
set -Eeuo pipefail
umask 077

[[ "$EUID" -eq 0 ]] || { echo 'Запусти через sudo на тестовой WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
UNIT=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
    ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Нужен контроллер WPO, не дополнительная VPN-нода. Ничего не изменено.' >&2
    exit 2
}

exec 9>/run/lock/wpo-routing-actions-v5.lock
flock -n 9 || { echo 'Другое обновление интерфейса WPO уже запущено.' >&2; exit 2; }

WORK="$(mktemp -d /tmp/wpo-routing-actions-v5.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup(){
    code=$?
    trap - EXIT
    if [[ "$ROLLBACK" == 1 ]]; then
        echo 'Проверка не пройдена. Восстанавливаю прежний интерфейс.' >&2
        cp -a "$BACKUP" "$UI" || true
        rm -f "$APP"/__pycache__/wpp_ui.*.pyc
        systemctl restart "$UNIT" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$WORK"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

REF=ce65511a630ec85b555a0ef7349fc85bdf8509fe
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
    --connect-timeout 12 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/wpo-routing-actions-buttons-v5-patch.py" \
    -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
python3 "$WORK/patch.py" --input "$UI" --output "$WORK/ui.py"
python3 -m py_compile "$WORK/ui.py"

verify(){
    PYTHONPATH="$APP" python3 - "$1" <<'PY'
import importlib.util,sys
spec=importlib.util.spec_from_file_location("wpo_action_buttons_v5",sys.argv[1])
ui=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
connections=[
    {"id":"vless","name":"VLESS XHTTP","protocol":"vless","enabled":True},
    {"id":"hyst","name":"Hysteria2","protocol":"hysteria","enabled":True},
]
state={"profiles":{"vless":{"enabled":True,"ru_direct":True}}}
html=ui.routing_ui(connections,state,"/panel-demo","csrf-test")
assert html.count('class="routing-actions-primary"')==2
assert html.count('class="routing-actions-secondary"')==2
assert html.count('name="operation" value="add-selected"')==2
assert html.count('name="operation" value="remove-selected"')==2
assert 'name="select_ru_direct" value="1"' in html
assert "button.value='remove-all'" in html
assert 'background:#2563eb' in html
assert 'background:#c9364f' in html
assert 'transform:translateY(-2px)' in html
assert 'grid-template-columns:minmax(0,1.5fr) minmax(300px,.65fr)' in html
print('✓ Проверены синие/красные кнопки, эффект приподнимания и выравнивание.')
print('✓ Действия добавления/удаления, включая полную очистку, сохранены.')
PY
}
verify "$WORK/ui.py"

if cmp -s "$WORK/ui.py" "$UI"; then
    echo '✓ Кнопки уже обновлены. Обнови страницу маршрутизации без кэша.'
    exit 0
fi

BACKUP_DIR=/var/lib/tproxy-panel/routing-actions-v5-backups
install -d -o root -g root -m 0700 "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/wpp_ui-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0644 "$WORK/ui.py" "$UI"
rm -f "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$UNIT"

PANEL_PATH="$(systemctl show -p Environment --value "$UNIT" |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n 1)"
if [[ ! "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]]; then
    PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' \
        /etc/systemd/system/tproxy-panel.service | head -n 1)"
fi
[[ "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]] || exit 4
READY=0
for attempt in {1..15}; do
    if systemctl is-active --quiet "$UNIT" &&
       curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
            "http://127.0.0.1:8090$PANEL_PATH/__health" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done
[[ "$READY" == 1 ]] || exit 4
verify "$UI"
ROLLBACK=0

echo '✓ Готово: крупная синяя «Добавить» и красная «Убрать» с подъёмом.'
echo '✓ Кнопки выровнены по колонкам правил и собственных исключений.'
echo '✓ Пользователи, маршрутизация, Happ, Xray и VPN не изменены.'
echo "Резервная копия: $BACKUP"
echo 'Открой «Маршрутизация» и обнови страницу: Ctrl+Shift+R / Cmd+Shift+R.'
