#!/usr/bin/env bash
# Compatibility redirect: preset publication and gallery share one updater.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Run as root on the main panel VPS.' >&2; exit 1; }
TMP="$(mktemp /tmp/wpo-presets-v4.XXXXXXXX.sh)"
trap 'rm -f -- "$TMP"' EXIT
echo 'Using unified preset publication repair v4 (not a full panel install)...'
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/main/wpo-presets-publish-v4.sh' \
  -o "$TMP"
bash -n "$TMP"
bash "$TMP"
