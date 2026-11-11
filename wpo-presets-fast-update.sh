#!/usr/bin/env bash
# Compatibility entrypoint. The previous standalone card-only patch could
# update the UI without updating the site publication backend.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Запустите обновление от root на основном VPS." >&2; exit 1; }
TMP="$(mktemp /tmp/wpo-presets-v3.XXXXXXXX.sh)"
trap 'rm -f -- "$TMP"' EXIT
echo 'Перенаправляю на объединённое исправление карточек и публикации сайта v3...'
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/main/wpo-presets-live-v3-install.sh' -o "$TMP"
bash -n "$TMP"
bash "$TMP"
