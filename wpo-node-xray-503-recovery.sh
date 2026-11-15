#!/usr/bin/env bash
# Existing ADDITIONAL WPO node: recover Xray config readability after a 503.
# No reinstall, no changes to user/device keys, Caddy or WEB relay.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Используйте root на ДОПОЛНИТЕЛЬНОЙ ноде.' >&2; exit 2; }
ROOT=/opt/wpp-node-agent
MODULE="$ROOT/wpo_node_vpn.py"
CFG=/etc/wpp-node-vpn/xray.json
[[ -s "$MODULE" && -s "$CFG" && -s /etc/wpp-node-agent/config.json &&
   -s /etc/wpp-node-vpn/settings.json && ! -e /opt/tproxy-panel/panel.py ]] || {
  echo 'Не обнаружена установленная дополнительная WPO-нода. Ничего не изменено.' >&2
  exit 2
}
getent group xray >/dev/null || { echo 'Группа xray не существует.' >&2; exit 2; }
exec 9>/run/lock/wpo-node-xray-restore.lock
flock -n 9 || { echo 'Другое исправление уже выполняется.' >&2; exit 2; }
exec 8>/etc/wpp-node-vpn/.federation.lock
flock -w 40 8 || { echo 'Идёт создание VPN-профиля: ничего не изменено.' >&2; exit 3; }
TMP="$(mktemp -d /tmp/wpo-node-503.XXXXXXXX)"
BACKUP="/etc/wpp-node-vpn/xray-503-backup-$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK=0
finish(){
  code=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo 'Не прошла проверка Node API. Возвращаю предыдущий модуль.' >&2
    cp -a "$BACKUP/wpo_node_vpn.py" "$MODULE" || true
    rm -f "$ROOT"/__pycache__/wpo_node_vpn.*.pyc
    systemctl restart wpo-node-vpn.service >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TMP"
  exit "$code"
}
trap finish EXIT
trap 'exit 130' INT TERM
python3 - "$MODULE" "$TMP/wpo_node_vpn.py" <<'PY'
from pathlib import Path
import ast,sys
src=Path(sys.argv[1]).read_text(encoding="utf-8")
old='''            os.chmod(tmp, 0o600)
            os.replace(tmp, XRAY)
            command("systemctl", "restart", UNIT, timeout=30)'''
new='''            # The Xray daemon runs as the unprivileged xray user. Restoring
            # root:root mode 0600 leaves the daemon unable to read its config
            # and turns a recoverable POST failure into a persistent 503.
            os.chown(tmp, 0, grp.getgrnam("xray").gr_gid)
            os.chmod(tmp, 0o640)
            os.replace(tmp, XRAY)
            command("systemctl", "restart", UNIT, timeout=30)'''
if old in src:
    if src.count(old)!=1: raise SystemExit("Некорректный код отката Xray")
    src=src.replace(old,new,1)
elif new not in src:
    raise SystemExit("Неизвестная версия VPN Federation; ничего не меняем")
ast.parse(src,filename="wpo_node_vpn.py")
Path(sys.argv[2]).write_text(src,encoding="utf-8")
PY
python3 -m py_compile "$TMP/wpo_node_vpn.py"
install -d -o root -g root -m 0700 "$BACKUP"
cp -a "$MODULE" "$BACKUP/wpo_node_vpn.py"
cp -a "$CFG" "$BACKUP/xray.json"
ROLLBACK=1
if ! cmp -s "$MODULE" "$TMP/wpo_node_vpn.py"; then
  install -o root -g root -m 0644 "$TMP/wpo_node_vpn.py" "$MODULE"
  rm -f "$ROOT"/__pycache__/wpo_node_vpn.*.pyc
fi
# Recover readable permissions without changing ANY bytes of saved profiles.
chown root:xray "$CFG"
chmod 0640 "$CFG"
if ! systemctl is-active --quiet wpo-node-xray.service; then
  echo 'Xray был остановлен: пытаюсь запустить его со старой конфигурацией.'
  systemctl restart wpo-node-xray.service
fi
systemctl is-active --quiet wpo-node-xray.service || exit 4
systemctl restart wpo-node-vpn.service
READY=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  if systemctl is-active --quiet wpo-node-vpn.service &&
    curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 2 \
      http://127.0.0.1:9089/healthz 2>/dev/null |
      python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("ok") else 1)' 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done
[[ "$READY" == 1 ]] || exit 4
ROLLBACK=0
echo '✓ Xray читает свою конфигурацию; VPN Federation отвечает.'
echo '✓ Восстановление после ошибки больше не оставит root-only конфигурацию.'
echo '✓ Пользователи, ключи, Caddy, WEB Proxy и другие VPN-протоколы не изменены.'
echo "Резервная копия: $BACKUP"
