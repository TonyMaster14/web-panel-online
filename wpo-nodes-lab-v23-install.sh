#!/usr/bin/env bash
# Nodes Lab v23: refresh the Node Agent installer served by "Добавить ноду".
set -Eeuo pipefail
umask 077
AGENT=/opt/tproxy-panel/wpp-node-agent-install.sh
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите на основном VPS WPO от root.'; exit 1; }
[[ -s "$AGENT" ]] || { echo 'Установщик ноды не найден. Сначала установите Nodes Lab v22.'; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Основная панель WPO не найдена.'; exit 1; }
grep -Fq 'WEB PANEL ONLINE — Node Agent 0.2' "$AGENT" || { echo 'Ожидается Node Agent 0.2.'; exit 1; }

if grep -Fq 'wpo-node-agent-reinstall-v23' "$AGENT"; then
    echo 'Nodes Lab v23 уже установлен.'
    exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -4fsSL --retry 3 --connect-timeout 15 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/wpo-node-agent-install-v2.sh' -o "$TMP"
[[ -s "$TMP" ]] || { echo 'Не удалось получить установщик Node Agent.'; exit 1; }

for token in 'wpo-node-agent-reinstall-v23' \
             'systemctl restart wpp-node-agent.service' \
             'Регистрация: HTTP %d' \
             'wpp-api/v1/status' \
             '__WPO_CONTROLLER_ENROLL_URL__' \
             '__WPO_CONTROLLER_STATUS_URL__' \
             'PY_VALIDATE_EMAIL'; do
    grep -Fq "$token" "$TMP" || { echo "Проверка нового установщика не прошла: $token"; exit 1; }
done
bash -n "$TMP" || { echo 'Синтаксис установщика Node Agent некорректен.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v23-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"

if ! install -o root -g root -m 0700 "$TMP" "$AGENT" || ! bash -n "$AGENT"; then
    cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT"
    echo 'Ошибка обновления: предыдущий установщик восстановлен.'
    exit 1
fi

echo 'Nodes Lab v23: установщик из кнопки «Добавить ноду» обновлён.'
echo 'Повторная установка перезапускает Node Agent с новым ключом API.'
echo 'При ошибке регистрации показывается причина, возвращённая панелью.'
echo "Резервная копия: $BACKUP"
echo 'Работающие ноды не изменены. Перезапуск основной панели не нужен. GitHub main не затронут.'
