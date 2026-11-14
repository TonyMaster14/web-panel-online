#!/usr/bin/env bash
# Repair WPO's federation error handling on MAIN PANEL and prewarm the existing Happ device.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Используй sudo на ОСНОВНОМ VPS WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_nodes.py"
[[ -s "$APP/panel.py" && -s "$TARGET" && -s /var/lib/tproxy-panel/nodes.json &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Нужна основная панель WPO с зарегистрированными нодами.' >&2; exit 2;
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Другое обновление WPO уже выполняется.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-happ-503.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/happ-503-backup-$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK=0
cleanup() {
  local code=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo 'Панель не прошла проверку — возвращаю прежний модуль нод.' >&2
    cp -a "$BACKUP/wpp_nodes.py" "$TARGET" || true
    rm -f "$APP"/__pycache__/wpp_nodes.*.pyc
    systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
  fi
  rm -rf -- "$WORK"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
BASE=https://raw.githubusercontent.com/TonyMaster14/web-panel-online
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
    --connect-timeout 10 --max-time 60 \
    "$BASE/3b77106340f4a32f99157548d17faf0eff7ccb48/wpo-happ-node-timeout-patch.py" \
    -o "$WORK/patch.py"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
    --connect-timeout 10 --max-time 60 \
    "$BASE/025183c77595aa4297cd7c4314d8881bbe7ae2c6/wpo-happ-post-diagnostic.py" \
    -o "$WORK/post.py"
python3 -m py_compile "$WORK/patch.py" "$WORK/post.py"
python3 "$WORK/patch.py" --input "$TARGET" --output "$WORK/wpp_nodes.py"
python3 -m py_compile "$WORK/wpp_nodes.py"
grep -Fq '}, timeout=90)' "$WORK/wpp_nodes.py"
grep -Fq 'Нода вернула HTTP ' "$WORK/wpp_nodes.py"
if ! cmp -s "$WORK/wpp_nodes.py" "$TARGET"; then
  install -d -o root -g root -m 0700 "$BACKUP"
  cp -a "$TARGET" "$BACKUP/wpp_nodes.py"
  ROLLBACK=1
  install -o root -g root -m 0644 "$WORK/wpp_nodes.py" "$TARGET"
  rm -f "$APP"/__pycache__/wpp_nodes.*.pyc
  systemctl restart tproxy-panel.service
  # This endpoint is already used by WPO's main installer for panel health.
  PANEL_PATH="$(systemctl show -p Environment --value tproxy-panel.service |
      tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
  [[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] ||
      { echo 'Не найден URL панели; выполняю откат.' >&2; exit 4; }
  ready=0
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if systemctl is-active --quiet tproxy-panel.service &&
       [[ "$(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
            "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null)" == OK ]]; then
       ready=1; break
    fi
    sleep 1
  done
  [[ "$ready" == 1 ]] || { echo 'Панель не отвечает; откатываю.' >&2; exit 4; }
  ROLLBACK=0
  echo '✓ Основная WPO исправлена и отвечает.'
else
  echo '✓ Обновлённая синхронизация уже установлена.'
fi
echo '=== Проверяю создание профилей на уже выбранных нодах ==='
echo 'Используется существующее устройство Happ; возможно создание недостающих VPN-профилей.'
if python3 "$WORK/post.py"; then
  echo '✓ Все выбранные VPN-профили подготовлены. Обнови текущую подписку в Happ.'
else
  echo '✗ Одна из нод не создала профиль — точная категория отказа указана выше.' >&2
  echo 'Исправление основной WPO установлено, но работоспособность этих нод пока не подтверждена.' >&2
  exit 6
fi
