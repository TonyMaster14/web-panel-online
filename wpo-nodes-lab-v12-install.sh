#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью.'; exit 1; }
[[ -s "$AGENT" ]] || { echo "Установщик ноды не найден: $AGENT"; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Ожидается Node Agent 0.2. Ничего не изменено.'; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 20 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
if ! grep -Fq 'Email для Let' "$TMP" ||
   ! grep -Fq 'Убраны случайные символы по краям email.' "$TMP" ||
   ! grep -Fq 'PY_VALIDATE_EMAIL' "$TMP" ||
   ! grep -Fq 'tls $EMAIL' "$TMP" ||
   ! grep -Fq 'site-template' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$TMP" ||
   ! grep -Fq '__WPO_CONTROLLER_STATUS_URL__' "$TMP" ||
   ! grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$TMP" ||
   ! bash -n "$TMP"; then
  echo 'Проверка нового установщика не пройдена; ничего не изменено.'
  exit 1
fi

if cmp -s "$TMP" "$AGENT"; then
  echo 'Исправленная версия установщика уже установлена.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v12-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"
if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
  cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
  echo 'Не удалось обновить установщик, выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v12: email сохранён; случайная кириллица по краям удаляется, ошибки исправляются без перезапуска установки.'
echo "Резервная копия: $BACKUP"
echo 'Панель не перезапускалась, репозиторий main не изменён.'
