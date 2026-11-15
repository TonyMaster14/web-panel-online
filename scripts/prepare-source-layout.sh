#!/usr/bin/env bash
# Restore historical root module paths only in an unpacked local source bundle.
# GitHub stays compact; the deployed /opt/tproxy-panel layout is unchanged.
set -Eeuo pipefail
umask 077
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
[[ -d "$ROOT/src" ]] || exit 0
for source in "$ROOT"/src/wpp_*.py "$ROOT"/src/wpo_*.py; do
    [[ -s "$source" ]] || continue
    name="${source##*/}"
    target="src/$name"
    dest="$ROOT/$name"
    if [[ -L "$dest" ]]; then
        [[ "$(readlink "$dest")" == "$target" ]] || {
            echo "WPO: unexpected source symlink $dest" >&2
            exit 1
        }
    elif [[ -e "$dest" ]]; then
        cmp -s "$dest" "$source" || {
            echo "WPO: conflicting module $dest (source was not overwritten)" >&2
            exit 1
        }
    else
        ln -s "$target" "$dest"
    fi
done
