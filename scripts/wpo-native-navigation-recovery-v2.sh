#!/usr/bin/env bash
# WPO emergency UI-only navigation recovery.
# Preserve the working login, cookies, client data and VPN settings.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Запустите через sudo на сервере WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=4b0bc22f2e9621bd56f7e69e767e85fa22c44cb9
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || { echo "Файл панели WPO не найден. Изменений нет." >&2; exit 2; }
systemctl is-active --quiet "$SERVICE" || { echo "Служба WPO неактивна. Изменений нет." >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-native-nav.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Проверка не пройдена: прежний интерфейс восстановлен из $BACKUP" >&2
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

# Only the old tab navigation controller is removed; native anchors remain.
nav_old_start = "let wppNavigationTimer=0;"
nav_old_end = "window.addEventListener('pageshow',wppFinishNavigation);"
nav_new = ("// Use native links and normal POSTs. No navigation overlay or disabled page.\n"
           "document.documentElement.classList.remove('wpp-navigating');\n"
           "document.querySelectorAll('.topnav a').forEach(link=>link.classList.remove('is-pending'));")
if source.count(nav_new) != 1:
    raise RuntimeError("В исходной версии WPO нет исправленной навигации.")
if installed.count(nav_old_start) == 1 and installed.count(nav_old_end) == 1:
    a = installed.index(nav_old_start)
    b = installed.index(nav_old_end, a) + len(nav_old_end)
    if b - a > 3000:
        raise RuntimeError("Старая навигация WPO не соответствует ожидаемой версии.")
    installed = installed[:a] + nav_new + installed[b:]
elif installed.count(nav_new) != 1:
    raise RuntimeError("Не удалось найти блок навигации WPO. Изменений нет.")

# Remove live whole-page translation observer. RU/EN still translates at page
# load and on actual RU/EN button click; no continuous DOM scanning.
left = "WPO_I18N_UI_JS = "
right = "\n_WPO_LOGIN_LANGUAGE_BASE = login_ui"
def extract_js(s):
    if s.count(left) != 1 or s.count(right) != 1:
        raise RuntimeError("Не распознан установленный переключатель RU/EN.")
    a = s.index(left)
    b = s.index(right, a)
    return a, b, s[a:b]

a, b, _ = extract_js(installed)
_, _, replacement = extract_js(source)
if ("// Translations run at page load and when RU/EN is clicked" not in replacement
        or "MutationObserver(records=>" in replacement
        or "window.wpoSetLanguage=setLanguage;" not in replacement):
    raise RuntimeError("Неверный вариант скрипта RU/EN.")
installed = installed[:a] + replacement + installed[b:]

begin = "# WPO_NAV_NATIVE_RECOVERY_V2_BEGIN"
end = "# WPO_NAV_NATIVE_RECOVERY_V2_END"
if source.count(begin) != 1 or source.count(end) != 1 or source.index(begin) >= source.index(end):
    raise RuntimeError("В исходной версии нет аварийного исправления навигации.")
patch = source[source.index(begin):source.index(end)+len(end)]
if not all(x in patch for x in ("CSS +=", "WPO_NATIVE_NAV_JS", "_WPO_NATIVE_NAV_BASE = page_layout", "ASSET_REV = ")):
    raise RuntimeError("Скрипт навигации неполный.")
if installed.count(begin) != installed.count(end) or installed.count(begin) > 1:
    raise RuntimeError("Некорректные маркеры предыдущей установки.")
if begin in installed:
    a = installed.index(begin)
    b = installed.index(end, a)+len(end)
    installed = installed[:a] + patch + installed[b:]
else:
    installed = installed.rstrip() + "\n\n" + patch + "\n"

# Protect the working login from accidental changes.
if not all(x in installed for x in (
        'HTMLFormElement.prototype.submit.call(form)',
        'WPO_LOGIN_DIRECT_POST_SPACING_V4_BEGIN',
        '<button type="button" class="primary login-submit"',
        'def page_layout(', 'def login_ui(')):
    raise RuntimeError("Текущий рабочий вход WPO не распознан. Изменений нет.")
if "let wppNavigationTimer=0;" in installed or "MutationObserver(records=>" in extract_js(installed)[2]:
    raise RuntimeError("Неполное исправление: осталась старая навигация или observer.")
compile(installed, sys.argv[3], "exec")
Path(sys.argv[3]).write_text(installed, encoding="utf-8")
PY
python3 -m py_compile "$TMP/updated.py"
if cmp -s "$TMP/updated.py" "$TARGET"; then
  echo "✓ WPO уже использует прямую навигацию."
  exit 0
fi
BACKUP="/var/backups/web-panel-online/native-nav-v2-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-native-nav.XXXXXXXX.py")"
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
(( READY )) || { echo "WPO не ответила после обновления; выполняется откат." >&2; exit 4; }
CHANGED=0
echo "✓ Вкладки WPO переведены на прямые переходы по ссылкам."
echo "✓ Убраны блокировка содержимого и постоянное наблюдение RU/EN за DOM."
echo "✓ Рабочая кнопка входа, настройки VPN, сессии и пользователи не изменялись."
echo "✓ Резервная копия: $BACKUP"
