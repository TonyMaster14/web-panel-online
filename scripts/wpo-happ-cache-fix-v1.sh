#!/usr/bin/env bash
# WPO 3 test: refresh asynchronous Happ REALITY node URI cache safely.
# Controller only. Never edits Node Agent, Xray/HAProxy or subscriber registries.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на основной панели WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
SERVICE=tproxy-panel.service
MODULE="$APP/wpo_happ_async_feed.py"
REV=1245e8a6651e77e9108e09f751df6acfd3545b94
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpo_happ_async_feed.py"
[[ -f "$APP/panel.py" && -f "$MODULE" && ! -L "$MODULE" ]] ||
  { echo 'Основная панель с Happ federation не найдена.' >&2; exit 2; }
systemctl is-active --quiet "$SERVICE" ||
  { echo 'Панель не запущена. Не меняю файлы.' >&2; exit 2; }
command -v curl >/dev/null && command -v python3 >/dev/null || exit 2
STAGE="$(mktemp -d /tmp/wpo-happ-safe.XXXXXXXX)"
BACKUP=""
TOUCHED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && TOUCHED == 1 )) && [[ -n "$BACKUP" && -f "$BACKUP/wpo_happ_async_feed.py" ]]; then
    cp -a "$BACKUP/wpo_happ_async_feed.py" "$MODULE" || true
    systemctl restart "$SERVICE" || true
    echo "WPO: старый модуль Happ восстановлен из $BACKUP" >&2
  fi
  rm -rf -- "$STAGE"
  exit "$rc"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 75 --proto '=https' \
     "$URL" -o "$STAGE/wpo_happ_async_feed.py"
python3 -m py_compile "$STAGE/wpo_happ_async_feed.py"
grep -Fq 'CACHE_TTL = 300' "$STAGE/wpo_happ_async_feed.py" &&
grep -Fq 'if epoch == CACHE_EPOCH:' "$STAGE/wpo_happ_async_feed.py" &&
grep -Fq 'PENDING.clear()' "$STAGE/wpo_happ_async_feed.py" ||
  { echo 'Неверная версия исправления кеша Happ. Файлы не изменены.' >&2; exit 3; }
if cmp -s "$STAGE/wpo_happ_async_feed.py" "$MODULE"; then
  echo 'WPO: исправление кеша Happ уже установлено.'
  exit 0
fi
install -d -m 0700 /var/backups/web-panel-online
BACKUP="/var/backups/web-panel-online/happ-cache-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$MODULE" "$BACKUP/wpo_happ_async_feed.py"
echo "Резервная копия: $BACKUP"
TEMP="$(mktemp "$APP/.wpo-happ-cache.XXXXXXXX.py")"
cp "$STAGE/wpo_happ_async_feed.py" "$TEMP"
chown --reference="$MODULE" "$TEMP"
chmod --reference="$MODULE" "$TEMP"
TOUCHED=1
mv -f "$TEMP" "$MODULE"
PYTHONPATH="$APP" python3 - <<'PY'
import wpo_happ_async_feed as m
assert m.CACHE_TTL==300
assert isinstance(m.CACHE_EPOCH,int)
assert callable(m.invalidate_all)
PY
systemctl restart "$SERVICE"
READY=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if systemctl is-active --quiet "$SERVICE"; then
    code="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' \
                    http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$code" =~ ^[234][0-9][0-9]$ ]]; then
      READY=1
      break
    fi
  fi
  sleep 1
done
(( READY )) || { echo 'Панель не прошла проверку после обновления.' >&2; exit 4; }
TOUCHED=0
echo '✓ Happ: время кеширования удалённых REALITY ссылок 5 минут вместо 24 часов.'
echo '✓ Устаревшая фоновая синхронизация больше не восстановит очищенный кеш.'
echo '✓ Все серверы, клиентские ключи, UUID и текущие REALITY-настройки сохранены.'
echo 'Следующее обновление подписки Happ запросит свежие профили у нод.'
