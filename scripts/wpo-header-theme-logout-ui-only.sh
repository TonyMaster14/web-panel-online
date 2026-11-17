#!/usr/bin/env bash
# WPO UI-only: compact theme icon by GitHub and make logout link reliably clickable.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на основном сервере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=e96fd0698d27c058033fb70abe2976eaa0d58627
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && -s "$APP/panel.py" && ! -L "$TARGET" ]] || {
  echo 'Файл панели WPO не найден. Изменений нет.' >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo 'Служба WPO не запущена. Изменений нет.' >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-header-logout.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Проверка не прошла. Исходный UI восстановлен: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/updated.py" <<'PY'
from pathlib import Path
import sys

installed = Path(sys.argv[1]).read_text(encoding='utf-8')
source = Path(sys.argv[2]).read_text(encoding='utf-8')
begin = '# WPO_HEADER_COMPACT_THEME_LOGOUT_V1_BEGIN'
end = '# WPO_HEADER_COMPACT_THEME_LOGOUT_V1_END'

if source.count(begin) != 1 or source.count(end) != 1 or source.index(begin) >= source.index(end):
    raise RuntimeError('Исходный патч верхней панели WPO повреждён.')
patch = source[source.index(begin):source.index(end) + len(end)]
if not all(x in patch for x in (
    'CSS +=', 'WPO_HEADER_LOGOUT_JS', '_WPO_HEADER_LOGOUT_BASE = page_layout',
    'window.location.replace(link.href)', 'ASSET_REV = ')):
    raise RuntimeError('Патч кнопки выхода неполный.')
if not all(k in installed for k in (
    'def theme_button():', 'def page_layout(', 'def login_ui(',
    '# WPO_LOGIN_LANGUAGE_THEME_V1_BEGIN', '# WPO_LOGIN_SAFE_SUBMIT_V2_BEGIN',
    'WPO_I18N_UI_JS', 'ASSET_REV = ')):
    raise RuntimeError('На сервере не установлена ожидаемая версия WPO с RU/EN. Изменений нет.')

caption = '<span class="wpo-theme-caption">Тема</span>'
if installed.count(caption) == 1:
    installed = installed.replace(caption, '', 1)
elif installed.count(caption) != 0:
    raise RuntimeError('Неизвестная разметка переключателя темы.')

old_link = '<a class="logout" href="{esc(path)}/logout" aria-label="Выйти">'
new_link = '<a class="logout" href="{esc(path)}/logout" aria-label="Выйти" title="Выйти" data-wpo-logout="1">'
if installed.count(old_link) == 1:
    installed = installed.replace(old_link, new_link, 1)
elif installed.count(old_link) != 0 or installed.count(new_link) != 1:
    raise RuntimeError('Кнопка выхода WPO не соответствует ожидаемой версии. Изменений нет.')

if installed.count(begin) != installed.count(end) or installed.count(begin) > 1:
    raise RuntimeError('Найдены некорректные маркеры предыдущего UI-патча.')
if begin in installed:
    a = installed.index(begin)
    b = installed.index(end, a) + len(end)
    installed = installed[:a] + patch + installed[b:]
else:
    installed = installed.rstrip() + '\n\n' + patch + '\n'

if installed.count('data-wpo-logout="1"') != 1:
    raise RuntimeError('Кнопка выхода потеряна при применении патча.')
if installed.count('_WPO_HEADER_LOGOUT_BASE = page_layout') != 1:
    raise RuntimeError('Обработчик выхода не подключён.')
compile(installed, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(installed, encoding='utf-8')
PY
python3 -m py_compile "$TMP/updated.py"
if cmp -s "$TMP/updated.py" "$TARGET"; then
  echo '✓ Верхние переключатели и кнопка выхода WPO уже обновлены.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/header-logout-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-header-logout.XXXXXXXX.py")"
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
(( READY )) || { echo 'WPO не ответила после изменения UI. Выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Убрана надпись «Тема», осталась круглая кнопка с солнцем или луной.'
echo '✓ Переключатели RU/EN и темы выровнены рядом с GitHub и кнопкой выхода.'
echo '✓ Исправлены область нажатия и переход по существующей ссылке /logout.'
echo '✓ Серверные правила сессий и VPN не менялись.'
echo "✓ Резервная копия: $BACKUP"
