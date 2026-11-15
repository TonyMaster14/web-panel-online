#!/usr/bin/env bash
# Test only: fix registered node disappearing after concurrent status polling.
# Run on controller VPS; do NOT run on additional node servers.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основной панели WPO.' >&2; exit 1; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
SERVICE=tproxy-panel.service
[[ -f "$PANEL" && ! -L "$PANEL" ]] || {
  echo 'Основная панель WPO не найдена. Ничего не изменено.' >&2; exit 2;
}
command -v python3 >/dev/null && command -v curl >/dev/null || exit 2
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба WPO отсутствует.' >&2; exit 2; }
PATCH="$(mktemp /tmp/wpo-node-registry-patch.XXXXXXXX.py)"
STAGE="$(mktemp "$APP/.wpo-registry-fixed.XXXXXXXX.py")"
BACKUP=""
CHANGED=0
cleanup(){
  local code=$?
  trap - EXIT
  if (( code != 0 && CHANGED == 1 )) && [[ -f "$BACKUP" ]]; then
    cp -a -- "$BACKUP" "$PANEL"
    systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    echo 'Обновление не удалось. Исходная панель восстановлена.' >&2
  fi
  rm -f -- "$PATCH" "$STAGE"
  exit "$code"
}
trap cleanup EXIT
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 10 --max-time 90 \
  'https://raw.githubusercontent.com/TonyMaster14/web-panel-online/test/wpo-smooth-progress-v1/scripts/wpo-node-registration-race-fix.py' -o "$PATCH"
python3 "$PATCH" --panel "$PANEL" --out "$STAGE"
python3 -m py_compile "$STAGE"
if cmp -s "$STAGE" "$PANEL"; then
  echo 'Исправление уже установлено, перезапуск не требуется.'
  exit 0
fi
install -d -m 0700 /var/backups/web-panel-online
BACKUP="/var/backups/web-panel-online/panel-before-node-registry-fix-$(date -u +%Y%m%dT%H%M%SZ)-$$.py"
cp -a -- "$PANEL" "$BACKUP"
chmod --reference="$PANEL" "$STAGE"
chown --reference="$PANEL" "$STAGE"
mv -f -- "$STAGE" "$PANEL"
CHANGED=1
systemctl restart "$SERVICE"
systemctl is-active --quiet "$SERVICE" || {
  echo 'Служба панели не запустилась. Восстанавливаю резервную копию.' >&2
  exit 4
}
CHANGED=0
echo 'WPO: исправлена потеря карточек нод при регистрации.'
echo 'Действующие ноды, их ключи, профиль и шаблоны не изменены.'
echo "Резервная копия: $BACKUP"
