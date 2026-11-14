#!/usr/bin/env bash
# WPO test controller update: exact selected-node Happ feed + pinned 8-engine node installer.
# Existing users, subscription keys, Caddy, Xray and nodes remain unchanged.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Нужен sudo на основном VPS с WPO.' >&2; exit 1; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
SUBS="$APP/wpp_subscriptions.py"
REMOTE="$APP/wpo_node_remote.py"
AGENT="$APP/wpp-node-agent-install.sh"
SERVICE=tproxy-panel.service
[[ -s "$PANEL" && -s "$SUBS" && -s "$REMOTE" && -s "$AGENT" ]] || {
  echo 'Требуется WPO с ранее установленной формой v28 и удалёнными профилями.' >&2
  echo 'Ничего не изменено.' >&2
  exit 2
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Другое обновление WPO выполняется.' >&2; exit 2; }

PATCH_REV=2ff2b2c0fc6dfcb859894a2cb4419382c8b553da
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$PATCH_REV"
TMP="$(mktemp -d /tmp/wpo-exact-nodes.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/nodes-routing-backup-$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && ROLLBACK == 1 )); then
    echo 'Ошибка обновления — возвращаю предыдущий код и установщик ноды.' >&2
    cp -a "$BACKUP/panel.py" "$PANEL" || true
    cp -a "$BACKUP/wpp-node-agent-install.sh" "$AGENT" || true
    rm -f "$APP"/__pycache__/panel.*.pyc
    systemctl restart "$SERVICE" || true
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 15 --max-time 90 \
  "$BASE/wpo_node_selection_v2.py" -o "$TMP/wpo_node_selection_v2.py"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 15 --max-time 90 \
  "$BASE/wpo-node-agent-install-v2.sh" -o "$TMP/wpp-node-agent-install.sh"
python3 -m py_compile "$TMP/wpo_node_selection_v2.py"
bash -n "$TMP/wpp-node-agent-install.sh"
grep -Fq '# wpo-node-agent-eight-pinned-v1:' "$TMP/wpp-node-agent-install.sh" || {
  echo 'Неверная версия установщика восьми протоколов.' >&2; exit 3;
}
grep -Fq 'expected={"federation","vless","hysteria","web","mtproto","awg20","awg31","naive","mieru"}' \
  "$TMP/wpp-node-agent-install.sh" || { echo 'Нет проверки всех восьми протоколов.' >&2; exit 3; }

python3 "$TMP/wpo_node_selection_v2.py" \
  --panel "$PANEL" --subscriptions "$SUBS" --output "$TMP/panel.py"
python3 -m py_compile "$TMP/panel.py"
grep -Fq '# wpo-exact-node-selection-v1' "$TMP/panel.py"
grep -Fq 'local_count=len(result["users"]) if local_selected else 0' "$TMP/panel.py"

install -d -o root -g root -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$AGENT" "$BACKUP/wpp-node-agent-install.sh"
ROLLBACK=1
install -o root -g root -m 0755 "$TMP/panel.py" "$PANEL"
install -o root -g root -m 0700 "$TMP/wpp-node-agent-install.sh" "$AGENT"
rm -f "$APP"/__pycache__/panel.*.pyc

systemctl restart "$SERVICE"
PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-z0-9-]{3,64}$ ]] || {
  echo 'Не удалось определить скрытый путь WPO. Выполняется откат.' >&2; exit 3;
}
OK=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet "$SERVICE" &&
     curl -4fsS --max-time 3 "http://127.0.0.1:8090$PANEL_PATH/__health" | grep -qx 'OK'; then
    OK=1
    break
  fi
  sleep 1
done
(( OK==1 )) || { echo 'WPO не ответила после обновления. Выполняется откат.' >&2; exit 3; }
cmp -s "$TMP/panel.py" "$PANEL" || { echo 'Установленный код не совпал.' >&2; exit 3; }
cmp -s "$TMP/wpp-node-agent-install.sh" "$AGENT" || { echo 'Установщик ноды не совпал.' >&2; exit 3; }
ROLLBACK=0
echo '✓ WPO: выбор VPN-нод строго применяется к подписке Happ.'
echo '✓ Для двух разных нод включается автовыбор, для одной — нет.'
echo '✓ Ошибочные и неполные профили удалённых нод не выдаются.'
echo '✓ Новый установщик ноды устанавливает 8 реальных серверных протоколов.'
echo '✓ Регистрация ноды только после проверки её восьми движков.'
echo '✓ Клиенты, ключи, подписки и работающий Xray не изменялись.'
echo "Резервная копия: $BACKUP"
echo 'Обновите вкладку WPO, затем генерируйте установщик новой ноды.'
