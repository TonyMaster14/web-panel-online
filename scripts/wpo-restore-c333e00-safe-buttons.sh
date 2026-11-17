#!/usr/bin/env bash
# WPO recovery: pinned known-good c333e00 + isolated RU/EN, theme and native sign-in UI.
# Default --check only builds/validates locally; --apply replaces ONLY wpp_ui.py after backup.
set -Eeuo pipefail
umask 077
MODE="${1:---check}"
if [[ "$MODE" != '--check' && "$MODE" != '--apply' ]]; then
  echo 'Использование: bash wpo-restore-c333e00-safe-buttons.sh [--check|--apply]' >&2
  exit 2
fi
if [[ "$MODE" == '--apply' && "$EUID" -ne 0 ]]; then
  echo 'Для --apply запустите через sudo на VPS с WPO.' >&2
  exit 2
fi
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REPO=https://raw.githubusercontent.com/TonyMaster14/web-panel-online
BASE_REV=c333e00eceb4fa5975e27166d40cee65700d7d86
I18N_REV=4b0bc22f2e9621bd56f7e69e767e85fa22c44cb9
TMP="$(mktemp -d /tmp/wpo-safe-c333e00.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    echo 'Проверка не пройдена. Возвращаю исходный файл интерфейса.' >&2
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Резервная копия: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT

curl -fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' \
  "$REPO/$BASE_REV/src/wpp_ui.py" -o "$TMP/base.py"
curl -fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' \
  "$REPO/$I18N_REV/src/wpp_ui.py" -o "$TMP/i18n-reference.py"

python3 - "$TMP/base.py" "$TMP/i18n-reference.py" "$TMP/patched.py" <<'PY'
from pathlib import Path
import ast
import hashlib
import sys

base_path, i18n_path, out_path = map(Path, sys.argv[1:])
base_bytes = base_path.read_bytes()
i18n_bytes = i18n_path.read_bytes()

def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()

# GitHub blob IDs of both *specific* files, not just the moving branch names.
if git_blob(base_bytes) != 'b0e3e2d041ad1710a261d8da62004a1bd30fb20e':
    raise SystemExit('Проверка исходного c333e00 не прошла. Ничего не изменено.')
if git_blob(i18n_bytes) != 'f016b2e4d1a7de78fa6080c54ca6d4f4e3602c4d':
    raise SystemExit('Проверка источника перевода не прошла. Ничего не изменено.')

s = base_bytes.decode('utf-8')
reference = i18n_bytes.decode('utf-8')

def once(text: str, part: str, label: str) -> None:
    n = text.count(part)
    if n != 1:
        raise RuntimeError(f'Несовместимая структура ({label}): ожидалось 1, найдено {n}')

if '# WPO_SAFE_C333E00_BUTTONS_BEGIN' in s:
    raise RuntimeError('Неверный исходник: патч уже присутствует')
if '# WPO_SELECT_POPOVER_V2_BEGIN' not in s or 'WPO_SELECT_POPOVER_V2_JS' not in s:
    raise RuntimeError('Не найден рабочий контроллер выпадающих списков из c333e00')

# Keep the pre-existing JS theme logic. Only point its two text selectors at
# a dedicated hidden label, never at the new sun/moon SVGs or language controls.
old = "b.querySelector('span').textContent="
new = "b.querySelector('.theme-label').textContent="
once(s, old, 'подпись темы')
s = s.replace(old, new, 1)
old = "document.querySelectorAll('[data-theme-toggle] span')"
new = "document.querySelectorAll('[data-theme-toggle] .theme-label')"
once(s, old, 'обновление темы')
s = s.replace(old, new, 1)

# Replace ONLY the theme control markup. Never touch the section links,
# <select> controls, the global click handlers, or the routing logic.
start = 'def theme_button():'
end = '\n\ndef page_layout('
once(s, start, 'theme_button')
a = s.index(start)
b = s.index(end, a)
theme_button = '''def theme_button():
    return (\'\'\'<div class="wpo-utility-switches" aria-label="Язык и тема">
      <div class="wpo-language-switch" role="group" aria-label="Язык интерфейса">
        <button type="button" data-wpo-lang="ru" aria-pressed="true">RU</button>
        <button type="button" data-wpo-lang="en" aria-pressed="false">EN</button>
      </div>
      <button type="button" class="quiet wpo-theme-pill" data-theme-toggle aria-label="Переключить тему">
        <svg class="wpo-theme-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>
        <svg class="wpo-theme-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.6 15.5A9 9 0 0 1 8.5 3.4 9 9 0 1 0 20.6 15.5Z"/></svg>
        <span class="theme-label" hidden>Тёмная тема</span>
      </button>
    </div>\'\'\')'''
