#!/usr/bin/env bash
# WPO UI-only login repair: direct native POST only on explicit click/Enter.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запусти через sudo на основном сервере WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
REV=509c57bca4a4f91f02c849c821862675347895de
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpp_ui.py"
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || { echo 'Интерфейс WPO не найден. Изменений нет.' >&2; exit 2; }
systemctl is-active --quiet "$SERVICE" || { echo 'Служба WPO не активна. Изменений нет.' >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-login-direct-v4.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Ошибка проверки. Предыдущий интерфейс восстановлен: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap finish EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' "$URL" -o "$TMP/source.py"
python3 - "$TARGET" "$TMP/source.py" "$TMP/updated.py" <<'PY'
from pathlib import Path
import sys

target = Path(sys.argv[1]).read_text(encoding='utf-8')
source = Path(sys.argv[2]).read_text(encoding='utf-8')

def section(data, left, right):
    a = data.find(left)
    if a < 0:
        raise RuntimeError('Не найден фрагмент формы входа WPO: ' + left)
    b = data.find(right, a + len(left))
    if b < 0:
        raise RuntimeError('Не найден конец формы входа WPO.')
    return data[a:b]

left = 'def login_ui(path):'
right = '\n\ndef hidden(csrf'
new_login = section(source, left, right)
old_login = section(target, left, right)
if not all(x in old_login for x in (
        'id="loginForm"', 'id="loginSubmit"', 'id="loginPassword"',
        'autocomplete="current-password"', 'method="post"')):
    raise RuntimeError('Неизвестная версия формы входа; изменения остановлены.')
if not all(x in new_login for x in (
        '<button type="button" class="primary login-submit"',
        'HTMLFormElement.prototype.submit.call(form)',
        'method="post"', 'action="{esc(path)}/login"')):
    raise RuntimeError('Загружен некорректный патч входа.')
if 'autoTimer=' in new_login or 'requestSubmit(' in new_login or "form.addEventListener('submit'" in new_login:
    raise RuntimeError('В новой форме обнаружена нежелательная автоматическая отправка.')
target = target.replace(old_login, new_login, 1)

# Remove older click/submit gate; it may intercept a legitimate iPhone tap.
old_begin = '# WPO_LOGIN_SAFE_SUBMIT_V2_BEGIN'
old_end = '# WPO_LOGIN_SAFE_SUBMIT_V2_END'
if target.count(old_begin) != target.count(old_end) or target.count(old_begin) > 1:
    raise RuntimeError('Повреждены маркеры старого перехватчика авторизации.')
if old_begin in target:
    a = target.index(old_begin)
    b = target.index(old_end, a) + len(old_end)
    target = target[:a].rstrip() + '\n\n' + target[b:].lstrip('\n')

begin = '# WPO_LOGIN_DIRECT_POST_SPACING_V4_BEGIN'
end = '# WPO_LOGIN_DIRECT_POST_SPACING_V4_END'
if source.count(begin) != 1 or source.count(end) != 1 or source.index(begin) >= source.index(end):
    raise RuntimeError('Исходный UI-патч V4 не найден.')
patch = source[source.index(begin):source.index(end)+len(end)]
if not all(x in patch for x in ('CSS +=', 'gap:12px!important', 'right:34px!important', 'ASSET_REV =')):
    raise RuntimeError('В исходном UI-патче отсутствуют требуемые стили.')
if target.count(begin) != target.count(end) or target.count(begin) > 1:
    raise RuntimeError('Повторные маркеры UI-патча повреждены.')
if begin in target:
    a = target.index(begin)
    b = target.index(end, a)+len(end)
    target = target[:a] + patch + target[b:]
else:
    target = target.rstrip() + '\n\n' + patch + '\n'

if target.count('HTMLFormElement.prototype.submit.call(form)') != 1 or target.count('id="loginSubmit"') != 1:
    raise RuntimeError('Новый вход не подключён либо продублирован.')
compile(target, sys.argv[3], 'exec')
Path(sys.argv[3]).write_text(target, encoding='utf-8')
PY
python3 -m py_compile "$TMP/updated.py"
if cmp -s "$TARGET" "$TMP/updated.py"; then
  echo '✓ Исправление входа и отступов уже установлено.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/login-direct-v4-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-login-direct.XXXXXXXX.py")"
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
(( READY )) || { echo 'WPO не ответила после обновления. Выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ Кнопка «Вход» отправляет POST только при нажатии или Enter в поле пароля.'
echo '✓ Автологина и прежнего перехватчика отправки больше нет.'
echo '✓ Между RU/EN и темой увеличен отступ; блок отодвинут от правого края.'
echo '✓ Настройки аккаунтов, сессий, VPN и main не изменены.'
echo "✓ Резервная копия: $BACKUP"
