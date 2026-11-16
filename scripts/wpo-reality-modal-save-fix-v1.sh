#!/usr/bin/env bash
# WPO test branch: fix REALITY modal Save, Cancel and layout on controller.
# Does NOT touch Xray, HAProxy, node installations, users or subscriber secrets.
set -Eeuo pipefail
umask 077
if (( EUID != 0 )); then echo "Запустите с sudo на основной панели WPO." >&2; exit 2; fi
APP=/opt/tproxy-panel
MODULE="$APP/wpo_reality_ui.py"
SERVICE=tproxy-panel.service
REV=bccb93d43b6622f32ae4389b98433b15fd58cbd6
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpo_reality_ui.py"
if [[ ! -f "$APP/panel.py" || ! -f "$MODULE" || -L "$MODULE" ]]; then
  echo "Не найдена основная панель с модулями REALITY. Ничего не изменено." >&2
  exit 2
fi
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "Служба основной панели не запущена. Ничего не изменено." >&2
  exit 2
fi
TMP="$(mktemp -d /tmp/wpo-reality-modal.XXXXXXXX)"
BACKUP=""
INSTALLED=0
cleanup(){
  local code=$?
  trap - EXIT
  if (( code != 0 && INSTALLED == 1 )) && [[ -n "$BACKUP" && -f "$BACKUP/wpo_reality_ui.py" ]]; then
    cp -a "$BACKUP/wpo_reality_ui.py" "$MODULE" || true
    systemctl restart "$SERVICE" || true
    echo "WPO: старый модуль REALITY восстановлен из $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$code"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' \
  "$URL" -o "$TMP/wpo_reality_ui.py"
python3 -m py_compile "$TMP/wpo_reality_ui.py"
grep -Fq "const reuse=save&&verified?.key===key" "$TMP/wpo_reality_ui.py" &&
grep -Fq "function requestStop()" "$TMP/wpo_reality_ui.py" &&
grep -Fq "overflow-y:auto;overscroll-behavior:contain" "$TMP/wpo_reality_ui.py" &&
grep -Fq "if(closeAfterStop&&!restoreFailed)d.close()" "$TMP/wpo_reality_ui.py" ||
  { echo "Скачан неподходящий модуль REALITY. Ничего не изменено." >&2; exit 3; }
if cmp -s "$TMP/wpo_reality_ui.py" "$MODULE"; then
  echo "WPO: исправление модального окна REALITY уже установлено."
  exit 0
fi
install -d -m 0700 /var/backups/web-panel-online
BACKUP="/var/backups/web-panel-online/reality-modal-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$MODULE" "$BACKUP/wpo_reality_ui.py"
echo "Резервная копия: $BACKUP"
STAGE="$(mktemp "$APP/.wpo-reality-modal.XXXXXXXX.py")"
cp "$TMP/wpo_reality_ui.py" "$STAGE"
chown --reference="$MODULE" "$STAGE"
chmod --reference="$MODULE" "$STAGE"
INSTALLED=1
mv -f "$STAGE" "$MODULE"
python3 -m py_compile "$MODULE"
systemctl restart "$SERVICE"
HEALTHY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet "$SERVICE"; then
    STATUS="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' \
                http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$STATUS" =~ ^[234][0-9][0-9]$ ]]; then HEALTHY=1; break; fi
  fi
  sleep 1
done
if (( HEALTHY != 1 )); then
  echo "Служба панели не прошла проверку после обновления." >&2
  exit 4
fi
INSTALLED=0
echo "✓ REALITY: Сохранить применяет настройки после однократной проверки."
echo "✓ Крестик доступен; прерывание применения запускает откат затронутых нод."
echo "✓ Окно не меняет высоту; кнопки закреплены, результаты прокручиваются."
echo "✓ Синяя обводка полей заменена нейтральной."
echo "Профили пользователей, UUID, ключи, SNI и настройки нод не изменялись."