s = s[:a] + theme_button + s[b:]

# Preserve the original server-side login route, password fields and session
# handling. Remove ONLY the auto-login browser JS, making POST fully native.
start = 'def login_ui(path):'
end = '\n\ndef hidden(csrf'
once(s, start, 'login_ui')
a = s.index(start)
b = s.index(end, a)
login = s[a:b]
old = '<button class="primary login-submit" id="loginSubmit"><b>Войти в панель</b>'
new = '<button type="submit" class="primary login-submit" id="loginSubmit"><b>Вход</b>'
once(login, old, 'кнопка входа')
login = login.replace(old, new, 1)
js_start = '<script>(()=>{{const form=document.getElementById(\'loginForm\')'
once(login, js_start, 'старый автологин')
c = login.index(js_start)
d = login.index('</script>', c) + len('</script>')
# The original login_UI return uses a Python f-string. Escaping braces is
# deliberate and the whole patched source is Python-compiled before install.
login_js = '''<script>
(()=>{
 'use strict';
 const form=document.getElementById('loginForm');
 const password=document.getElementById('loginPassword');
 const toggle=document.getElementById('loginPasswordToggle');
 const button=document.getElementById('loginSubmit');
 if(!form||!password||!toggle||!button)return;
 toggle.addEventListener('click',()=>{
   const visible=password.type==='text';
   password.type=visible?'password':'text';
   toggle.textContent=visible?'Показать':'Скрыть';
   toggle.setAttribute('aria-pressed',String(!visible));
   password.focus({preventScroll:true});
 });
 // Native submit: no preventDefault, synthetic click, auto-login or navigation blocker.
 form.addEventListener('submit',()=>{
   const label=button.querySelector('b');
   if(label)label.textContent='Вход…';
 });
})();
</script>'''
login = login[:c] + login_js.replace('{', '{{').replace('}', '}}') + login[d:]
if any(x in login for x in ('autoTimer=', 'watchTimer=', 'requestSubmit(', 'queueAutoLogin')):
    raise RuntimeError('Автоматический вход не удалён')
if 'method="post" action="{esc(path)}/login"' not in login:
    raise RuntimeError('Исходный маршрут входа не сохранён')
s = s[:a] + login + s[b:]

# Bring over ONLY the completed, one-shot RU/EN translator from the later
# source. Do not take its navigation/click interception or its other wrappers.
left = 'WPO_I18N_UI_JS = '
right = '\n_WPO_LOGIN_LANGUAGE_BASE = login_ui'
once(reference, left, 'начало локализации')
once(reference, right, 'конец локализации')
a = reference.index(left)
b = reference.index(right, a)
assignment = reference[a:b]
tree = ast.parse(assignment)
if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
    raise RuntimeError('Неверный формат скрипта RU/EN')
js = ast.literal_eval(tree.body[0].value)
if not all(term in js for term in ('window.wpoSetLanguage=setLanguage;', 'document.addEventListener(\'click\'', 'apply();')):
    raise RuntimeError('Требуемые функции RU/EN отсутствуют')
if 'MutationObserver' in js or 'wppNavigationTimer' in js:
    raise RuntimeError('Небезопасный постоянный обработчик RU/EN')

