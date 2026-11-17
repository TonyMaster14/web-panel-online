#!/usr/bin/env bash
# WPO login UI: avoid implicit iOS submit, compact centered button, RU/EN + theme pills.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Запустите через sudo на основном сервере WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=28f99aa326e6896324cf551ed2a6da2d14baa3d3
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && -s "$APP/panel.py" && ! -L "$TARGET" ]] || {
 echo "Интерфейс WPO не найден. Изменений нет." >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || { echo "Служба WPO не запущена. Изменений нет." >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-login-lang.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "При ошибке восстановлен прежний UI: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys

target = Path(sys.argv[1]).read_text(encoding='utf-8')
source = Path(sys.argv[2]).read_text(encoding='utf-8')
def check_one(value, needle, description):
    if value.count(needle) != 1:
        raise RuntimeError(f"Нельзя безопасно изменить {description}: найдено {value.count(needle)} вместо 1.")
def slice_section(text, start, end):
    a = text.find(start)
    b = text.find(end, a+len(start))
    if a < 0 or b < 0:
        raise RuntimeError("Несовместимый интерфейс WPO; ничего не изменено.")
    return text[a:b]

for marker in ("CSS = ", "COMMON_JS = ", "def theme_button():",
               "def page_layout(", "def login_ui(path):", "id=\"loginForm\""):
    if marker not in target:
        raise RuntimeError(f"Неизвестная версия WPO; отсутствует {marker}")

# Replace ONLY the reusable theme button and the standalone sign-in page.
# All authenticated screens, routing, nodes and accounts remain in place.
theme_start, theme_end = "def theme_button():", "\n\ndef page_layout("
if not all(x in source for x in ("data-wpo-lang", "wpo-theme-pill", "wpo-theme-caption")):
    raise RuntimeError("В исходном GitHub UI отсутствуют переключатели языка/темы.")
old_theme = slice_section(target, theme_start, theme_end)
new_theme = slice_section(source, theme_start, theme_end)
target = target.replace(old_theme, new_theme, 1)

login_start, login_end = "def login_ui(path):", "\n\ndef hidden("
old_login = slice_section(target, login_start, login_end)
new_login = slice_section(source, login_start, login_end)
if 'id="loginForm"' not in new_login or 'id="loginSubmit"' not in new_login or '<b>Вход</b>' not in new_login:
    raise RuntimeError("Исходная страница входа WPO не соответствует исправленной версии.")
if old_login.count('id="loginForm"') != 1:
    raise RuntimeError("Локальная форма входа не распознана; файлы не менялись.")
target = target.replace(old_login, new_login, 1)

# Existing global theme handler must update its hidden caption, not
# overwrite the visible small 'Тема' label in the 90px pill.
theme_line = "document.querySelectorAll('[data-theme-toggle]').forEach(b=>"
src_line = next((line for line in source.splitlines() if line.startswith(theme_line)), None)
local_line = next((line for line in target.splitlines() if line.startswith(theme_line)), None)
if not src_line or not local_line or src_line.count(".theme-label") < 2:
    raise RuntimeError("Обработчик переключения темы не распознан.")
check_one(target, local_line, "переключатель темы")
target = target.replace(local_line, src_line, 1)

# Install the complete CSS + RU/EN translations on ALL pages,
# then the explicit-login-only guard. Preserve previous UI source patches.
for start, end in (
    ('# WPO_LOGIN_LANGUAGE_THEME_V1_BEGIN', '# WPO_LOGIN_LANGUAGE_THEME_V1_END'),
    ('# WPO_LOGIN_SAFE_SUBMIT_V2_BEGIN', '# WPO_LOGIN_SAFE_SUBMIT_V2_END')
):
    if source.count(start) != 1 or source.count(end) != 1:
        raise RuntimeError("Неполная версия патча языка и авторизации.")
    src_patch = slice_section(source, start, end) + end
    if target.count(start) != target.count(end) or target.count(start) > 1:
        raise RuntimeError(f"На сервере повреждены маркеры патча {start}.")
    if start in target:
        first = target.index(start)
        last = target.index(end, first) + len(end)
        target = target[:first] + src_patch + target[last:]
    else:
        target = target.rstrip() + "\n\n" + src_patch + "\n"

# Validate that only one login form and one set of global controls is emitted
# and that the safety handler is always appended after the localization layer.
if not (target.index('# WPO_LOGIN_LANGUAGE_THEME_V1_BEGIN')
        < target.index('# WPO_LOGIN_SAFE_SUBMIT_V2_BEGIN')):
    raise RuntimeError("Неверный порядок UI-патчей.")
if ("event.preventDefault();event.stopImmediatePropagation()" not in target or
        "WPO_LOGIN_SAFE_SUBMIT_V2_JS" not in target):
    raise RuntimeError("Защита формы входа не установлена.")
compile(target, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(target, encoding='utf-8')
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TMP/patched.py" "$TARGET"; then
  echo "✓ Экран входа, RU/EN и защита от автоматической отправки уже установлены."
  exit 0
fi
BACKUP="/var/backups/web-panel-online/login-language-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-login-lang.XXXXXXXX.py")"
cp "$TMP/patched.py" "$STAGE"
chown --reference="$TARGET" "$STAGE"
chmod --reference="$TARGET" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$TARGET"
python3 -m py_compile "$TARGET"
systemctl restart "$SERVICE"
READY=0
for i in $(seq 1 15); do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo "WPO не ответила после изменения UI — выполняется откат." >&2; exit 4; }
CHANGED=0
echo "✓ Вход на iPhone: форма отправляется только после нажатия кнопки «Вход»."
echo "✓ Кнопка «Вход» компактная, со стрелкой и по центру карточки."
echo "✓ RU/EN и светлая/тёмная тема в одинаковых переключателях в правом верхнем углу."
echo "✓ Язык сохраняется на устройстве и применяется к страницам панели."
echo "✓ Изменены только функции и стили интерфейса; пользователи, VPN и авторизация сервера не изменялись."
echo "✓ Резервная копия: $BACKUP"
