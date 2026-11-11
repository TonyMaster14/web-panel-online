#!/usr/bin/env bash
# WEB PANEL ONLINE 3.0 — focused preset gallery update.
# Preserves existing nodes, protocols, clients, secrets, domain and site HTML.
set -Eeuo pipefail
umask 077

[[ "$EUID" == 0 ]] || { echo 'Run this updater as root.' >&2; exit 1; }
APP="/opt/tproxy-panel"
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
EXTRAS="$APP/wpp_panel_extras.py"
SERVICE="tproxy-panel.service"
REF="db56a44c92f967f8978320f122a392a99a6457db"
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF"
for file in "$PANEL" "$UI" "$EXTRAS"; do
    [[ -s "$file" ]] || { echo "Missing panel file: $file" >&2; exit 1; }
done
command -v flock >/dev/null || { echo 'flock is required.' >&2; exit 1; }
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Another update/install is running.' >&2; exit 1; }

STAGE="$(mktemp -d /tmp/wpo-presets.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/preset-gallery-backup-$(date -u +%Y%m%dT%H%M%SZ)"
MODIFIED=0
finish() {
    local code=$?
    trap - EXIT
    if (( code != 0 && MODIFIED )); then
        echo 'The update failed; restoring previous panel modules...' >&2
        for item in panel.py wpp_ui.py wpp_panel_extras.py; do
            if [[ -f "$BACKUP/$item" ]]; then
                cp -a "$BACKUP/$item" "$APP/$item" || true
            fi
        done
        systemctl restart "$SERVICE" 2>/dev/null || true
    fi
    rm -rf -- "$STAGE"
    exit "$code"
}
trap finish EXIT

install -d -m 0700 "$BACKUP"
for item in panel.py wpp_ui.py wpp_panel_extras.py; do
    cp -a "$APP/$item" "$BACKUP/$item"
done
echo 'Updating only the Settings → Presets gallery (main repository)...'
for item in install-panel.sh wpp_ui.py wpp_panel_extras.py; do
    curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 \
        "$BASE/$item" -o "$STAGE/$item"
    [[ -s "$STAGE/$item" ]] || { echo "Download failed: $item" >&2; exit 1; }
done
bash -n "$STAGE/install-panel.sh"
python3 -m py_compile "$STAGE/wpp_ui.py" "$STAGE/wpp_panel_extras.py"

# Repair any missing bundled WebP photos, without touching custom site files.
for photo in preset-cars.webp preset-car-graphite.webp preset-car-silver.webp \
             preset-car-white.webp preset-car-blue.webp preset-car-red.webp \
             preset-car-black.webp preset-coffee.webp; do
    if python3 - "/srv/tproxy-site/$photo" <<'PY_PHOTO'
from pathlib import Path
import sys
try:
    b=Path(sys.argv[1]).read_bytes()
    assert len(b) >= 12 and len(b) <= 4*1024*1024
    assert b[:4]==b"RIFF" and b[8:12]==b"WEBP"
except (OSError,AssertionError):
    sys.exit(1)
PY_PHOTO
    then continue; fi
    echo "Restoring local photo: $photo"
    curl -4fsSL --retry 3 --connect-timeout 12 --max-time 60 \
        "$BASE/assets/$photo" -o "$STAGE/$photo"
    python3 - "$STAGE/$photo" <<'PY_PHOTO'
from pathlib import Path
import sys
b=Path(sys.argv[1]).read_bytes()
if not (12 <= len(b) <= 4*1024*1024 and b[:4]==b"RIFF" and b[8:12]==b"WEBP"):
    sys.exit("Photo download has invalid WebP magic.")
PY_PHOTO
    MODIFIED=1
    install -o root -g tproxy -m 0640 "$STAGE/$photo" "/srv/tproxy-site/$photo"
done

