#!/usr/bin/env bash
# Safe in-place test updater for the agreed Happ node naming preview.
set -Eeuo pipefail
umask 077

die() { echo "ERROR: $*" >&2; exit 1; }
[[ ${EUID:-1} -eq 0 ]] || die "Запустите установщик от root: sudo -i"

export WEB_PANEL_PROXY_REF="preview-happ-node-names"
export GIT_TERMINAL_PROMPT=0

UPDATE_SCRIPT="$(mktemp /tmp/wpo-preview-update.XXXXXX)"
cleanup() { rm -f -- "$UPDATE_SCRIPT"; }
trap cleanup EXIT

curl -4fsSL --retry 3 --retry-all-errors --connect-timeout 20 --proto '=https' --proto-redir '=https' --tlsv1.2 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/preview-happ-node-names/update.sh" \
  -o "$UPDATE_SCRIPT" || die "Не удалось загрузить скрипт обновления."

chmod 0700 "$UPDATE_SCRIPT"
bash "$UPDATE_SCRIPT"
