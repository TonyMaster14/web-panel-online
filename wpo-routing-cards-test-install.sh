#!/usr/bin/env bash
# Test branch only: visual routing cards. Never modifies routing state, keys,
# subscription profiles or VPN services. Backs up and verifies real HTML.
set -Eeuo pipefail
umask 077

[[ "$EUID" -eq 0 ]] || { echo 'Запусти через sudo на тестовом контроллере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
   echo 'Нужен контроллер WPO с установленной панелью, не дополнительная нода.' >&2
   exit 2
}
systemctl cat "$SERVICE" >/dev/null
exec 9>/run/lock/wpo-routing-cards-ui.lock
flock -n 9 || { echo 'Уже выполняется обновление интерфейса WPO.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-routing-cards.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup(){
    code=$?
    trap - EXIT
    if [[ "$ROLLBACK" == 1 ]]; then
        echo 'Проверка интерфейса не пройдена. Восстанавливаю предыдущую версию.' >&2
        cp -a "$BACKUP" "$UI" || true
        rm -f "$APP"/__pycache__/wpp_ui.*.pyc
        systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$WORK"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

REF=93e738785a70f41196ef5930bc067caa58787494
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
  --connect-timeout 12 --max-time 90 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/wpo-routing-cards-ui-patch.py" \
  -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
python3 "$WORK/patch.py" --input "$UI" --output "$WORK/new.py"
python3 -m py_compile "$WORK/new.py"

verify(){
    PYTHONPATH="$APP" python3 - "$1" <<'PY'
import importlib.util
import pathlib
import sys
file=pathlib.Path(sys.argv[1])
spec=importlib.util.spec_from_file_location("wpo_routing_cards_check",file)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
items=[
 {"id":"wg31","protocol":"awg31","name":"Amnezia 3.1","enabled":True},
 {"id":"hyst","protocol":"hysteria","name":"Hysteria","enabled":True},
 {"id":"vless","protocol":"vless","name":"VLESS","enabled":True},
 {"id":"wg20","protocol":"awg20","name":"Amnezia 2.0","enabled":True}
]
page=module.routing_ui(items,{},"/panel-test","csrf")
expected=("vless","hyst","wg20","wg31")
if page.count('data-routing-choice=')!=4 or page.count('aria-pressed="true"')!=1:
    raise SystemExit('Не удалось подтвердить четыре карточки выбора протокола.')
if any(f'data-routing-choice="{key}"' not in page for key in expected):
    raise SystemExit('Не обнаружен один из четырёх протоколов.')
if not all(f'name="select_{key}"' in page for key in
           ("ru_direct","private_direct","youtube_proxy","push_proxy",
            "captive_direct","block_bittorrent","split_dns")):
    raise SystemExit('Неполный список правил маршрутизации.')
if page.count('class="routing-rule-dot"')!=14:
    raise SystemExit('Отсутствуют индикаторы для выбора правил.')
if 'Подключение для маршрутизации<select' in page:
    raise SystemExit('Старый выпадающий список ещё виден.')
if "select.dispatchEvent(new Event('change'" not in page:
    raise SystemExit('Переключение карточек не подключено.')
if 'name="operation" value="add-selected"' not in page or \
   'name="operation" value="remove-selected"' not in page:
    raise SystemExit('Кнопки маршрутизации потеряны.')
print('✓ Проверены настоящие HTML-карточки, переключение и семь правил.')
PY
}
verify "$WORK/new.py"
if cmp -s "$UI" "$WORK/new.py"; then
    echo '✓ Новый стиль маршрутизации уже установлен. Обнови страницу с очисткой кэша.'
    exit 0
fi

BACKUPS=/var/lib/tproxy-panel/routing-cards-ui-backups
install -d -m 0700 -o root -g root "$BACKUPS"
BACKUP="$BACKUPS/wpp_ui-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0644 "$WORK/new.py" "$UI"
rm -f "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$SERVICE"
PANEL_PATH="$(systemctl show -p Environment --value "$SERVICE" |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n 1)"
if [[ ! "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]]; then
    PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n 1)"
fi
[[ "$PANEL_PATH" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]] || exit 4
READY=0
for attempt in {1..15}; do
    if systemctl is-active --quiet "$SERVICE" &&
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
echo '✓ Маршрутизация обновлена: четыре протокола, один активен.'
echo '✓ Правила выбираются независимо: синее выделение, зелёная точка.'
echo '✓ Красное предупреждение закруглено; действия сохранили прежнюю логику.'
echo '✓ Ноды, пользователи, подписки и работающие VPN-службы не изменены.'
echo "Резервная копия: $BACKUP"
echo 'Открой «Маршрутизация» и обнови страницу: Ctrl+Shift+R (Mac: Cmd+Shift+R).'