# Extract the exact verified implementation from our official install-panel.sh.
# Apply narrow, guarded edits to the running panel.py. All Nodes Lab code and
# other customizations elsewhere in panel.py remain byte-for-byte unchanged.
# Never replace wpp_ui.py wholesale: Nodes Lab v26 customizes it on the VPS.
# Patch only editor_ui and gallery-specific CSS, leaving every node change intact.
MODIFIED=1
python3 - "$PANEL" "$UI" "$STAGE/install-panel.sh" "$STAGE/wpp_ui.py" <<'PY_PATCH'
from pathlib import Path
import os
import re
import sys
import tempfile

target=Path(sys.argv[1])
ui_path=Path(sys.argv[2])
reference=Path(sys.argv[3]).read_text(encoding="utf-8")
ref_ui=Path(sys.argv[4]).read_text(encoding="utf-8")
original=target.read_text(encoding="utf-8")
original_ui=ui_path.read_text(encoding="utf-8")
content=original
ui_code=original_ui

def span(text,start,end):
    a=text.find(start)
    if a<0:
        raise SystemExit("Cannot locate the start marker: "+start[:100])
    b=text.find(end,a+len(start))
    if b<0:
        raise SystemExit("Cannot locate the end marker: "+end[:100])
    return text[a:b]

old_import="from wpp_panel_extras import preview_document"
new_import="from wpp_panel_extras import preview_document, inline_bundled_preset_photos"
if new_import not in content:
    if content.count(old_import)!=1:
        raise SystemExit("Unexpected backend import layout; no changes applied.")
    content=content.replace(old_import,new_import,1)

css_start='    css="/* WEB PANEL ONLINE public CSS */'
css_end='    javascript="/* WEB PANEL ONLINE public JS */'
updated_css=span(reference,css_start,css_end)
current_css=span(content,css_start,css_end)
if "inline_bundled_preset_photos(css)" not in current_css:
    if current_css.count("css=")!=1 or not current_css.strip().endswith('if styles else ""'):
        raise SystemExit("Unexpected stylesheet generator; no changes applied.")
    content=content.replace(current_css,updated_css,1)

preview_start='        if path in (PANEL_PATH+"/preview-html",PANEL_PATH+"/save-draft"'
preview_end='        if path==PANEL_PATH+"/add-user":'
updated_preview=span(reference,preview_start,preview_end)
current_preview=span(content,preview_start,preview_end)
if 'use_preset=path.endswith("/draft-preset")' not in current_preview:
    if current_preview.count('self.send_json({"document":preview_document(')!=1:
        raise SystemExit("Unexpected preview route; no changes applied.")
    content=content.replace(current_preview,updated_preview,1)

apply_start='        if path==PANEL_PATH+"/apply-preset":'
apply_end='        if path==PANEL_PATH+"/password":'
updated_apply=span(reference,apply_start,apply_end)
current_apply=span(content,apply_start,apply_end)
if 'async_apply=self.headers.get("X-WPP-Async","")=="1"' not in current_apply:
    if current_apply.count('write_site_html(preset["html"])')!=1:
        raise SystemExit("Unexpected publication route; no changes applied.")
    content=content.replace(current_apply,updated_apply,1)

expected=[
    new_import,"inline_bundled_preset_photos(css)",
    'use_preset=path.endswith("/draft-preset")',
    'async_apply=self.headers.get("X-WPP-Async","")=="1"',
]
if not all(mark in content for mark in expected):
    raise SystemExit("The preset gallery backend is incomplete.")
# Ensure none of the existing Nodes Lab additions have been removed.
node_marks=set(re.findall(r"# wpo-node-[^\n]+", original))
if not all(mark in content for mark in node_marks):
    raise SystemExit("Nodes Lab feature marker changed. Refusing patch.")
# Update the Settings gallery without clobbering Nodes Lab v26 UI changes.
ui_start='def editor_ui(source, path, csrf, presets, has_draft):'
ui_end='\ndef openflux_ui('
latest_editor=span(ref_ui,ui_start,ui_end)
current_editor=span(ui_code,ui_start,ui_end)
if 'id="presetGallery"' not in current_editor:
    if 'id="editorForm"' not in current_editor:
        raise SystemExit("Unexpected existing settings editor; refusing to overwrite.")
    ui_code=ui_code.replace(current_editor,latest_editor,1)

