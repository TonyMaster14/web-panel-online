#!/usr/bin/env bash
# WPO: one command ON MAIN VPS. Update registered additional nodes over SSH
# from the main machine, then deploy verified fast Happ provisioning.
# SSH is needed because Node Agent 0.4 lacks an authenticated code-update API.
set -Eeuo pipefail
umask 077
(( EUID == 0 )) || { echo 'Запусти команду с sudo на ОСНОВНОМ VPS WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
NODES=/var/lib/tproxy-panel/nodes.json
[[ -s "$APP/panel.py" && -s "$APP/wpp_subscriptions.py" &&
   -s "$APP/wpp_nodes.py" && -s "$NODES" &&
   ! -e /etc/wpp-node-agent/config.json ]] || {
  echo 'Это не основная WPO с зарегистрированными нодами.' >&2; exit 2;
}
for bin in ssh curl python3 flock; do
  command -v "$bin" >/dev/null || { echo "Не установлен $bin." >&2; exit 2; }
done
SSH_PORT=22
[[ -z "${WPO_NODE_SSH_PORT:-}" ]] || SSH_PORT="$WPO_NODE_SSH_PORT"
[[ "$SSH_PORT" =~ ^[0-9]{1,5}$ ]] && (( 10#$SSH_PORT > 0 && 10#$SSH_PORT <= 65535 )) || {
  echo 'Некорректный SSH-порт.' >&2; exit 2;
}
SSH_USER=root
[[ -z "${WPO_NODE_SSH_USER:-}" ]] || SSH_USER="$WPO_NODE_SSH_USER"
[[ "$SSH_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || {
  echo 'Некорректный SSH-пользователь.' >&2; exit 2;
}
WORK="$(mktemp -d /tmp/wpo-main-one-command.XXXXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
exec 9>/run/lock/wpo-one-vps-node-update.lock
flock -n 9 || { echo 'Обновление нод уже выполняется.' >&2; exit 2; }

# No node tokens or users' VPN keys are exposed.
python3 - "$NODES" >"$WORK/hosts" <<'PY_HOSTS'
import re,sys
from urllib.parse import urlsplit
sys.path.insert(0,"/opt/tproxy-panel")
import wpp_nodes as api
nodes=api.load_nodes(sys.argv[1])
hosts=[]
for node in nodes:
    p=urlsplit(node.get("url",""))
    host=(p.hostname or "").lower()
    if p.scheme!="https" or p.port not in (None,443) or not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",host
    ):
        raise SystemExit("Некорректное доменное имя зарегистрированной ноды.")
    if host not in hosts:
        hosts.append(host)
if not 1<=len(hosts)<=16:
    raise SystemExit("Нужна хотя бы одна зарегистрированная дополнительная нода.")
print("\n".join(hosts))
PY_HOSTS
echo '=== Дополнительные ноды WPO ==='
cat "$WORK/hosts"

# Immutable GitHub revisions: a moving branch cannot alter downloaded code.
BASE=https://raw.githubusercontent.com/TonyMaster14/web-panel-online
NODE_REV=440e90aa0d42e2f5c2b957f60df7e69690c08e50
MAIN_REV=12fe9982b0550be60279c872428876d557b7e595
PATCH_REV=ceb4fb3acbfc241a3f6c01580bf84a32615921fb
fetch() {
  curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
    --connect-timeout 12 --max-time 90 "$1" -o "$2"
}
fetch "$BASE/$NODE_REV/wpo-node-federation-hotfix.sh" "$WORK/node.sh"
fetch "$BASE/$MAIN_REV/wpo-happ-multinode-main-install.sh" "$WORK/main.sh"
fetch "$BASE/$PATCH_REV/wpo-happ-preallocate-patch.py" "$WORK/subs-patch.py"
fetch "$BASE/$PATCH_REV/wpo-happ-async-panel-patch.py" "$WORK/panel-patch.py"
bash -n "$WORK/node.sh" "$WORK/main.sh"
python3 -m py_compile "$WORK/subs-patch.py" "$WORK/panel-patch.py"

# Verify both main-panel source transformations BEFORE touching any node.
echo '=== Проверка совместимости основной WPO ==='
python3 "$WORK/subs-patch.py" --input "$APP/wpp_subscriptions.py" \
  --output "$WORK/subs-verified.py"
python3 "$WORK/panel-patch.py" --panel "$APP/panel.py" \
  --output "$WORK/panel-verified.py"
python3 -m py_compile "$WORK/subs-verified.py" "$WORK/panel-verified.py"

echo '=== Обновляю все зарегистрированные ноды из ОДНОЙ SSH-сессии основного VPS ==='
echo 'SSH проверяет ключ сервера. Если доступ по ключу не настроен, может запросить пароль root.'
# StrictHostKeyChecking is not disabled. Never pass private credentials to remote
# script. It independently downloads the public pinned source.
while IFS= read -r host; do
  echo "Нода: $host"
  if ! ssh -T \
       -o StrictHostKeyChecking=ask \
       -o ConnectTimeout=12 \
       -o ConnectionAttempts=1 \
       -o ServerAliveInterval=10 \
       -o ServerAliveCountMax=3 \
       -o NumberOfPasswordPrompts=3 \
       -o ForwardAgent=no \
       -o ClearAllForwardings=yes \
       -p "$SSH_PORT" \
       "$SSH_USER@$host" 'bash -se' < "$WORK/node.sh"; then
    echo "✗ SSH-доступ к $host с ОСНОВНОГО VPS отсутствует или обновление не удалось." >&2
    echo 'Старый Node Agent не умеет обновлять собственный код через HTTP API.' >&2
    echo 'Без разрешённого удалённого доступа выполнить обновление этой VPS нельзя.' >&2
    exit 5
  fi
  echo "✓ $host: VPN Federation обновлена."
done < "$WORK/hosts"

echo '=== Устанавливаю быструю многонодовую подписку на основной WPO ==='
bash "$WORK/main.sh"
echo '=== Проверяю реальные VPN-профили всех выбранных нод ==='
if ! python3 "$APP/wpo_happ_preparer.py"; then
  echo '✗ Не все VPN-профили созданы. Смотри подробности по нодам выше.' >&2
  echo 'Полный успех не подтверждён; новые ключи не выдумывались.' >&2
  exit 6
fi
echo '✓ Все выбранные ноды подготовлены. Обнови ту же подписку в Happ.'
echo '✓ Для обновления использовалась одна команда только на основном VPS.'
