#!/usr/bin/env bash
# WPO: stop RU/EN MutationObserver loop that can freeze dashboard navigation.
# UI-only hotfix; preserve login form, sessions, clients, and VPN state.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на сервере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=761bc4cb4397f21807547921a8f9c762bad96cde
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || {
  echo 'Установленная панель WPO не найдена; ничего не изменено.' >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo 'Служба панели WPO неактивна; ничего не изменено.' >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-nav-unfreeze.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "При ошибке восстановлен прежний интерфейс: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys

current = Path(sys.argv[1]).read_text(encoding="utf-8")
source = Path(sys.argv[2]).read_text(encoding="utf-8")
start = "WPO_I18N_UI_JS = "
end = "\n_WPO_LOGIN_LANGUAGE_BASE = login_ui"
v1 = "# WPO_LOGIN_LANGUAGE_THEME_V1_BEGIN"

def assignment(s):
    if s.count(start) != 1 or s.count(end) != 1 or v1 not in s:
        raise RuntimeError('Неизвестная версия RU/EN WPO; файлы не изменены.')
    a = s.index(start)
    b = s.index(end, a)
    return a, b, s[a:b]

a, b, installed_i18n = assignment(current)
_, _, new_i18n = assignment(source)
if not all(x in new_i18n for x in (
    "if(button.getAttribute('aria-label')!==label)",
    "if(button.getAttribute('aria-pressed')!==pressed)",
    "r.target.closest('.wpo-utility-switches')",
    "MutationObserver(records=>")):
    raise RuntimeError('Новая защита навигации не найдена.')
if not all(x in current for x in (
    'def page_layout(', 'def login_ui(', 'COMMON_JS = ',
    'ASSET_REV = ', 'WPO_LOGIN_DIRECT_POST_SPACING_V4_BEGIN',
    'HTMLFormElement.prototype.submit.call(form)')):
    raise RuntimeError('Неизвестная установленная версия WPO; ничего не изменено.')

patched = current[:a] + new_i18n + current[b:]
if patched.count('def login_ui(path):') < 2 or patched.count('WPO_I18N_UI_JS = ') != 1:
    raise RuntimeError('Ожидаемая структура WPO не подтверждена.')
compile(patched, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(patched, encoding="utf-8")
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TARGET" "$TMP/patched.py"; then
  echo '✓ Исправление RU/EN и навигации уже установлено.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/nav-unfreeze-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-ui-nav-fix.XXXXXXXX.py")"
cp "$TMP/patched.py" "$STAGE"
chown --reference="$TARGET" "$STAGE"
chmod --reference="$TARGET" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$TARGET"
python3 -m py_compile "$TARGET"
systemctl restart "$SERVICE"
READY=0
for i in $(seq 1 18); do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo 'WPO не ответила после перезапуска; выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Устранён повторяющийся цикл локализации RU/EN, блокировавший интерфейс.'
echo '✓ Вкладки Пользователи, Подключения и остальные разделы должны снова открываться.'
echo '✓ Авторизация, VPN, клиенты и правила сервера не менялись.'
echo "✓ Резервная копия интерфейса: $BACKUP"
