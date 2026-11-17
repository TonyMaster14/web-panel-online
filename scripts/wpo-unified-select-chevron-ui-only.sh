#!/usr/bin/env bash
# UI-only: unify the chevron icons across native and custom WPO selects.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на основном сервере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=e41737d6411a3448404908a3337226b711814d28
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || { echo 'WPO не найдена. Ничего не изменено.' >&2; exit 2; }
systemctl is-active --quiet "$SERVICE" || { echo 'Служба WPO не активна. Ничего не изменено.' >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-select-chevron.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "При ошибке восстановлена резервная копия WPO: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap finish EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys

old = Path(sys.argv[1]).read_text(encoding='utf-8')
source = Path(sys.argv[2]).read_text(encoding='utf-8')
begin = '# WPO_UNIFIED_SELECT_CHEVRON_V1_BEGIN'
end = '# WPO_UNIFIED_SELECT_CHEVRON_V1_END'
if source.count(begin) != 1 or source.count(end) != 1:
    raise RuntimeError('Невозможно прочитать патч стрелок из исходного кода.')
patch = source[source.index(begin):source.index(end) + len(end)]
if source.index(begin) >= source.index(end) or any(marker not in patch for marker in (
        'CSS +=', 'background-position:right 12px center', 'wpo-popup-select-chevron',
        'WPO_SELECT_POPOVER_V2_JS.replace', 'ASSET_REV =')):
    raise RuntimeError('Патч стрелок неполный; изменений нет.')
if not all(marker in old for marker in ('CSS = ', 'COMMON_JS = ', 'def page_layout(', 'ASSET_REV =')):
    raise RuntimeError('Неизвестная версия WPO; файлы не менялись.')
if old.count(begin) != old.count(end) or old.count(begin) > 1:
    raise RuntimeError('Обнаружено некорректное повторное оформление стрелок.')
if begin in old:
    a = old.index(begin)
    b = old.index(end, a) + len(end)
    updated = old[:a] + patch + old[b:]
else:
    updated = old.rstrip() + '\n\n' + patch + '\n'
compile(updated, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(updated, encoding='utf-8')
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TMP/patched.py" "$TARGET"; then
  echo '✓ Единые стрелки WPO уже установлены.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/select-chevron-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-ui-chevron.XXXXXXXX.py")"
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
(( READY )) || { echo 'WPO не ответила после обновления — выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Стрелки всех выпадающих списков WPO приведены к одному стилю и размеру.'
echo '✓ Изменён только интерфейс. Подключения, маршруты, подписки, ноды не затронуты.'
echo "✓ Резервная копия: $BACKUP"
