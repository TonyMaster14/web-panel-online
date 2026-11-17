#!/usr/bin/env bash
# Apply only the WPO admin interface dropdown styling.
# No node or VPN configuration is touched.
set -Eeuo pipefail
umask 077
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=752f6fc241dc79e4064ef62155a5c9d8eda1dd8f
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ "$EUID" -eq 0 ]] || { echo "Run with sudo" >&2; exit 1; }
[[ -f "$TARGET" && -f "$APP/panel.py" ]] || { echo "Not a WPO controller installation: $APP" >&2; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "WPO systemd service absent" >&2; exit 1; }
TMP="$(mktemp "$APP/.wpo-ui-XXXXXX.py")"
BACKUP="$(mktemp "$APP/.wpo-ui-before-XXXXXX.py")"
MODE="$(stat -c '%a' "$TARGET")"
OWNER="$(stat -c '%u' "$TARGET")"
GROUP="$(stat -c '%g' "$TARGET")"
COMMITTED=0
cleanup(){
  rc=$?
  if (( rc != 0 && COMMITTED == 1 )); then
    echo "Ошибка! Возвращаю предыдущий интерфейс..." >&2
    cp -p "$BACKUP" "$TARGET" || true
    systemctl restart "$SERVICE" || true
  fi
  rm -f "$TMP"
  if (( rc == 0 )); then
    echo "Предыдущая версия UI: $BACKUP"
  else
    rm -f "$BACKUP"
  fi
}
trap cleanup EXIT
cp -p "$TARGET" "$BACKUP"
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 60 "$URL" -o "$TMP"
python3 - "$TMP" <<'PY'
import ast,sys
source=open(sys.argv[1],encoding="utf-8").read()
ast.parse(source)
assert "# wpo-reality-select-style-v1" in source
assert ":is(dialog select:not([multiple]),.clients-toolbar select,.update-control select)" in source
print("Стили селекторов REALITY проверены")
PY
chown "$OWNER:$GROUP" "$TMP"
chmod "$MODE" "$TMP"
mv -f "$TMP" "$TARGET"
COMMITTED=1
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || { echo "WPO did not start" >&2; exit 1; }
echo "Готово: выпадающие списки «Тип подключения», «Пользователи», «Шаблон сайта» и «Обновления» обновлены."
echo "Серверные конфигурации, подписки и ноды не изменены."
