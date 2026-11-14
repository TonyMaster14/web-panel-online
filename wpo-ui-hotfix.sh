#!/usr/bin/env bash
# WPO test-branch focused UI refresh. No node, subscriber or VPN changes.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo.' >&2; exit 1; }
APP=/opt/tproxy-panel
MODULE="$APP/wpo_user_v28.py"
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s "$MODULE" ]] || {
  echo 'Основная WPO с новым меню пользователей не обнаружена на этом VPS.' >&2
  exit 2
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Обновление WPO уже выполняется.' >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-ui-hotfix.XXXXXXXX)"
BACKUP="$TMP/original-wpo-user-v28.py"
SAVED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && SAVED == 1 )); then
    echo 'Проверка не пройдена — возвращаю прежнюю форму.' >&2
    cp -a "$BACKUP" "$MODULE" || true
    rm -f "$APP"/__pycache__/wpo_user_v28.*.pyc
    systemctl restart "$SERVICE" || true
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/test/wpo-smooth-progress-v1/wpo_user_v28.py"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 15 --max-time 90 "$URL" -o "$TMP/new.py"
python3 -m py_compile "$TMP/new.py"
python3 - "$TMP/new.py" "$UI" <<'PY_VERIFY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text(encoding="utf-8")
ui=Path(sys.argv[2]).read_text(encoding="utf-8")
required=[
    'placeholder="Например, Home VPN"',
    "toggle.addEventListener('click',event=>{",
    "if(popover.hidden)openCalendar();",
    "else closeCalendar();",
    "document.getElementById('wpoV28Until2099')",
    "const calendar=document.getElementById('wpoV28Calendar');",
    'id="wpoV28DayGrid"',
]
for token in required:
    if token not in src:
        raise SystemExit("Сборка не содержит новое меню: "+token)
if 'placeholder="Например, Анна · iPhone"' in src:
    raise SystemExit("Загружена устаревшая форма")
if 'wpo_user_v28.form(' not in ui or 'import wpo_user_v28' not in ui:
    raise SystemExit("Панель не подключена к новому модулю пользователей")
print("✓ Проверена новая форма: Home VPN и закрытие календаря")
PY_VERIFY
cp -a "$MODULE" "$BACKUP"
SAVED=1
install -o root -g root -m 0644 "$TMP/new.py" "$MODULE"
rm -f "$APP"/__pycache__/wpo_user_v28.*.pyc
PYTHONPATH="$APP" python3 - <<'PY_TEST'
import wpo_user_v28
html=wpo_user_v28.form('/panel-check','test-csrf',[
    {'id':'vless-primary','protocol':'vless','enabled':True}
],[],{'country_code':'NL','country_name':'Нидерланды'})
assert 'placeholder="Например, Home VPN"' in html
assert 'Например, Анна · iPhone' not in html
assert "toggle.addEventListener('click',event=>{" in html
assert "if(popover.hidden)openCalendar();" in html
assert 'data-wpo-2099="1"' in html
assert 'id="wpoV28Hour"' not in html
print('✓ Установленный модуль выдаёт Home VPN')
PY_TEST
systemctl restart "$SERVICE"
PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-z0-9-]{3,64}$ ]] || {
  echo 'Не удалось определить путь панели WPO.' >&2
  exit 3
}
OK=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet "$SERVICE" &&
     curl -4fsS --max-time 3 "http://127.0.0.1:8090${PANEL_PATH}/__health" |
       grep -qx 'OK'; then
    OK=1
    break
  fi
  sleep 1
done
(( OK == 1 )) || { echo 'Панель не ответила после перезапуска.' >&2; exit 3; }
SAVED=0
echo '✓ WPO перезапущена, новая форма установлена и проверена.'
echo '✓ Подсказка: Например, Home VPN'
echo '✓ Календарь закрывается по иконке, выбору дня, быстрому сроку и Esc.'
echo 'Закройте старую вкладку панели, откройте её заново и нажмите «Новый пользователь».'
