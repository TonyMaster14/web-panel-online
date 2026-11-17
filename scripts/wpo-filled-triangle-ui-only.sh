#!/usr/bin/env bash
# WPO UI-only: gray filled triangle arrows across selects, including REALITY picker.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Запустите через sudo на основном сервере WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
REALITY="$APP/wpo_reality_ui.py"
SERVICE=tproxy-panel.service
REV=100ada8fc307902a36d97e2475b8594247e7828e
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src"
[[ -s "$UI" && -s "$REALITY" && -s "$APP/panel.py" && ! -L "$UI" && ! -L "$REALITY" ]] || {
  echo "Файлы интерфейса WPO не найдены; ничего не изменено." >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || { echo "Служба WPO неактивна; ничего не изменено." >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-filled-triangle.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" && -s "$BACKUP/wpo_reality_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$UI" || true
    cp -a "$BACKUP/wpo_reality_ui.py" "$REALITY" || true
    systemctl restart "$SERVICE" || true
    echo "Ошибка проверки. Оба файла интерфейса восстановлены: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap finish EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$BASE/wpp_ui.py" -o "$TMP/src_ui.py"
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$BASE/wpo_reality_ui.py" -o "$TMP/src_reality.py"
python3 - "$UI" "$REALITY" "$TMP/src_ui.py" "$TMP/src_reality.py" "$TMP/new_ui.py" "$TMP/new_reality.py" <<'PY'
from pathlib import Path
import sys

ui = Path(sys.argv[1]).read_text(encoding='utf-8')
reality = Path(sys.argv[2]).read_text(encoding='utf-8')
src_ui = Path(sys.argv[3]).read_text(encoding='utf-8')
src_reality = Path(sys.argv[4]).read_text(encoding='utf-8')

def extract(src, begin, end):
    if src.count(begin) != 1 or src.count(end) != 1 or src.index(begin) >= src.index(end):
        raise RuntimeError("Недопустимые маркеры стрелок в исходной версии WPO.")
    return src[src.index(begin):src.index(end) + len(end)]

ui_begin = "# WPO_FILLED_TRIANGLE_ICON_V1_BEGIN"
ui_end = "# WPO_FILLED_TRIANGLE_ICON_V1_END"
ui_patch = extract(src_ui, ui_begin, ui_end)
if not all(x in ui_patch for x in ('CSS +=', 'ASSET_REV =', 'wpo-popup-select-chevron', 'M7 9h10l-5 6z')):
    raise RuntimeError("Неполный патч иконок WPO.")
if not all(x in ui for x in ('CSS = ', 'COMMON_JS = ', 'def page_layout(', 'ASSET_REV = ')):
    raise RuntimeError("Неизвестная версия wpp_ui.py; изменять её нельзя.")
if ui.count(ui_begin) != ui.count(ui_end) or ui.count(ui_begin) > 1:
    raise RuntimeError("Найдены повреждённые маркеры стрелок в wpp_ui.py.")
if ui_begin in ui:
    a, b = ui.index(ui_begin), ui.index(ui_end, ui.index(ui_begin)) + len(ui_end)
    ui = ui[:a] + ui_patch + ui[b:]
else:
    ui = ui.rstrip() + "\n\n" + ui_patch + "\n"

css_begin = "/* WPO_REALITY_FILLED_TRIANGLE_V1_BEGIN */"
css_end = "/* WPO_REALITY_FILLED_TRIANGLE_V1_END */"
css = extract(src_reality, css_begin, css_end)
old = '<span aria-hidden="true">⌄</span>'
new = '<span class="wpo-reality-picker-triangle" aria-hidden="true"></span>'
if 'def editor(' not in reality or 'wpo-reality-picker-toggle' not in reality or "</style>'''" not in reality:
    raise RuntimeError("Неизвестная версия REALITY UI; ничего не изменено.")
if reality.count(old) == 1:
    reality = reality.replace(old, new, 1)
elif reality.count(new) != 1:
    raise RuntimeError("Поле «Сайт для REALITY» не соответствует ожидаемой версии.")
if reality.count(css_begin) != reality.count(css_end) or reality.count(css_begin) > 1:
    raise RuntimeError("Найдены повреждённые маркеры стрелок REALITY.")
if css_begin in reality:
    a, b = reality.index(css_begin), reality.index(css_end, reality.index(css_begin)) + len(css_end)
    reality = reality[:a] + css + reality[b:]
else:
    reality = reality.replace("</style>'''", css + "\n</style>'''", 1)

compile(ui, sys.argv[5], 'exec')
compile(reality, sys.argv[6], 'exec')
Path(sys.argv[5]).write_text(ui, encoding='utf-8')
Path(sys.argv[6]).write_text(reality, encoding='utf-8')
PY
python3 -m py_compile "$TMP/new_ui.py" "$TMP/new_reality.py"
if cmp -s "$UI" "$TMP/new_ui.py" && cmp -s "$REALITY" "$TMP/new_reality.py"; then
  echo '✓ Серые треугольные стрелки уже установлены в WPO.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/filled-triangle-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"
cp -a "$REALITY" "$BACKUP/wpo_reality_ui.py"
STAGE_UI="$(mktemp "$APP/.wpp-ui-triangle.XXXXXXXX.py")"
STAGE_REALITY="$(mktemp "$APP/.wpo-reality-triangle.XXXXXXXX.py")"
cp "$TMP/new_ui.py" "$STAGE_UI"
cp "$TMP/new_reality.py" "$STAGE_REALITY"
chown --reference="$UI" "$STAGE_UI"
chmod --reference="$UI" "$STAGE_UI"
chown --reference="$REALITY" "$STAGE_REALITY"
chmod --reference="$REALITY" "$STAGE_REALITY"
CHANGED=1
mv -f "$STAGE_UI" "$UI"
mv -f "$STAGE_REALITY" "$REALITY"
python3 -m py_compile "$UI" "$REALITY"
systemctl restart "$SERVICE"
READY=0
for i in $(seq 1 15); do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo 'WPO не ответила после установки. Выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Единые маленькие серые залитые треугольники во всех выпадающих полях WPO.'
echo '✓ Исправлено отдельное поле «Сайт для REALITY».'
echo '✓ Изменён только интерфейс, VPN и настройки пользователей не затронуты.'
echo "✓ Резервная копия обоих файлов: $BACKUP"
