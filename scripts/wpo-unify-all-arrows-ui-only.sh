#!/usr/bin/env bash
# UI-only unification of all disclosure and dropdown triangle arrows in WPO.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на основном сервере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
REALITY="$APP/wpo_reality_ui.py"
SERVICE=tproxy-panel.service
REV=252ccaa43e78a6fa8c38f443fdd3e9194830f122
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src"
[[ -s "$UI" && -s "$REALITY" && -s "$APP/panel.py" && ! -L "$UI" && ! -L "$REALITY" ]] || {
  echo 'Файлы интерфейса WPO не найдены; ничего не изменено.' >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo 'Служба WPO не активна; ничего не изменено.' >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-unified-arrows.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" && -s "$BACKUP/wpo_reality_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$UI" || true
    cp -a "$BACKUP/wpo_reality_ui.py" "$REALITY" || true
    systemctl restart "$SERVICE" || true
    echo "Ошибка применения; предыдущий UI восстановлен из $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap finish EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL/wpp_ui.py" -o "$TMP/src_ui.py"
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL/wpo_reality_ui.py" -o "$TMP/src_reality.py"
python3 - "$UI" "$REALITY" "$TMP/src_ui.py" "$TMP/src_reality.py" "$TMP/new_ui.py" "$TMP/new_reality.py" <<'PY'
from pathlib import Path
import sys

ui = Path(sys.argv[1]).read_text(encoding="utf-8")
reality = Path(sys.argv[2]).read_text(encoding="utf-8")
src_ui = Path(sys.argv[3]).read_text(encoding="utf-8")
src_reality = Path(sys.argv[4]).read_text(encoding="utf-8")

def extract(src, start, end):
    if src.count(start) != 1 or src.count(end) != 1 or src.index(start) >= src.index(end):
        raise RuntimeError(f"Не найден корректный исходный UI-патч {start}")
    return src[src.index(start):src.index(end)+len(end)]

def apply(target, patch, start, end):
    if target.count(start) != target.count(end) or target.count(start) > 1:
        raise RuntimeError(f"Повреждены маркеры оформления {start}")
    if start in target:
        a = target.index(start)
        b = target.index(end, a)+len(end)
        return target[:a]+patch+target[b:]
    return target.rstrip()+"\n\n"+patch+"\n"

if not all(k in ui for k in ("CSS = ", "COMMON_JS = ", "def page_layout(", "ASSET_REV = ")):
    raise RuntimeError("Неизвестная версия интерфейса WPO.")
if "def editor(" not in reality or "wpo-reality-picker-toggle" not in reality:
    raise RuntimeError("Неизвестная версия редактора REALITY.")

# Apply the initial filled-triangle styling (also supports older panel builds)
# and then the comprehensive override of all dropdowns and details/summary arrows.
for start, end in (
    ("# WPO_FILLED_TRIANGLE_ICON_V1_BEGIN", "# WPO_FILLED_TRIANGLE_ICON_V1_END"),
    ("# WPO_GLOBAL_DISCLOSURE_TRIANGLE_V2_BEGIN", "# WPO_GLOBAL_DISCLOSURE_TRIANGLE_V2_END"),
):
    patch = extract(src_ui, start, end)
    if "CSS +=" not in patch or "ASSET_REV = " not in patch:
        raise RuntimeError("UI-патч неполон.")
    ui = apply(ui, patch, start, end)

start = "/* WPO_REALITY_FILLED_TRIANGLE_V1_BEGIN */"
end = "/* WPO_REALITY_FILLED_TRIANGLE_V1_END */"
patch = extract(src_reality, start, end)
old_glyph = '<span aria-hidden="true">⌄</span>'
new_glyph = '<span class="wpo-reality-picker-triangle" aria-hidden="true"></span>'
if reality.count(old_glyph) == 1:
    reality = reality.replace(old_glyph, new_glyph, 1)
elif reality.count(new_glyph) != 1:
    raise RuntimeError("Не распознан переключатель «Сайт для REALITY».")
if reality.count(start) != reality.count(end) or reality.count(start) > 1:
    raise RuntimeError("Старый стиль REALITY имеет повреждённые маркеры.")
if start in reality:
    a = reality.index(start)
    b = reality.index(end,a)+len(end)
    reality = reality[:a]+patch+reality[b:]
elif reality.count("</style>'''") == 1:
    reality = reality.replace("</style>'''",patch+"\n</style>'''",1)
else:
    raise RuntimeError("Невозможно аккуратно добавить стиль REALITY.")

compile(ui, sys.argv[5], "exec")
compile(reality, sys.argv[6], "exec")
Path(sys.argv[5]).write_text(ui,encoding="utf-8")
Path(sys.argv[6]).write_text(reality,encoding="utf-8")
PY
python3 -m py_compile "$TMP/new_ui.py" "$TMP/new_reality.py"
if cmp -s "$UI" "$TMP/new_ui.py" && cmp -s "$REALITY" "$TMP/new_reality.py"; then
  echo '✓ Стрелки WPO уже приведены к единому стилю.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/unified-arrows-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"
cp -a "$REALITY" "$BACKUP/wpo_reality_ui.py"
STAGE_UI="$(mktemp "$APP/.wpp-ui-arrows.XXXXXXXX.py")"
STAGE_REALITY="$(mktemp "$APP/.wpo-reality-arrows.XXXXXXXX.py")"
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
(( READY )) || { echo 'WPO не ответила после обновления; откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Во всех выпадающих полях и раскрывающихся секциях WPO один серый треугольник 10x6 в области 16x16.'
echo '✓ Отдельный список «Сайт для REALITY» также обновлён.'
echo '✓ Изменены только два UI-файла. REALITY, Xray, пользователи, ноды и подписки не менялись.'
echo "✓ Резервная копия: $BACKUP"
