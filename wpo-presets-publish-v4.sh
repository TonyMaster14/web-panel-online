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
REF="78068296f10a4e23c8d2b02ac66c667938119091"
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF"
for file in "$PANEL" "$UI" "$EXTRAS"; do
    [[ -s "$file" ]] || { echo "Missing panel file: $file" >&2; exit 1; }
done
command -v flock >/dev/null || { echo 'flock is required.' >&2; exit 1; }
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Another update/install is running.' >&2; exit 1; }

STAGE="$(mktemp -d /tmp/wpo-presets.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/preset-publish-v4-backup-$(date -u +%Y%m%dT%H%M%SZ)"
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
echo 'Обновляем публикацию сайтов и проверку на реальном домене (v4)...'
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
# Patch only preset routes, editor_ui and gallery CSS. Nodes Lab is not modified.
MODIFIED=1
python3 - "$PANEL" "$UI" "$STAGE/install-panel.sh" "$STAGE/wpp_ui.py" <<'PY_PATCH'
from pathlib import Path
import os,re,sys,tempfile
panel_path,ui_path=map(Path,sys.argv[1:3])
reference=Path(sys.argv[3]).read_text(encoding="utf-8")
reference_ui=Path(sys.argv[4]).read_text(encoding="utf-8")
old_panel=panel_path.read_text(encoding="utf-8")
old_ui=ui_path.read_text(encoding="utf-8")
panel,ui=old_panel,old_ui

def between(src,start,end):
    begin=src.find(start)
    if begin<0 or src.find(start,begin+len(start))!=-1:
        raise RuntimeError("Неподдерживаемая версия панели, якорь: "+start[:90])
    finish=src.find(end,begin+len(start))
    if finish<0: raise RuntimeError("Не найдена граница: "+end[:90])
    return src[begin:finish]

def replace_region(source,reference,start,end,expected):
    fresh=between(reference,start,end)
    old=between(source,start,end)
    if expected not in fresh: raise RuntimeError("Исходник обновления некорректен: "+expected)
    return source.replace(old,fresh,1)

# Keep every unrelated panel path and all Node Lab additions intact.
# The v3 updater accidentally retained the OLD fetch_published implementation
# while installing the NEW verifier. Replace the exact missing function too.
panel=replace_region(panel,reference,"def fetch_published(","def verify_public_asset(","# wpo-publish-v4")
panel=replace_region(panel,reference,"def verify_public_page(","def insert_into_head(","wpo-presets-live-v3")
panel=replace_region(panel,reference,"def externalize_inline_assets(","def hydrate_legacy_assets(","# wpo-presets-live-v3")
panel=replace_region(panel,reference,"def write_site_html(","def custom_presets(","return hashlib.sha256(raw).hexdigest()")
panel=replace_region(panel,reference,
    '        if path==PANEL_PATH+"/apply-preset":',
    '        if path==PANEL_PATH+"/password":',
    '"published_hash":published_hash')

# Synchronize the preview API too, even on older installations.
preview_start='        if path in (PANEL_PATH+"/preview-html",PANEL_PATH+"/save-draft"'
preview_end='        if path==PANEL_PATH+"/add-user":'
panel=replace_region(panel,reference,preview_start,preview_end,
                     'use_preset=path.endswith("/draft-preset")')
new_import="from wpp_panel_extras import preview_document, inline_bundled_preset_photos"
old_import="from wpp_panel_extras import preview_document"
if new_import not in panel:
    if panel.count(old_import)!=1: raise RuntimeError("Импорт предпросмотра неизвестной версии.")
    panel=panel.replace(old_import,new_import,1)

editor='def editor_ui(source, path, csrf, presets, has_draft):'
ui=replace_region(ui,reference_ui,editor,'\ndef openflux_ui(','data-presets-ui="v3"')
compact='# Compact outlined preset gallery'
if compact not in ui:
    css=between(reference_ui,compact,'\ndef editor_ui(')
    ui=ui.replace(editor,css+'\n'+editor,1)
else:
    ui=replace_region(ui,reference_ui,compact,'\ndef editor_ui(',"CSS += '''")

v3='# wpo-presets-compact-v3'
end_v3="CSS += '''\n.node-country-control"
new_v3=between(reference_ui,v3,end_v3)
if v3 not in ui:
    if ui.count(end_v3)!=1: raise RuntimeError("Стили Node Lab отличаются от ожидаемых, изменения отменены.")
    ui=ui.replace(end_v3,new_v3+end_v3,1)
