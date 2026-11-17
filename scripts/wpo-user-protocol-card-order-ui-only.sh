#!/usr/bin/env bash
# UI-only: reorder the new-user protocol cards without changing their values/handlers.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Запустите через sudo на основном сервере WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpo_user_v28.py"
SERVICE=tproxy-panel.service
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || {
  echo "Модуль создания пользователей WPO не найден. Ничего не изменено." >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo "Служба WPO не активна. Ничего не изменено." >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-user-card-order.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -s "$BACKUP/wpo_user_v28.py" ]]; then
    cp -a "$BACKUP/wpo_user_v28.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Ошибка проверки: исходный модуль пользователей восстановлен из $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
python3 - "$TARGET" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
src = p.read_text(encoding='utf-8')
original = (
    '    ("vless", "VLESS XHTTP", "Happ · HTTPS 443", "happ"),\n'
    '    ("reality", "VLESS REALITY", "Happ · TCP 443 · Vision", "happ"),'
)
desired = (
    '    ("reality", "VLESS REALITY", "Happ · TCP 443 · Vision", "happ"),\n'
    '    ("vless", "VLESS XHTTP", "Happ · HTTPS 443", "happ"),'
)
old_css = 'wpo-reality-hysteria{grid-column:2}'
new_css = 'wpo-reality-hysteria{grid-column:1}'
if not all(x in src for x in ('CATALOG = (', 'def form(', 'wpo-v28-grid')):
    raise RuntimeError("Неизвестная версия окна нового пользователя; изменения отменены.")
if src.count(original) == 1:
    src = src.replace(original,desired,1)
elif src.count(desired) != 1:
    raise RuntimeError("Порядок REALITY / XHTTP не распознан; ничего не изменено.")
if src.count(old_css) == 2:
    src = src.replace(old_css,new_css)
elif src.count(old_css) != 0 or src.count(new_css) != 2:
    raise RuntimeError("Расположение Hysteria2 не распознано; ничего не изменено.")
catalog = src[src.index('CATALOG = ('):src.index('VPN_SUPPORTED =')]
protocols = [x.split('"')[1] for x in catalog.splitlines() if x.strip().startswith('("')]
expected = ['reality','vless','web','mtproto','awg20','awg31','naive','mieru','hysteria']
if protocols != expected:
    raise RuntimeError(f"Неожиданный порядок карточек: {protocols}")
compile(src,str(sys.argv[2]),'exec')
Path(sys.argv[2]).write_text(src,encoding='utf-8')
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TARGET" "$TMP/patched.py"; then
  echo "✓ Карточки уже стоят в нужном порядке."
  exit 0
fi
BACKUP="/var/backups/web-panel-online/protocol-card-order-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpo_user_v28.py"
STAGE="$(mktemp "$APP/.wpo-user-card-order.XXXXXXXX.py")"
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
echo "✓ REALITY теперь слева первым, XHTTP справа."
echo "✓ Hysteria2 слева в последней строке, под NaiveProxy."
echo "✓ Изменён только порядок карточек нового пользователя; VPN и подписки не затронуты."
echo "✓ Резервная копия: $BACKUP"
