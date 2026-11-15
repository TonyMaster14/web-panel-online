#!/usr/bin/env bash
# MAIN WPO only: make multi-node account creation independent of remote GET.
# Never modifies additional VPS, Node Agent, Xray, Caddy, subscriber keys.
set -Eeuo pipefail
umask 077
[[ "${EUID}" == 0 ]] || { echo 'Запустите на ОСНОВНОЙ WPO через sudo.' >&2; exit 2; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
[[ -s "$PANEL" && -s "$APP/wpp_nodes.py" &&
   -s "$APP/wpo_happ_async_feed.py" &&
   -s "$APP/wpo_happ_preparer.py" &&
   -s /etc/web-proxy-panel/users.json &&
   -s /var/lib/tproxy-panel/nodes.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
  echo 'Не найдена основная WPO с асинхронной подготовкой нод. Изменения не внесены.' >&2
  exit 2
}
systemctl cat wpo-happ-preparer.service >/dev/null 2>&1 || {
  echo 'Служба подготовки VPN Federation не установлена. Ничего не изменено.' >&2
  exit 2
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Обновление WPO уже выполняется. Изменения не внесены.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-happ-queue.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/happ-queue-backup-$(date -u +%Y%m%dT%H%M%SZ).py"
ROLLBACK=0
cleanup(){
  code=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo 'Проверка панели не пройдена. Возвращаю прежний серверный обработчик.' >&2
    cp -a "$BACKUP" "$PANEL" || true
    rm -f "$APP"/__pycache__/panel.*.pyc
    systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
  fi
  rm -rf -- "$WORK"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
REV=bbe233dd8a88efcec090907508e6e0d9295ae4e3
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 12 --max-time 90 \
  "$BASE/wpo-happ-queue-create-patch.py" -o "$WORK/patch.py"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 12 --max-time 90 \
  "$BASE/wpo-happ-readonly-diagnostic.py" -o "$WORK/diagnostic.py"
python3 -m py_compile "$WORK/patch.py" "$WORK/diagnostic.py"
python3 "$WORK/patch.py" --input "$PANEL" --output "$WORK/panel.py"
python3 -m py_compile "$WORK/panel.py"
grep -Fq '# wpo-happ-queue-create-v2:' "$WORK/panel.py"
grep -Fq 'wpo-happ-prewarm-on-create-v2:' "$WORK/panel.py"
grep -Fq 'wpo_happ_async_feed.enqueue(' "$WORK/panel.py"
grep -Fq 'len(distinct_nodes)>1' "$WORK/panel.py"
grep -Fq 'SUB_FETCH_SLOTS.release()' "$WORK/panel.py"
if ! cmp -s "$WORK/panel.py" "$PANEL"; then
  cp -a "$PANEL" "$BACKUP"
  ROLLBACK=1
  install -o root -g root -m 0644 "$WORK/panel.py" "$PANEL"
  rm -f "$APP"/__pycache__/panel.*.pyc
  echo '=== Перезапускаю только основную веб-панель ==='
  systemctl restart tproxy-panel.service
  PANEL_PATH="$(systemctl show -p Environment --value tproxy-panel.service |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
  [[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] || exit 4
  READY=0
  for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
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
else
  echo '✓ Исправление создания подписок уже установлено.'
fi
echo '✓ Можно создавать подписку с зарегистрированными и включёнными нодами без ожидания удалённых API.'
echo '✓ Выдача Happ остаётся защищённой: только проверенные реальные профили; недоступные ноды ещё не добавлены.'
echo '=== Проверка доступности обеих дополнительных VPN Federation (без изменений) ==='
python3 "$WORK/diagnostic.py" || true
echo '✓ WPO обновлена; реальные VPN-подключения нод проверяются отдельно.'
echo "Резервная копия: $BACKUP"
