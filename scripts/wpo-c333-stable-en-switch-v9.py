#!/usr/bin/env python3
"""WPO: stop the RU-to-EN selector jump on full-page navigation.

Requires the existing c333e00 safe UI + i18n v8. Changes no navigation,
protocols, nodes, customers or settings. Updates only wpp_ui.py.
"""
import ast
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

APP=Path("/opt/tproxy-panel")
TARGET=APP/"wpp_ui.py"
SERVICE="tproxy-panel.service"
BASE="# WPO_C333_I18N_V8_PRELOAD"
MARK="# WPO_C333_V9_STABLE_SELECTOR"

# Injected after the original v8 function. V8 page_layout/login_ui wrappers
# look this function up at request time, so all pages receive the patch.
ADDON = r"""
# WPO_C333_V9_STABLE_SELECTOR
_WPO_C333_V9_BASE_PREFLIGHT = _wpo_c333_v8_safari_preflight

def _wpo_c333_v8_safari_preflight(markup):
    markup = _WPO_C333_V9_BASE_PREFLIGHT(markup)
    old_style = '<style>html.wpo-en-prepaint body{visibility:hidden!important}</style>'
    css = (
      '<style>'
      'html.wpo-en-prepaint main{visibility:hidden!important}'
      'html[data-wpo-language="en"] .wpo-utility-switches .wpo-language-switch button[data-wpo-lang="en"],'
      'html[data-wpo-language="ru"] .wpo-utility-switches .wpo-language-switch button[data-wpo-lang="ru"]'
      '{background:var(--text)!important;color:var(--input)!important;box-shadow:0 1px 5px #0002!important}'
      'html[data-wpo-language="en"] .wpo-utility-switches .wpo-language-switch button[data-wpo-lang="ru"],'
      'html[data-wpo-language="ru"] .wpo-utility-switches .wpo-language-switch button[data-wpo-lang="en"]'
      '{background:transparent!important;color:var(--muted)!important;box-shadow:none!important}'
      '</style>'
    )
    old_script = (
      '<script>(function(){try{if(localStorage.getItem("wpo-language")==="en"){'
      'document.documentElement.classList.add("wpo-en-prepaint");'
      'setTimeout(function(){document.documentElement.classList.remove("wpo-en-prepaint")},1400)'
      '}}catch(e){}})();</script>'
    )
    new_script = (
      '<script>(function(){'
      'var l="ru";try{l=localStorage.getItem("wpo-language")==="en"?"en":"ru"}catch(e){}'
      'document.documentElement.dataset.wpoLanguage=l;'
      'if(l==="en"){document.documentElement.classList.add("wpo-en-prepaint");'
      'setTimeout(function(){document.documentElement.classList.remove("wpo-en-prepaint")},1400)}'
      '})();</script>'
    )
    if markup.count(old_style)!=1 or markup.count(old_script)!=1:
        raise RuntimeError("WPO v8 pre-render markup does not match; nothing replaced")
    return markup.replace(old_style,css,1).replace(old_script,new_script,1)

# Keep the selected pill correct on initial load and update it immediately on
# a real language-button click (without delaying for text translation).
if WPO_C333_I18N_JS.count('function updateControls(){') != 1:
    raise RuntimeError("WPO translation controls changed unexpectedly")
if WPO_C333_I18N_JS.count('  language=next;\n') != 1:
    raise RuntimeError("WPO language click logic changed unexpectedly")
WPO_C333_I18N_JS = WPO_C333_I18N_JS.replace(
    'function updateControls(){',
    'function updateControls(){\n  document.documentElement.dataset.wpoLanguage=language;',1
).replace(
    '  language=next;\n',
    '  language=next;\n  document.documentElement.dataset.wpoLanguage=language;\n',1
)
"""

def check_source(original):
    if BASE not in original or "# WPO_C333_LANGUAGE_THEME_V1" not in original:
        raise RuntimeError("WPO v8 or language controls missing. Nothing will be changed.")
    if "# WPO_NAV_NATIVE_RECOVERY_V2_BEGIN" in original:
        raise RuntimeError("An incompatible legacy patch is present.")
    if original.count("def _wpo_c333_v8_safari_preflight(markup):") != 1:
        raise RuntimeError("Expected one Safari helper from v8.")
    if "WPO_C333_I18N_JS = " not in original or "WPO_SELECT_POPOVER_V2_BEGIN" not in original:
        raise RuntimeError("Safe WPO i18n and original selectors were not detected.")
    if "wppNavigationTimer" not in original:
        raise RuntimeError("Original WPO navigation marker missing.")

def compile_check(original):
    check_source(original)
    if MARK in original:
        return original, True
    updated=original+"\n"+ADDON
    ast.parse(updated,filename=str(TARGET))
    compile(updated,str(TARGET),"exec")
    for term in ("def routing_ui(","def theme_button():","# WPO_SELECT_POPOVER_V2_BEGIN","wppNavigationTimer"):
        if original.count(term)!=updated.count(term):
            raise RuntimeError("Unexpected change to working WPO code: "+term)
    return updated, False

def healthy():
    if subprocess.run(["systemctl","is-active","--quiet",SERVICE]).returncode:
        return False
    try:
        try:
            resp=urlopen("http://127.0.0.1:8090/",timeout=2)
            code=resp.status
            resp.close()
        except HTTPError as e:
            code=e.code
        return 200<=code<500
    except Exception:
        return False

def main():
    mode=sys.argv[1] if len(sys.argv)==2 else ""
    if mode not in ("--check","--apply"):
        raise SystemExit("Usage: --check | --apply")
    if mode=="--apply" and os.geteuid()!=0:
        raise SystemExit("Run this patch with sudo.")
    if not TARGET.is_file() or TARGET.is_symlink() or not (APP/"panel.py").is_file():
        raise SystemExit("The existing WPO installation was not found.")
    current=TARGET.read_text(encoding="utf-8")
    updated,already=compile_check(current)
    if already:
        print("✓ The stable RU/EN switch is already installed.")
        return
    print("✓ WPO v8 base verified. Stable EN control patch is compatible.")
    if mode=="--check":
        print("✓ Check-only mode: no changes made.")
        return
    if not healthy():
        raise RuntimeError("WPO is not responding before the patch. Nothing changed.")
    backup=Path("/var/backups/web-panel-online")/("lang-selector-v9-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+str(os.getpid()))
    backup.mkdir(parents=True,mode=0o700,exist_ok=False)
    shutil.copy2(TARGET,backup/"wpp_ui.py")
    descriptor,temp=tempfile.mkstemp(prefix=".wpo-lang-v9-",suffix=".py",dir=APP)
    try:
        with os.fdopen(descriptor,"w",encoding="utf-8") as dst:
            dst.write(updated)
        file_stat=TARGET.stat()
        os.chmod(temp,stat.S_IMODE(file_stat.st_mode))
        os.chown(temp,file_stat.st_uid,file_stat.st_gid)
        os.replace(temp,TARGET)
        subprocess.run(["systemctl","restart",SERVICE],check=True)
        for _ in range(20):
            if healthy():
                print("✓ Stable EN language switch installed.")
                print("✓ UI backup: "+str(backup/"wpp_ui.py"))
                return
            time.sleep(1)
        raise RuntimeError("The panel did not respond after the patch.")
    except Exception:
        shutil.copy2(backup/"wpp_ui.py",TARGET)
        subprocess.run(["systemctl","restart",SERVICE],check=False)
        print("✖ Restored the previous WPO UI from backup.",file=sys.stderr)
        raise
    finally:
        if os.path.exists(temp):os.unlink(temp)

if __name__=="__main__":
    main()