# Extra CSS is scoped exclusively to the new controls / login / header.
# The working select styles, REALITY controls, forms, links, nodes etc remain
# exactly as in c333e00.
css = r'''
/* WPO_SAFE_C333E00_BUTTONS: purely visual additions */
.wpo-utility-switches{display:inline-flex!important;align-items:center!important;gap:12px!important;flex:0 0 auto;min-width:0}
.wpo-utility-switches .wpo-language-switch{box-sizing:border-box!important;display:flex!important;align-items:center!important;width:90px!important;min-width:90px!important;height:38px!important;padding:3px!important;margin:0!important;border:1px solid var(--line)!important;border-radius:999px!important;background:var(--input)!important}
.wpo-utility-switches .wpo-language-switch button{box-sizing:border-box!important;display:grid!important;place-items:center!important;flex:1 1 0!important;min-width:0!important;height:30px!important;min-height:30px!important;padding:0!important;margin:0!important;border:0!important;border-radius:999px!important;background:transparent!important;color:var(--muted)!important;font:700 11px/1 system-ui,sans-serif!important;cursor:pointer!important;transform:none!important;box-shadow:none!important}
.wpo-utility-switches .wpo-language-switch button[aria-pressed="true"]{background:var(--text)!important;color:var(--input)!important;box-shadow:0 1px 4px #0002!important}
.wpo-utility-switches .wpo-language-switch button:focus-visible,.wpo-utility-switches .wpo-theme-pill:focus-visible{outline:2px solid var(--accent)!important;outline-offset:2px!important}
.wpo-utility-switches button.wpo-theme-pill{box-sizing:border-box!important;display:inline-flex!important;align-items:center!important;justify-content:center!important;flex:0 0 38px!important;width:38px!important;min-width:38px!important;max-width:38px!important;height:38px!important;min-height:38px!important;max-height:38px!important;padding:0!important;margin:0!important;border:1px solid var(--line)!important;border-radius:50%!important;background:var(--input)!important;color:var(--text)!important;cursor:pointer!important;transform:none!important}
.wpo-utility-switches .wpo-theme-pill .theme-label{display:none!important}
.wpo-utility-switches .wpo-theme-pill svg{display:block!important;width:18px!important;height:18px!important;flex:0 0 18px!important}
:root[data-theme="light"] .wpo-utility-switches .wpo-theme-moon{display:none!important}
:root:not([data-theme="light"]) .wpo-utility-switches .wpo-theme-sun{display:none!important}
.login-theme{position:fixed!important;top:14px!important;right:34px!important;z-index:15}
.appbar-tools{display:flex!important;align-items:center!important;justify-content:flex-end!important;gap:6px!important;padding-right:8px!important;min-width:0}
.appbar-tools .wpo-utility-switches{margin:0!important}
.appbar-tools .social-icon,.appbar-tools a.logout{position:relative!important;z-index:2!important;pointer-events:auto!important;flex:0 0 38px!important;width:38px!important;min-width:38px!important;height:38px!important;box-sizing:border-box!important;display:grid!important;place-items:center!important;padding:8px!important}
.login-card #loginSubmit{position:relative!important;display:flex!important;align-items:center!important;justify-content:center!important;box-sizing:border-box!important;width:min(184px,100%)!important;min-height:43px!important;height:43px!important;padding:0 34px!important;gap:0!important;margin:6px auto 0!important;cursor:pointer!important;pointer-events:auto!important;touch-action:manipulation;z-index:2!important}
.login-card #loginSubmit b{font-size:17px!important;font-weight:750!important;line-height:1.2!important;text-align:center!important}
.login-card #loginSubmit span{position:absolute!important;right:14px!important;top:50%!important;transform:translateY(-50%)!important;line-height:1!important;font-size:18px!important;pointer-events:none!important}
.login-card #loginSubmit:hover span{transform:translate(2px,-50%)!important}
@media(max-width:1180px){.appbar{grid-template-columns:minmax(0,1fr) auto!important;gap:8px!important}.appbar-left{grid-column:1;grid-row:1;min-width:0}.appbar-tools{grid-column:2;grid-row:1}.topnav{grid-column:1/-1;grid-row:2;width:100%}}
@media(max-width:700px){.appbar{padding:10px 10px 8px!important;gap:7px!important}.appbar-left .host{display:none!important}.appbar-tools{gap:4px!important;padding-right:6px!important}.appbar-tools .social-icon,.appbar-tools a.logout{flex:0 0 34px!important;width:34px!important;min-width:34px!important;height:36px!important;padding:7px!important}.wpo-utility-switches{gap:10px!important}.wpo-utility-switches .wpo-language-switch{width:82px!important;min-width:82px!important;height:36px!important}.wpo-utility-switches .wpo-language-switch button{height:28px!important;min-height:28px!important}.wpo-utility-switches button.wpo-theme-pill{flex:0 0 36px!important;width:36px!important;min-width:36px!important;max-width:36px!important;height:36px!important;min-height:36px!important;max-height:36px!important}.login-theme{top:12px!important;right:22px!important}}
@media(max-width:355px){.appbar-tools{gap:3px!important}.appbar-tools .social-icon{display:grid!important}.wpo-utility-switches{gap:8px!important}}
@media(prefers-reduced-motion:reduce){.wpo-utility-switches button{transition:none!important}}
'''
# Use Python's repr for a safe CSS string literal. No JavaScript handlers here.
patch = '''\n\n# WPO_SAFE_C333E00_BUTTONS_BEGIN\n'''
patch += 'CSS += ' + repr('\n' + css) + '\n'
patch += assignment + '\n'
patch += '''
_WPO_C333_LOGIN_BASE = login_ui
def login_ui(path):
    return _WPO_C333_LOGIN_BASE(path).replace('</body></html>', WPO_I18N_UI_JS + '</body></html>', 1)
_WPO_C333_PAGE_BASE = page_layout
def page_layout(*args, **kwargs):
    return _WPO_C333_PAGE_BASE(*args, **kwargs).replace('</body></html>', WPO_I18N_UI_JS + '</body></html>', 1)
ASSET_REV = hashlib.sha256((CSS + COMMON_JS + globals().get('WPO_SELECT_POPOVER_V2_JS', '') + WPO_I18N_UI_JS).encode('utf-8')).hexdigest()[:12]
# WPO_SAFE_C333E00_BUTTONS_END
'''
s += patch
ast.parse(s, filename=str(out_path))
compile(s, str(out_path), 'exec')
# Guard behavior: do not accidentally drop the proven working select engine
# or sneak in the broken navigation recovery wrappers.
if s.count('# WPO_SELECT_POPOVER_V2_BEGIN') != 1 or 'WPO_NATIVE_NAV_JS =' in s:
    raise RuntimeError('Рабочие списки или навигация были затронуты')
