#!/usr/bin/env bash
# WPO: restore future node site templates by updating the controller installer
# only. No SSH to nodes, no passwords, no remote changes, no VPN restarts.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запустите от root на основном VPS WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
TARGET="$APP/wpp-node-agent-install.sh"
[[ -s "$PANEL" && -s "$TARGET" && ! -e /etc/wpp-node-agent/config.json ]] || {
  echo 'Требуется ОСНОВНАЯ панель WPO; ноды или другая установка не изменялись.' >&2
  exit 2
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Уже выполняется обновление WPO.' >&2; exit 2; }

# Both revisions are immutable commits tested in the WPO test branch.
INSTALL_REV=a3bcb61506c9813c473a01cd968238c667857a23
ENGINE_REV=5f497290fe041149521b7d6006a1dd5b2e833885
BASE=https://raw.githubusercontent.com/TonyMaster14/web-panel-online
WORK="$(mktemp -d /tmp/wpo-node-templates.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/node-template-installer-backup-$(date -u +%Y%m%dT%H%M%SZ)"
cleanup(){ rm -rf -- "$WORK"; }
trap cleanup EXIT

curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 15 --max-time 90 \
  "$BASE/$INSTALL_REV/wpo-node-agent-install-v2.sh" -o "$WORK/installer"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 15 --max-time 90 \
  "$BASE/$ENGINE_REV/wpo-node-eight-enable.sh" -o "$WORK/engines"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 15 --max-time 90 \
  "$BASE/$ENGINE_REV/wpo-node-site-template-fix.sh" -o "$WORK/site"
bash -n "$WORK/installer"
bash -n "$WORK/engines"
bash -n "$WORK/site"
grep -Fqx "ENGINE_REV=$ENGINE_REV" "$WORK/installer" || {
  echo 'Неверная версия Node Agent. Ничего не изменено.' >&2; exit 3;
}
grep -Fq 'wpo-node-eight-enable.sh' "$WORK/installer"
grep -Fq 'expected={"federation","vless","hysteria","web","mtproto","awg20","awg31","naive","mieru"}' "$WORK/installer"
grep -Fq 'wpo-node-site-template-fix.sh' "$WORK/engines"
grep -Fq 'bash "$TEMP/site-template-fix.sh"' "$WORK/engines"
grep -Fq "doc['public_upstream']='http://127.0.0.1:18082'" "$WORK/site"
grep -Fq 'header Cache-Control "no-store"' "$WORK/site"
grep -Fq 'systemctl reload caddy.service' "$WORK/site"
grep -Fq '# wpo-eight-agent-ready-retry-v1:' "$WORK/installer"
grep -Fq 'http://127.0.0.1:9088/healthz' "$WORK/installer"
grep -Fq 'journalctl -u wpp-node-agent.service' "$WORK/installer"

# The controller already serves this script from disk for each installer
# request. Replace just that file; do not restart panel, Xray, Caddy or Happ.
if cmp -s "$WORK/installer" "$TARGET"; then
  echo '✓ На основной WPO уже установлен исправленный установщик нод.'
  echo '✓ Создавайте новые ноды через WPO — сайты и шаблоны будут обслуживаться Caddy.'
  echo '✓ Удалённые VPS, панель и действующие VPN не изменены.'
  exit 0
fi
install -d -o root -g root -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp-node-agent-install.sh"
install -o root -g root -m 0700 "$WORK/installer" "$TARGET"
if ! cmp -s "$WORK/installer" "$TARGET" || ! bash -n "$TARGET"; then
  echo 'Проверка установщика не прошла — возвращаю резервную копию.' >&2
  cp -a "$BACKUP/wpp-node-agent-install.sh" "$TARGET"
  exit 4
fi
echo '✓ В основной WPO установлен исправленный Node Agent 0.4.'
echo '✓ Новые дополнительные ноды сохраняют 8 протоколов и живые шаблоны сайтов.'
echo '✓ Шаблон назначается из панели, WEB Proxy работает через Caddy upstream.'
echo '✓ SSH, пароли, подключение к VPS и переустановка основной панели не требуются.'
echo "Резервная копия: $BACKUP"
echo 'Можно добавлять новую ноду и проверять шаблон сайта.'