else:
    ui=ui.replace(between(ui,v3,end_v3),new_v3,1)

# No registered Node Lab changes may be discarded.
marks=lambda content:set(re.findall(r'(?:#|/\*) wpo-node-[^\n]+',content))
if not marks(old_panel).issubset(marks(panel)):
    raise RuntimeError("Исправление затрагивает сохранённые ноды; отмена.")
if not marks(old_ui).issubset(marks(ui)):
    raise RuntimeError("Исправление затрагивает интерфейс нод; отмена.")
for target,code in ((panel_path,panel),(ui_path,ui)):
    compile(code,str(target),'exec')
if not all(key in ui for key in ('data-presets-ui="v3"','# wpo-presets-compact-v3','id="presetGallery"',
                               "crypto.subtle.digest('SHA-256',bytes)")):
    raise RuntimeError("Новый интерфейс карточек или браузерная проверка HTTPS отсутствуют.")
if 'inline_bundled_preset_photos(css)' in panel:
    raise RuntimeError("Опубликованный CSS всё ещё содержит небезопасную вставку WebP.")

def atomic_write(path,code):
    fd,temp=tempfile.mkstemp(prefix=".wpo-preset-live-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            out.write(code);out.flush();os.fsync(out.fileno())
        stat=path.stat()
        os.chown(temp,stat.st_uid,stat.st_gid)
        os.chmod(temp,stat.st_mode & 0o777)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

if panel!=old_panel: atomic_write(panel_path,panel)
if ui!=old_ui: atomic_write(ui_path,ui)
print("✓ Обновлена публикация сайта, реальная проверка и карточки v3.")
PY_PATCH
install -o root -g root -m 0644 "$STAGE/wpp_panel_extras.py" "$EXTRAS"
python3 -m py_compile "$PANEL" "$UI" "$EXTRAS"
# Smoke-test actual packaged pages and CSS generation before restarting panel.
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

# Exercise the real CSS transform without starting the panel's HTTP server.
python3 - "$PANEL" "$UI" "$APP" <<'PY_CSS'
import ast,hashlib,importlib.util,os,re,sys
from pathlib import Path
panel=Path(sys.argv[1]).read_text(encoding="utf-8")
module=ast.parse(panel)
function=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=="externalize_inline_assets")
ctx={"re":re,"os":os,"hashlib":hashlib,
     "SITE_INDEX":"/srv/tproxy-site/index.html",
     "insert_into_head":lambda html,tag: html.replace("</head>",tag+"</head>",1)}
exec(compile(ast.Module(body=[function],type_ignores=[]),"<site-test>","exec"),ctx)
sys.path.insert(0,sys.argv[3])
from wpp_presets import presets
cars=next(item for item in presets() if item["id"]=="cars")
html,css,js,css_name,js_name=ctx["externalize_inline_assets"](cars["html"])
assert css_name and "/"+css_name in html, "Stylesheet was not linked"
assert "data:image/webp;base64," not in css, "Published CSS contains forbidden data images"
assert "/preset-car-" in css, "Local car photos missing in stylesheet"
ui=Path(sys.argv[2]).read_text(encoding="utf-8")
assert '# wpo-presets-compact-v3' in ui and 'data-presets-ui="v3"' in ui
import importlib.util
spec=importlib.util.spec_from_file_location("wpo_preset_ui_smoke",sys.argv[2])
ui_module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui_module)
assert "#presetGallery.preset-grid" in ui_module.CSS, "Compact gallery CSS not active"
rendered=ui_module.editor_ui("","/panel-test","test-csrf",presets(),False)
assert 'data-presets-ui="v3"' in rendered and 'preset-apply' in rendered, "Gallery HTML not active"
assert "wpo-presets-ui-v3" in rendered and "new URL('/?wpp-view='" in rendered
assert "crypto.subtle.digest('SHA-256',bytes)" in rendered
assert 'published_hash' in rendered
assert '# wpo-publish-v4' in panel and 'return hashlib.sha256(raw).hexdigest()' in panel
print("✓ Gallery renders compact cards, publishing and SHA-256 browser HTTPS checks.")
print("✓ Published car CSS references real local photos, not blocked data images.")
PY_CSS
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
echo '✓ Presets v4: one-click publish, relay verification + browser HTTPS SHA-256 confirmation.'
echo '✓ User profiles, subscriptions, protocols and Nodes Lab preserved.'
echo "✓ Backup: $BACKUP"
