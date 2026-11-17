#!/usr/bin/env bash
# WPO login repair: remove iPhone submit interceptor, keep no-autologin, center label.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Запустите через sudo на сервере WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=3491d0fa15d13c7f95a1eecef16e9947881757ab
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || {
  echo "Установленная панель WPO не найдена. Изменений нет." >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo "Служба WPO не активна. Изменений нет." >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-login-repair.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Ошибка проверки. Исходный интерфейс восстановлен: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/updated.py" <<'PY'
from pathlib import Path
import sys

installed = Path(sys.argv[1]).read_text(encoding="utf-8")
source = Path(sys.argv[2]).read_text(encoding="utf-8")
begin = "# WPO_LOGIN_BUTTON_SAFE_V3_BEGIN"
end = "# WPO_LOGIN_BUTTON_SAFE_V3_END"
old_begin = "# WPO_LOGIN_SAFE_SUBMIT_V2_BEGIN"
old_end = "# WPO_LOGIN_SAFE_SUBMIT_V2_END"

if source.count(begin) != 1 or source.count(end) != 1 or source.index(begin) >= source.index(end):
    raise RuntimeError("Неправильная версия исправления входа.")
patch = source[source.index(begin):source.index(end)+len(end)]
if not all(x in patch for x in ("CSS +=", "ASSET_REV = ", "font-size:17px", "justify-content:center")):
    raise RuntimeError("Стиль кнопки входа не полностью загружен.")
if not all(x in installed for x in (
        'def login_ui(path):', 'id="loginForm"', 'id="loginSubmit"',
        'autocomplete="current-password"', '# WPO_LOGIN_LANGUAGE_THEME_V1_BEGIN',
        'def page_layout(', 'COMMON_JS = ')):
    raise RuntimeError("Текущая версия формы WPO не распознана. Изменений нет.")

# Remove the extra submit interception entirely. Safari must use native form POST.
if installed.count(old_begin) != installed.count(old_end) or installed.count(old_begin) > 1:
    raise RuntimeError("Маркеры старого обработчика входа повреждены.")
if old_begin in installed:
    a = installed.index(old_begin)
    b = installed.index(old_end,a) + len(old_end)
    installed = installed[:a].rstrip() + '\n\n' + installed[b:].lstrip('\n')

old_disabled = "submit.disabled=true;submit.classList.add('is-busy')"
new_busy = "submit.setAttribute('aria-busy','true');submit.classList.add('is-busy')"
if installed.count(old_disabled) == 1:
    installed = installed.replace(old_disabled, new_busy, 1)
elif installed.count(old_disabled) != 0 or installed.count(new_busy) != 1:
    raise RuntimeError("Состояние отправки формы неизвестно. Изменений нет.")

old_button = '<button class="primary login-submit" id="loginSubmit">'
new_button = '<button type="submit" class="primary login-submit" id="loginSubmit">'
if installed.count(old_button) == 1:
    installed = installed.replace(old_button,new_button,1)
elif installed.count(old_button) != 0 or installed.count(new_button) != 1:
    raise RuntimeError("Кнопка входа не соответствует ожидаемой версии.")

if installed.count(begin) != installed.count(end) or installed.count(begin) > 1:
    raise RuntimeError("Повторное оформление входа повреждено.")
if begin in installed:
    a = installed.index(begin)
    b = installed.index(end,a) + len(end)
    installed = installed[:a] + patch + installed[b:]
else:
    installed = installed.rstrip() + '\n\n' + patch + '\n'

if old_begin in installed or old_end in installed or "autoTimer=" in installed:
    raise RuntimeError("Не удалось убрать автоматический или блокирующий обработчик входа.")
if installed.count(new_button) != 1 or installed.count(new_busy) != 1:
    raise RuntimeError("Отправка формы входа не восстановлена.")
compile(installed, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(installed, encoding='utf-8')
PY
python3 -m py_compile "$TMP/updated.py"
if cmp -s "$TARGET" "$TMP/updated.py"; then
  echo "✓ Исправленный вход WPO уже установлен."
  exit 0
fi
BACKUP="/var/backups/web-panel-online/login-repair-v3-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-login-repair.XXXXXXXX.py")"
cp "$TMP/updated.py" "$STAGE"
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
(( READY )) || { echo "Панель не ответила после обновления; выполняется откат." >&2; exit 4; }
CHANGED=0
echo "✓ Восстановлена штатная кнопка входа — отправка только по нажатию/Enter."
echo "✓ Автологин по таймеру по-прежнему выключен."
echo "✓ Надпись «Вход» 17 px по центру кнопки, стрелка справа."
echo "✓ Серверная авторизация, пользователи, VPN и main не менялись."
echo "✓ Резервная копия: $BACKUP"
