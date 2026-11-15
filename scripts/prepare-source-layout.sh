#!/usr/bin/env bash
# Reconstruct the legacy flat source layout after cloning/unpacking WPO.
# Original files remain organized in src/, installers/, nodes/ and docs/.
# Installed /opt/tproxy-panel paths and public entrypoints stay unchanged.
set -Eeuo pipefail
umask 077
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
[[ -d "$ROOT/src" ]] || exit 0

link_compat() {
    local source="$1" name target dest
    [[ -s "$source" ]] || return 0
    name="${2:-${source##*/}}"
    target="${source#"$ROOT"/}"
    dest="$ROOT/$name"
    if [[ -L "$dest" ]]; then
        [[ "$(readlink "$dest")" == "$target" ]] || {
            echo "WPO: unexpected source symlink $dest" >&2
            return 1
        }
    elif [[ -e "$dest" ]]; then
        cmp -s "$dest" "$source" || {
            echo "WPO: refusing to overwrite different file $dest" >&2
            return 1
        }
    else
        ln -s "$target" "$dest"
    fi
}
for source in "$ROOT"/src/wpp_*.py "$ROOT"/src/wpo_*.py \
              "$ROOT"/installers/*.sh "$ROOT"/nodes/wpo-* \
              "$ROOT"/docs/THIRD-PARTY-NOTICES.md; do
    [[ -f "$source" ]] || continue
    link_compat "$source"
done
# Keep legacy package aliases without publishing individual historical patches.
if [[ -s "$ROOT/installers/site-service-update.sh" ]]; then
    link_compat "$ROOT/installers/site-service-update.sh" "wpo-site-zero-profiles-v6.sh"
fi
if [[ -s "$ROOT/installers/site-relay-module.py" ]]; then
    link_compat "$ROOT/installers/site-relay-module.py" "wpo-relay-zero-profiles-patch.py"
fi
