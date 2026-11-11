#!/usr/bin/env bash
# Compatibility entrypoint; obsolete standby-profile fixes are withdrawn.
# Real site-only mode uses a patched Go relay accepting {"profiles":[]}.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Запустите от root на VPS панели." >&2; exit 1; }
TEMP="$(mktemp /tmp/wpo-zero-profiles.XXXXXXXX.sh)"
trap 'rm -f -- "$TEMP"' EXIT
echo "Обновление v6: публичный сайт независимо от WEB Proxy, без фиктивных профилей..."
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/main/wpo-site-zero-profiles-v6.sh' \
  -o "$TEMP"
bash -n "$TEMP"
bash "$TEMP"
