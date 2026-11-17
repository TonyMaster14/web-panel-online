#!/usr/bin/env bash
# WPO UI-only: manual sign-in, centered button, RU/EN + sun/moon matching controls.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на сервере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=d382a4a56261624cd27b1c19858cbc483ee7cf12
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && -s "$APP/panel.py" && ! -L "$TARGET" ]] || {
  echo 'Интерфейс WPO не найден. Изменений нет.' >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo 'Служба WPO не активна. Изменений нет.' >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-login-i18n.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Ошибка проверки — восстановлена предыдущая версия UI: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/updated.py" <<'PY'
from pathlib import Path
import sys

installed = Path(sys.argv[1]).read_text(encoding='utf-8')
source = Path(sys.argv[2]).read_text(encoding='utf-8')
begin = '# WPO_LOGIN_LANGUAGE_THEME_V1_BEGIN'
end = '# WPO_LOGIN_LANGUAGE_THEME_V1_END'

def section(data, start, stop):
    a = data.find(start)
    if a < 0:
        raise RuntimeError(f'Не найден фрагмент WPO: {start}')
    b = data.find(stop, a + len(start))
    if b < 0 or b <= a:
        raise RuntimeError(f'Не найден конец фрагмента WPO: {stop}')
    return data[a:b]

if source.count(begin) != 1 or source.count(end) != 1 or source.index(begin) >= source.index(end):
    raise RuntimeError('Исходный патч языка и темы повреждён.')
new_patch = source[source.index(begin):source.index(end) + len(end)]
if not all(piece in new_patch for piece in (
    'WPO_I18N_UI_JS', 'CSS +=', '_WPO_LOGIN_LANGUAGE_BASE = login_ui',
    '_WPO_PAGE_LANGUAGE_BASE = page_layout', 'ASSET_REV = ')):
    raise RuntimeError('Не все элементы нового UI присутствуют в источнике.')

start_theme = 'def theme_button():'
end_theme = '\n\ndef page_layout('
start_login = 'def login_ui(path):'
end_login = '\n\ndef hidden(csrf'
if installed.count(start_theme) != 1 or installed.count(end_theme) < 1:
    raise RuntimeError('Функция темы установлена в неизвестном формате.')
old_theme = section(installed, start_theme, end_theme)
new_theme = section(source, start_theme, end_theme)
if old_theme != new_theme:
    if 'data-theme-toggle' not in old_theme or 'theme-track' not in old_theme:
        raise RuntimeError('Неизвестный переключатель темы WPO; изменений нет.')
    installed = installed.replace(old_theme, new_theme, 1)

old_login = section(installed, start_login, end_login)
new_login = section(source, start_login, end_login)
if old_login != new_login:
    if not all(value in old_login for value in (
        'id="loginForm"', 'id="loginPassword"', 'id="loginSubmit"',
        'autocomplete="current-password"', 'form.addEventListener')):
        raise RuntimeError('Неизвестная версия формы входа WPO; изменений нет.')
    installed = installed.replace(old_login, new_login, 1)

def replace_legacy(text, old, new):
    if text.count(old) == 1:
        return text.replace(old, new, 1)
    if text.count(old) == 0 and text.count(new) == 1:
        return text
    raise RuntimeError('Неизвестная версия обработчика темы; изменений нет.')

installed = replace_legacy(
    installed,
    "b.querySelector('span').textContent=light?",
    "b.querySelector('.theme-label').textContent=light?"
)
installed = replace_legacy(
    installed,
    "document.querySelectorAll('[data-theme-toggle] span')",
    "document.querySelectorAll('[data-theme-toggle] .theme-label')"
)

if installed.count(begin) != installed.count(end) or installed.count(begin) > 1:
    raise RuntimeError('Некорректные маркеры ранее установленного переключателя.')
if begin in installed:
    a = installed.index(begin)
    b = installed.index(end, a) + len(end)
    installed = installed[:a] + new_patch + installed[b:]
else:
    installed = installed.rstrip() + '\n\n' + new_patch + '\n'

if installed.count('def login_ui(path):') != 2:
    raise RuntimeError('Не найдена обёртка нового UI входа.')
if 'autoTimer=' in section(installed, start_login, end_login):
    raise RuntimeError('Автоматическая отправка формы не удалена.')
if 'data-wpo-lang="ru"' not in installed or 'wpo-theme-moon' not in installed:
    raise RuntimeError('Переключатели языка и темы не установлены.')
if 'WPO_SELECT_POPOVER_V2_JS' not in installed:
    raise RuntimeError('В WPO отсутствует ожидаемый UI выпадающих списков.')
compile(installed, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(installed, encoding='utf-8')
PY
python3 -m py_compile "$TMP/updated.py"
if cmp -s "$TMP/updated.py" "$TARGET"; then
  echo '✓ Новый вход и переключатели RU/EN и темы уже установлены.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/login-i18n-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-login-i18n.XXXXXXXX.py")"
cp "$TMP/updated.py" "$STAGE"
chown --reference="$TARGET" "$STAGE"
chmod --reference="$TARGET" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$TARGET"
python3 -m py_compile "$TARGET"
systemctl restart "$SERVICE"
READY=0
for i in $(seq 1 18); do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo 'Панель WPO не ответила после обновления; выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Вход с iPhone: автоматическая отправка формы полностью отключена.'
echo '✓ Кнопка «Вход» уменьшена и расположена по центру, стрелка сохранена.'
echo '✓ RU/EN и солнце/луна одинакового размера на странице входа и внутри панели.'
echo '✓ Выбранный язык и тема сохраняются в браузере.'
echo '✓ Затронут только интерфейс. Авторизация, пароли, VPN и подписки не менялись.'
echo "✓ Резервная копия: $BACKUP"