css_anchor='# Compact outlined preset gallery'
if css_anchor not in ui_code:
    gallery_css=span(ref_ui,css_anchor,'\ndef editor_ui(')
    if not gallery_css.startswith(css_anchor) or not gallery_css.count("CSS += '''")==1:
        raise SystemExit("Cannot identify the new gallery stylesheet.")
    ui_code=ui_code.replace(ui_start,gallery_css+'\n'+ui_start,1)

# Keep every Nodes Lab marker in both files, not only the panel backend.
ui_marks=set(re.findall(r'(?:#|/\*) wpo-node-[^\n]+',original_ui))
if not all(mark in ui_code for mark in ui_marks):
    raise SystemExit("A Nodes Lab UI marker was lost; refusing update.")
if not all(mark in ui_code for mark in ('id="presetGallery"','id="previewDialog"',css_anchor)):
    raise SystemExit("Gallery implementation is incomplete.")
compile(content,str(target),"exec")
compile(ui_code,str(ui_path),"exec")

def atomic_source_replace(path,code):
    st=path.stat()
    fd,tmp=tempfile.mkstemp(prefix=".wpo-gallery-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(code)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(tmp,st.st_uid,st.st_gid)
        os.chmod(tmp,st.st_mode & 0o777)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

if content!=original:
    atomic_source_replace(target,content)
    print("Panel backend: preset routes updated.")
else:
    print("Panel backend: already up to date.")
if ui_code!=original_ui:
    atomic_source_replace(ui_path,ui_code)
    print("Settings gallery updated; existing Nodes Lab UI retained.")
else:
    print("Settings gallery: already up to date.")
PY_PATCH
install -o root -g root -m 0644 "$STAGE/wpp_panel_extras.py" "$EXTRAS"
python3 -m py_compile "$PANEL" "$UI" "$EXTRAS"
# Smoke-test actual packaged pages and every photo before restarting panel.
# The isolated preview must inline photographs without changing the doctype.
python3 - "$APP" <<'PY_SMOKE'
import sys
sys.path.insert(0,sys.argv[1])
from wpp_panel_extras import preview_document
from wpp_presets import presets
items=presets()
required={"countdown","cars","auto-service","beauty-salon","phone-repair","medical-diagnostics"}
assert required.issubset({str(p["id"]) for p in items}), "Missing built-in site preset"
for p in items:
    doc=preview_document(p["html"],None)
    assert doc.lstrip().lower().startswith("<!doctype html>"), "HTML doctype was lost: "+p["id"]
    assert "Content-Security-Policy" in doc, "Preview CSP missing: "+p["id"]
    if p["id"]=="cars":
        assert doc.count("data:image/webp;base64,")>=7, "Some car photos are missing in preview"
    if p["id"]=="countdown":
        assert "data:image/webp;base64," in doc, "Coffee preview photo is missing"
print("✓ Site previews and all seven car photos verified.")
PY_SMOKE
systemctl restart "$SERVICE"
systemctl is-active --quiet "$SERVICE" ||
    { echo 'Panel service did not become active.' >&2; exit 1; }
PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
if [[ -n "$PANEL_PATH" ]]; then
    ACTIVE=0
    for n in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS --noproxy '*' --max-time 3 \
            "http://127.0.0.1:8090$PANEL_PATH/__health" >/dev/null 2>&1; then
            ACTIVE=1
            break
        fi
        sleep 1
    done
    (( ACTIVE )) || { echo 'Panel health check failed.' >&2; exit 1; }
fi
echo '✓ Presets: compact gallery, modal previews, reliable local photos, async publish.'
echo '✓ User profiles, subscriptions, protocols and Nodes Lab preserved.'
echo "✓ Backup: $BACKUP"
