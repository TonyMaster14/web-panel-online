#!/usr/bin/env bash
# Test-only WPO routing visual fix: saved blue/green markers, equal red border.
# No VPN config, routing state, subscription, Caddy, Xray or users changes.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите sudo на тестовой основной панели WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
UNIT=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Нужен контроллер WPO, а не дополнительная нода.' >&2; exit 2;
}
exec 9>/run/lock/wpo-routing-saved-v2.lock
flock -n 9 || { echo 'Другое обновление интерфейса уже выполняется.' >&2; exit 2; }
TEMP="$(mktemp -d /tmp/wpo-routing-v2.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish(){
  code=$?
  trap - EXIT
  if [[ "$CHANGED" == 1 ]]; then
      echo 'Проверка панели не пройдена — возвращаю прежний интерфейс.' >&2
      cp -a "$BACKUP" "$UI" || true
      rm -f "$APP"/__pycache__/wpp_ui.*.pyc
      systemctl restart "$UNIT" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TEMP"
  exit "$code"
}
trap finish EXIT
trap 'exit 130' INT TERM
REV=39551e697629bb2308ab0cc6c4a2c26e6cbaacbe
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
    --connect-timeout 12 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/wpo-routing-persisted-rules-v2-patch.py" \
    -o "$TEMP/patch.py"
python3 -m py_compile "$TEMP/patch.py"
python3 "$TEMP/patch.py" --input "$UI" --output "$TEMP/new.py"
python3 -m py_compile "$TEMP/new.py"
verify(){
  PYTHONPATH="$APP" python3 - "$1" <<'PY'
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("wpo_routing_v2_check",sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
conns=[{"id":"vless","name":"VLESS XHTTP","protocol":"vless","enabled":True},
       {"id":"hyst","name":"Hysteria2","protocol":"hysteria","enabled":True}]
state={"profiles":{"vless":{"enabled":True,"ru_direct":True,"youtube_proxy":True}}}
html=module.routing_ui(conns,state,"/panel-test","csrf-test")
assert html.count('class="routing-toggle is-active"')==2, "Saved flags are not active"
assert 'class="routing-toggle"><input type="checkbox" name="select_private_direct"' in html
assert "wpo-routing-persisted-rules-v2" in html
assert ".routing-form .routing-switches label.routing-toggle.is-active .routing-rule-dot i" in html
assert ".routing-form .routing-hero{background:var(--surface)}" in html
assert "box-shadow:none" in html
assert 'name="operation" value="add-selected"' in html
assert 'name="operation" value="remove-selected"' in html
print("✓ Проверены настоящие сохранённые правила: два активны, остальные неактивны.")
print("✓ Проверены ровная красная рамка, тёмный фон и сохранение действий.")
PY
}
verify "$TEMP/new.py"
if cmp -s "$UI" "$TEMP/new.py"; then
  echo '✓ Исправление уже установлено; обнови страницу без кэша.'
  exit 0
fi
BACKUP_DIR=/var/lib/tproxy-panel/routing-ui-v2-backups
install -d -m 0700 -o root -g root "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/wpp_ui-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
CHANGED=1
install -o root -g root -m 0644 "$TEMP/new.py" "$UI"
rm -f "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$UNIT"
ROUTE="$(systemctl show -p Environment --value "$UNIT" |
   tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
if [[ ! "$ROUTE" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]]; then
  ROUTE="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
fi
[[ "$ROUTE" =~ ^/panel-[A-Za-z0-9_-]{3,80}$ ]] || exit 4
READY=0
for try in {1..15}; do
   if systemctl is-active --quiet "$UNIT" &&
      curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
       "http://127.0.0.1:8090$ROUTE/__health" >/dev/null 2>&1; then
       READY=1; break
   fi
   sleep 1
done
[[ "$READY" == 1 ]] || exit 4
verify "$UI"
CHANGED=0
echo '✓ Готово: сохранённые правила остаются синими с зелёными точками.'
echo '✓ У предупреждения ровная красная рамка и тёмный фон под ним.'
echo '✓ Состояние маршрутизации, ключи, пользователи и VPN не менялись.'
echo "Резервная копия: $BACKUP"
echo 'Открой «Маршрутизация» и сделай Ctrl+Shift+R (Mac: Cmd+Shift+R).'
