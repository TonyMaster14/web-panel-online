#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
[[ $EUID -eq 0 ]] || { echo 'Запустите команду от root.'; exit 1; }
[[ -s "$AGENT" ]] || { echo "Установщик нод не найден: $AGENT"; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Требуется установленный Node Agent 0.2 (Nodes Lab v2). Ничего не изменено.'; exit 1; }
if grep -Fq 'PY_VALIDATE_EMAIL' "$AGENT"; then
  echo 'Проверка email уже обновлена. Ничего не изменено.'
  exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 20 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
if ! grep -Fq 'PY_VALIDATE_EMAIL' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_STATUS_URL__' "$TMP" ||
   ! grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$TMP" ||
   ! bash -n "$TMP"; then
  echo 'Полученный установщик не прошёл проверку; действующая версия не изменена.'
  exit 1
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v10-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"
if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
  cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
  echo 'Ошибка обновления, предыдущая версия восстановлена.'
  exit 1
fi

echo 'Nodes Lab v10: проверка email обновлена.'
echo 'Кириллица и некорректные адреса отклоняются до установки Caddy.'
echo "Резервная копия: $BACKUP"
echo 'Перезапуск панели не требуется. GitHub main не изменён.'
