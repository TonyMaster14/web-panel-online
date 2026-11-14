#!/usr/bin/env bash
# Main WPO only: make selected multi-node Happ feeds synchronize concurrently.
# Existing subscriptions, node list, Xray, Caddy, and protocol services untouched.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запусти от root на основном VPS WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
SUBS="$APP/wpp_subscriptions.py"
[[ -s "$PANEL" && -s "$SUBS" && ! -e /etc/wpp-node-agent/config.json ]] || {
  echo 'Нужна ОСНОВНАЯ WPO с модулем подписок, не дополнительная нода.' >&2; exit 2;
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Другое обновление WPO уже выполняется.' >&2; exit 2; }
REV=4ba7f7e0cef7a7771a2fd75062e90fdf199c542f
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV"
TMP="$(mktemp -d /tmp/wpo-multinode-happ.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/multinode-happ-backup-$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && ROLLBACK == 1 )); then
    echo 'Возвращаю прежний код WPO после неудачного обновления.' >&2
    cp -a "$BACKUP/panel.py" "$PANEL" || true
    rm -f "$APP"/__pycache__/panel.*.pyc
    systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 15 --max-time 90 \
  "$BASE/wpo-multinode-feed-fix.py" -o "$TMP/patch.py"
python3 -m py_compile "$TMP/patch.py"
python3 "$TMP/patch.py" --panel "$PANEL" --output "$TMP/panel.py"
python3 -m py_compile "$TMP/panel.py"
grep -Fq '# wpo-multinode-parallel-v1:' "$TMP/panel.py"
grep -Fq 'ThreadPoolExecutor(max_workers=min(len(remote_nodes),4))' "$TMP/panel.py"
grep -Fq 'local_count=len(result["users"]) if local_selected else 0' "$TMP/panel.py"
grep -Fq 'len(distinct_nodes)>1' "$TMP/panel.py"
grep -Fq 'if set(by_protocol)!=set(wanted):' "$TMP/panel.py"
if cmp -s "$TMP/panel.py" "$PANEL"; then
  echo '✓ Параллельная синхронизация VPN-нод уже включена на основной WPO.'
  exit 0
fi
install -d -o root -g root -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
ROLLBACK=1
install -o root -g root -m 0755 "$TMP/panel.py" "$PANEL"
rm -f "$APP"/__pycache__/panel.*.pyc
systemctl restart tproxy-panel.service
PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-z0-9-]{3,64}$ ]] || { echo 'Скрытый путь WPO не найден.' >&2; exit 4; }
READY=0
for n in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet tproxy-panel.service &&
     curl -4fsS --max-time 3 "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null | grep -qx 'OK'; then
    READY=1; break
  fi
  sleep 1
done
(( READY == 1 )) || { echo 'Панель не ответила, выполняется откат.' >&2; exit 4; }
cmp -s "$TMP/panel.py" "$PANEL" || { echo 'Неожиданное изменение установленного кода.' >&2; exit 4; }
ROLLBACK=0
echo '✓ Основная WPO: синхронизация выбранных дополнительных нод параллельно, до 4 одновременно.'
echo '✓ Happ: только реально выбранные VPN-ноды, без неполных подписок.'
echo '✓ Автовыбор сохранён, пользователи и ключи не менялись.'
echo '✓ Основной Xray, Caddy и дополнительная VPS не изменялись.'
echo '✓ Если удалённая нода действительно не создаёт профиль, ошибка 503 остаётся явной.'
echo "Резервная копия: $BACKUP"
