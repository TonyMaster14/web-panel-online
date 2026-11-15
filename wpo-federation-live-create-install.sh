#!/usr/bin/env bash
# WPO test branch: repair the false-negative three-node create gate.
# Runs on PRIMARY WPO only; no remote SSH, Node Agent changes or VPN restarts.
set -Eeuo pipefail
umask 077
[[ "${EUID}" == 0 ]] || { echo 'Запустите на ОСНОВНОЙ WPO через sudo.' >&2; exit 2; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
[[ -s "$PANEL" && -s "$APP/wpp_nodes.py" &&
   -s /var/lib/tproxy-panel/nodes.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
  echo 'Это не основная WPO или отсутствует реестр нод. Изменения не внесены.' >&2
  exit 2
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Другое обновление WPO выполняется. Изменения не внесены.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-federation-live.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/live-federation-backup-$(date -u +%Y%m%dT%H%M%SZ).py"
ROLLBACK=0
finish(){
  code=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo 'Проверка новой панели не прошла. Восстанавливаю предыдущий код.' >&2
    cp -a "$BACKUP" "$PANEL" || true
    rm -f "$APP"/__pycache__/panel.*.pyc
    systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
  fi
  rm -rf -- "$WORK"
  exit "$code"
}
trap finish EXIT
trap 'exit 130' INT TERM
PATCH_REV=bdce5a7b2677a1128a0a8dfb82aa4d3080fe53b1
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 12 --max-time 90 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$PATCH_REV/wpo-federation-live-create-patch.py" \
  -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
python3 "$WORK/patch.py" --input "$PANEL" --output "$WORK/panel.py"
python3 -m py_compile "$WORK/panel.py"
grep -Fq '# wpo-federation-live-create-v1' "$WORK/panel.py"
grep -Fq 'node_api.API_PREFIX+"/federation/status"' "$WORK/panel.py"
grep -Fq 'len(distinct_nodes)>1' "$WORK/panel.py" || {
  echo 'Старая версия многонодовой подписки; сначала требуется проверка установки Happ.' >&2
  exit 3
}
if cmp -s "$WORK/panel.py" "$PANEL"; then
  echo '✓ Серверная проверка VPN Federation уже установлена.'
  exit 0
fi
cp -a "$PANEL" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0644 "$WORK/panel.py" "$PANEL"
rm -f "$APP"/__pycache__/panel.*.pyc
systemctl restart tproxy-panel.service
PANEL_PATH="$(systemctl show -p Environment --value tproxy-panel.service |
  tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n 1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] || exit 4
READY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if systemctl is-active --quiet tproxy-panel.service &&
     [[ "$(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
         "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null)" == OK ]]; then
    READY=1
    break
  fi
  sleep 1
done
[[ "$READY" == 1 ]] || exit 4
ROLLBACK=0
echo '✓ Основная WPO работает.'
echo '✓ Новые подписки проверяют реальный VPN Federation вместо старого статуса Node Agent.'
echo '✓ Логика оригинальных VLESS/Hysteria2, существующие пользователи и ключи не изменены.'
echo '✓ Если одна из VPN-служб действительно недоступна, будет явная ошибка 503, а не ложное подключение.'
echo "Резервная копия: $BACKUP"