if 'document.addEventListener(\'click\',event=>' in patch:
    raise RuntimeError('Найден нежелательный перехватчик навигации')
if s.count('# WPO_SAFE_C333E00_BUTTONS_BEGIN') != 1:
    raise RuntimeError('Не удалось безопасно применить изолированные правки')
out_path.write_text(s, encoding='utf-8')
print('✓ Основа: c333e00 (проверен Git blob SHA-1).')
print('✓ Полный RU/EN: только перевод при загрузке и по клику, без MutationObserver.')
print('✓ Тема: штатный обработчик, те же настройки браузера.')
print('✓ Вход: штатный POST, без автологина и JS-перехвата submit.')
print('✓ Выпадающие списки, протоколы и навигация остались от рабочей версии.')
PY

python3 -m py_compile "$TMP/patched.py"
if [[ "$MODE" == '--check' ]]; then
  echo '✓ Проверка Python пройдена. На сервере ничего не менялось.'
  echo 'Для установки: sudo bash wpo-restore-c333e00-safe-buttons.sh --apply'
  exit 0
fi
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || {
  echo 'Не распознана установленная WPO. Ничего не изменено.' >&2
  exit 2
}
if cmp -s "$TMP/patched.py" "$TARGET"; then
  echo '✓ Этот восстановленный интерфейс уже установлен.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/c333e00-buttons-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-c333e00.XXXXXXXX.py")"
cp "$TMP/patched.py" "$STAGE"
chown --reference="$TARGET" "$STAGE"
chmod --reference="$TARGET" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$TARGET"
python3 -m py_compile "$TARGET"
systemctl restart "$SERVICE"
READY=0
for i in $(seq 1 24); do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
if (( ! READY )); then
  echo 'Не удалось проверить HTTP-ответ WPO после перезапуска.' >&2
  exit 4
fi
CHANGED=0
echo '✓ WPO отвечает. Интерфейс восстановлен на базе c333e00 с новыми кнопками.'
echo 'Проверьте в браузере вкладки, выбор протокола/ноды, домены, RU/EN и вход.'
echo "Резервная копия предыдущего интерфейса: $BACKUP"