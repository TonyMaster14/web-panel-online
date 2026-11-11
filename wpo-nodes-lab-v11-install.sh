#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$AGENT" ]] || { echo "Установщик нод не найден: $AGENT"; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Требуется Node Agent 0.2. Ничего не изменено.'; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 20 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
if ! grep -Fq 'for EMAIL_ATTEMPT in 1 2 3' "$TMP" ||
   ! grep -Fq 'PY_EMAIL_TRIM' "$TMP" ||
   ! grep -Fq 'PY_VALIDATE_EMAIL' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_STATUS_URL__' "$TMP" ||
   ! grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$TMP" ||
   ! bash -n "$TMP"; then
  echo 'Полученный установщик не прошёл проверку. Действующая версия не изменена.'
  exit 1
fi
if cmp -s "$TMP" "$AGENT"; then
  echo 'Обновление email v11 уже установлено.'
  exit 0
fi
BACKUP="/var/lib/tproxy-panel/nodes-lab-v11-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"
if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
  cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
  echo 'Обновление не удалось, исходный установщик восстановлен.'
  exit 1
fi
echo 'Nodes Lab v11: email проверяется до установки Caddy; невидимые символы по краям убираются; три попытки ввода.'
echo "Резервная копия: $BACKUP"
echo 'Панель не перезапускалась. GitHub main не изменён.'
