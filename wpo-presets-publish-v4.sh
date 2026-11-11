#!/usr/bin/env bash
# Compatibility entrypoint: modern installations need the permanent
# always-on site relay fix, not another full preset reinstallation.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS панели.' >&2; exit 1; }
TMP="$(mktemp /tmp/wpp-site-always-on.XXXXXXXX.sh)"
trap 'rm -f -- "$TMP"' EXIT
echo 'Исправляем публикацию шаблонов и всегда доступный сайт (v5)...'
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/main/wpo-site-relay-always-on-v5.sh' -o "$TMP"
bash -n "$TMP"
bash "$TMP"
