#!/usr/bin/env bash
# WPO: UI-only popup select update with rollback, preserves server and client configuration.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Запустите через sudo на основном сервере WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=754c90a4661d1549a95fbe544865ff2263509295
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || { echo "Панель WPO не найдена. Ничего не изменено." >&2; exit 2; }
systemctl is-active --quiet "$SERVICE" || { echo "Служба WPO не запущена. Ничего не изменено." >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-select-popup-v2.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Ошибка проверки — выполнен откат интерфейса. Копия: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap finish EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys

target = Path(sys.argv[1]).read_text(encoding='utf-8')
source = Path(sys.argv[2]).read_text(encoding='utf-8')
begin = '# WPO_SELECT_POPOVER_V2_BEGIN'
end = '# WPO_SELECT_POPOVER_V2_END'
old_begin = '# WPO_CUSTOM_SELECT_POPOVER_BEGIN'
old_end = '# WPO_CUSTOM_SELECT_POPOVER_END'

if source.count(begin) != 1 or source.count(end) != 1:
    raise RuntimeError('Исходный UI-патч v2 отсутствует либо повреждён.')
patch = source[source.index(begin):source.index(end) + len(end)]
if ('WPO_SELECT_POPOVER_V2_JS' not in patch or 'CSS +=' not in patch or
        '_WPO_OLD_PAGE_LAYOUT = page_layout' not in patch or
        'return markup.replace' not in patch or
        'ASSET_REV = ' not in patch):
    raise RuntimeError('UI-патч v2 неполный. Изменения остановлены.')
if not all(fragment in target for fragment in ('CSS = ', 'COMMON_JS = ', 'def page_layout(', 'ASSET_REV = ')):
    raise RuntimeError('Неизвестная версия WPO. Ничего не изменено.')

# Remove any previous faulty popup script, which incorrectly appended HTML
# <script> tags to the app.js asset. Keep all unrelated styles and code.
for left, right in ((old_begin, old_end), (begin, end)):
    if target.count(left) != target.count(right) or target.count(left) > 1:
        raise RuntimeError('Найдены некорректные маркеры предыдущего патча.')
    if left in target:
        a = target.index(left)
        b = target.index(right, a) + len(right)
        target = target[:a].rstrip() + '\n\n' + target[b:].lstrip('\n')

target = target.rstrip() + '\n\n' + patch + '\n'
compile(target, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(target, encoding='utf-8')
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TMP/patched.py" "$TARGET"; then
  echo "✓ Выпадающие меню WPO уже обновлены. Изменений нет."
  exit 0
fi
BACKUP="/var/backups/web-panel-online/select-popup-v2-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-ui-select-v2.XXXXXXXX.py")"
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
(( READY )) || { echo "WPO не ответила после обновления; выполняется откат." >&2; exit 4; }
CHANGED=0
echo "✓ WPO: открытые списки теперь оформлены в едином стиле, без боковой полосы."
echo "✓ Обновлены Подключения, Пользователи, Ноды, Обновления и остальные одиночные выпадающие поля."
echo "✓ Только интерфейс. REALITY, Xray, пользователи, ноды и подписки не менялись."
echo "✓ Резервная копия интерфейса: $BACKUP"
