#!/usr/bin/env bash
# Update ONLY the REALITY check modules on an existing node.
# The controller fleet menu requires actual Vision/HTTP204 evidence.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите с sudo на VPS ноды WPO.' >&2; exit 2; }
APP=/opt/wpp-node-agent
UNIT=wpo-node-vpn.service
REV=a82bc7a2f03ada39ad0ab3db407996e24862878a
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src"
for file in wpo_reality.py wpo_node_vpn.py; do
    [[ -s "$APP/$file" && ! -L "$APP/$file" ]] || { echo "REALITY Node Agent не найден: $file" >&2; exit 2; }
done
[[ -s /etc/web-proxy-panel/reality/profile.json && -s /etc/web-proxy-panel/reality/private.key ]] ||
    { echo 'REALITY ещё не настроен на этой ноде.' >&2; exit 2; }
systemctl cat "$UNIT" >/dev/null 2>&1 || { echo 'Служба VPN ноды не найдена.' >&2; exit 2; }
TEMP="$(mktemp -d /tmp/wpo-reality-probe.XXXXXXXX)"
BACKUP=""
TOUCHED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if ((rc != 0 && TOUCHED == 1)) && [[ -n "$BACKUP" ]]; then
      for name in wpo_reality.py wpo_reality_probe.py; do
          if [[ -f "$BACKUP/$name" ]]; then cp -a "$BACKUP/$name" "$APP/$name" || true
          elif [[ -f "$BACKUP/absent-$name" ]]; then rm -f "$APP/$name" || true
          fi
      done
      systemctl restart "$UNIT" || true
      echo 'Ошибка обновления REALITY: старые модули восстановлены.' >&2
  fi
  rm -rf -- "$TEMP"
  exit "$rc"
}
trap cleanup EXIT
for name in wpo_reality.py wpo_reality_probe.py; do
    curl -4fsSL --retry 3 --connect-timeout 10 --max-time 75 --proto '=https' \
       "$BASE/$name" -o "$TEMP/$name"
    python3 -m py_compile "$TEMP/$name"
done
grep -Fq 'wpo_reality_probe.probe(' "$TEMP/wpo_reality.py" ||
    { echo 'В скачанной версии отсутствует полная проверка REALITY.' >&2; exit 3; }
grep -Fq 'HTTP 204' "$TEMP/wpo_reality_probe.py" ||
    { echo 'В скачанной версии отсутствует HTTP 204.' >&2; exit 3; }
if cmp -s "$APP/wpo_reality.py" "$TEMP/wpo_reality.py" &&
   cmp -s "$APP/wpo_reality_probe.py" "$TEMP/wpo_reality_probe.py"; then
    echo 'REALITY Vision: полноценная проверка уже установлена.'
    exit 0
fi
BACKUP="/etc/web-proxy-panel/reality/probe-update-backup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
for name in wpo_reality.py wpo_reality_probe.py; do
    if [[ -f "$APP/$name" ]]; then cp -a "$APP/$name" "$BACKUP/$name"
    else : > "$BACKUP/absent-$name"
    fi
done
echo "Резервная копия: $BACKUP"
TOUCHED=1
for name in wpo_reality.py wpo_reality_probe.py; do
    stage="$(mktemp "$APP/.wpo-reality.XXXXXXXX.py")"
    cp "$TEMP/$name" "$stage"
    if [[ -f "$APP/$name" ]]; then
       chown --reference="$APP/$name" "$stage"
       chmod --reference="$APP/$name" "$stage"
    else
       chmod 0644 "$stage"
    fi
    mv -f "$stage" "$APP/$name"
done
python3 -m py_compile "$APP/wpo_reality.py" "$APP/wpo_reality_probe.py"
systemctl restart "$UNIT"
READY=0
for attempt in 1 2 3 4 5 6 7 8; do
    if systemctl is-active --quiet "$UNIT" &&
       systemctl is-active --quiet wpo-node-xray &&
       systemctl is-active --quiet wpo-tls-router; then
        READY=1;break
    fi
    sleep 1
done
(( READY )) || { echo 'Службы ноды не прошли проверку после обновления.' >&2; exit 4; }
TOUCHED=0
echo 'REALITY node: установлена проверка TLS / Vision / HTTPS 204.'
echo 'SNI, пользователи, подписки, ключи и остальные протоколы не изменялись.'
