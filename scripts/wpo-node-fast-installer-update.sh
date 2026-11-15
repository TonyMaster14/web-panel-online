#!/usr/bin/env bash
# Test-branch-only installer refresh for an existing WPO controller.
# Replaces ONLY the node installer served by /node-agent-installer.sh.
# Does not restart the panel, replace its source, or touch existing nodes.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите от root на основном VPS WPO.' >&2; exit 1; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp-node-agent-install.sh"
[[ -f "$APP/panel.py" && -f "$TARGET" && ! -L "$TARGET" ]] || {
  echo 'Основная панель WPO или её установщик не найдены. Изменений нет.' >&2
  exit 2
}
grep -Fq 'node-agent-installer.sh' "$APP/panel.py" || {
  echo 'Панель не поддерживает текущий маршрут установщика ноды. Изменений нет.' >&2
  exit 2
}
command -v curl >/dev/null && command -v bash >/dev/null || exit 2
STAGE="$(mktemp "$APP/.wpo-node-fast.XXXXXXXX")"
trap 'rm -f -- "$STAGE"' EXIT
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 12 --max-time 90 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/test/wpo-smooth-progress-v1/nodes/wpo-node-agent-install-v2.sh' -o "$STAGE"
bash -n "$STAGE"
for marker in '__WPO_CONTROLLER_ENROLL_URL__' '__WPO_CONTROLLER_STATUS_URL__' \
              'node_last_move_us=' 'interval=650000' 'apt-cache show caddy'; do
  grep -Fq "$marker" "$STAGE" || {
    echo "Установщик не прошёл проверку: $marker. Изменений нет." >&2
    exit 3
  }
done
install -d -m 0700 /var/backups/web-panel-online
BACKUP="/var/backups/web-panel-online/wpo-node-installer-$(date -u +%Y%m%dT%H%M%SZ)-$$.sh"
cp -a -- "$TARGET" "$BACKUP"
chown root:root "$STAGE"
chmod 0700 "$STAGE"
mv -f -- "$STAGE" "$TARGET"
echo 'Обновлён установщик новых нод из тестовой ветки.'
echo 'Панель и уже работающие ноды не перезапускались.'
echo "Резервная копия: $BACKUP"
