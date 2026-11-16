#!/usr/bin/env bash
# WPO TEST: restore predictable one-node-at-a-time REALITY Check and Save.
# Controller UI only. Shared by Connections and Nodes. No VPN config changes.
set -Eeuo pipefail
umask 077
if (( EUID != 0 )); then
  echo 'Запустите с sudo на основном VPS WEB PANEL ONLINE.' >&2
  exit 2
fi
APP=/opt/tproxy-panel
MODULE="$APP/wpo_reality_ui.py"
SERVICE=tproxy-panel.service
REV=e6ba37ae3774c31f398ca9a58295ea47c57aebc3
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpo_reality_ui.py"
[[ -s "$APP/panel.py" && -s "$MODULE" && ! -L "$MODULE" ]] ||
  { echo 'Основная панель с REALITY не найдена. Ничего не изменено.' >&2; exit 2; }
systemctl is-active --quiet "$SERVICE" ||
  { echo 'Служба панели неактивна. Ничего не изменено.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-sequential.XXXXXXXX)"
BACKUP=""
CHANGED=0
finish(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -f "$BACKUP/wpo_reality_ui.py" ]]; then
    cp -a "$BACKUP/wpo_reality_ui.py" "$MODULE" || true
    systemctl restart "$SERVICE" || true
    echo "Неудачное обновление REALITY: старая версия восстановлена из $BACKUP" >&2
  fi
  rm -rf -- "$WORK"
  exit "$rc"
}
trap finish EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 75 --proto '=https' \
  "$URL" -o "$WORK/wpo_reality_ui.py"
python3 -m py_compile "$WORK/wpo_reality_ui.py"
grep -Fq "Walk the visible node list in order" "$WORK/wpo_reality_ui.py" &&
grep -Fq "Apply and read back one node at a time" "$WORK/wpo_reality_ui.py" &&
grep -Fq "const reuse=save&&verified?.key===key" "$WORK/wpo_reality_ui.py" &&
grep -Fq "function requestStop()" "$WORK/wpo_reality_ui.py" &&
grep -Fq "editor(path,csrf,public_nodes,fleet=True)" "$WORK/wpo_reality_ui.py" &&
grep -Fq "for(const n of attempted.reverse())" "$WORK/wpo_reality_ui.py" ||
  { echo 'Неверная версия упорядоченного REALITY. Ничего не изменено.' >&2; exit 3; }
if grep -Eq 'Promise[.]all(Settled)?[(]' "$WORK/wpo_reality_ui.py"; then
  echo 'В обновлении обнаружены параллельные запросы. Остановлено.' >&2
  exit 3
fi
if cmp -s "$WORK/wpo_reality_ui.py" "$MODULE"; then
  echo 'WPO REALITY: последовательные Проверить цель и Сохранить уже установлены.'
  exit 0
fi
install -d -m 0700 /var/backups/web-panel-online
BACKUP="/var/backups/web-panel-online/reality-sequential-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$MODULE" "$BACKUP/wpo_reality_ui.py"
echo "Резервная копия: $BACKUP"
STAGE="$(mktemp "$APP/.wpo-real-sequential.XXXXXXXX.py")"
cp "$WORK/wpo_reality_ui.py" "$STAGE"
chown --reference="$MODULE" "$STAGE"
chmod --reference="$MODULE" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$MODULE"
python3 -m py_compile "$MODULE"
systemctl restart "$SERVICE"
READY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet "$SERVICE"; then
    STATUS="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' \
      http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$STATUS" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo 'Панель не ответила после обновления.' >&2; exit 4; }
CHANGED=0
echo '✓ Проверить цель: одна нода за другой в порядке списка.'
echo '✓ Сохранить: одна нода за другой в том же порядке, с подтверждением записи.'
echo '✓ Подключения и Ноды используют одно и то же модальное окно.'
echo '✓ Крестик, откат, скруглённые полосы прокрутки и неподвижные кнопки сохранены.'
echo '✓ Пользователи, UUID, SNI, подписки, Xray и удалённые ноды не менялись.'
