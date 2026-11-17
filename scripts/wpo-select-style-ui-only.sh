#!/usr/bin/env bash
# WPO: apply only the unified REALITY-style select CSS to the running controller.
# No panel application replacement, no REALITY, Xray, HAProxy or user data changes.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Запустите с sudo на основной панели WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=134618e5da06eaaaf0b149ee134bac98b3f41d42
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || {
  echo "Установленная панель WPO не найдена; ничего не изменено." >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo "Служба WPO не активна; ничего не изменено." >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-select-style.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish(){
  local rc=$?
  trap - EXIT
  if ((rc != 0 && CHANGED == 1)) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Оформление не применилось, исходный интерфейс восстановлен: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap finish EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 75 --proto '=https' \
  "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys
target=Path(sys.argv[1]).read_text(encoding="utf-8")
source=Path(sys.argv[2]).read_text(encoding="utf-8")
start="# wpo-reality-picker-unified-select-v1:"
if source.count(start)!=1:
    raise RuntimeError("Source version mismatch: style marker is missing or duplicate.")
css=source[source.index(start):]
if not css.strip().endswith("'''"):
    raise RuntimeError("Invalid source CSS footer.")
if ("CSS +=" not in css or "background-image:" not in css or
        "#clientFilter" not in css or "#panelRelease" not in css or
        "#connectionProtocol" not in css or "dialog select" not in css):
    raise RuntimeError("Incomplete select style patch.")
if target.count(start)>1:
    raise RuntimeError("Existing repeated CSS marker; aborting safely.")
if "CSS = " not in target or "def connections_ui(" not in target:
    raise RuntimeError("Installed WPO UI is not compatible.")
if start in target:
    target=target[:target.index(start)].rstrip()+"\n\n"+css
else:
    target=target.rstrip()+"\n\n"+css
compile(target,sys.argv[3],"exec")
Path(sys.argv[3]).write_text(target,encoding="utf-8")
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TMP/patched.py" "$TARGET"; then
  echo 'WPO: стиль списков «Сайт для REALITY» уже установлен. Изменений нет.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/select-style-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-ui-style.XXXXXXXX.py")"
cp "$TMP/patched.py" "$STAGE"
chown --reference="$TARGET" "$STAGE"
chmod --reference="$TARGET" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$TARGET"
python3 -m py_compile "$TARGET"
systemctl restart "$SERVICE"
READY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' \
      http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo 'WPO не ответила после обновления; выполняется откат.' >&2; exit 4; }
CHANGED=0
echo "✓ Выпадающие списки оформлены в стиле «Сайт для REALITY»."
echo "✓ Подключения, Пользователи, Ноды, Обновления."
echo "✓ Резервная копия интерфейса: $BACKUP"
echo "✓ Изменён только CSS в wpp_ui.py. REALITY, Xray, пользователи, ноды и подписки не изменены."
