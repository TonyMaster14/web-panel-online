#!/usr/bin/env bash
# Test-only WPO speed patch. Only run on a testing main-controller VPS.
# Never resets profiles, nodes, user data, Xray configuration or TLS.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запустите через sudo на тестовой основной WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
MANAGER=/usr/local/sbin/web-proxy-panelctl
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
[[ -s "$MANAGER" && -s "$PANEL" && -s "$UI" &&
    -s /etc/web-proxy-panel/users.json && ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Нужна тестовая основная WPO, не дополнительная нода.' >&2; exit 2;
}
exec 9>/run/lock/wpo-fast-delete-test.lock
flock -n 9 || { echo 'Параллельное обновление уже выполняется.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-delete-test.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
    rc=$?
    trap - EXIT
    if [[ "$rc" != 0 && "$CHANGED" == 1 ]]; then
        echo 'Проверка не пройдена; возвращаю исходные модули.' >&2
        for item in manager.py panel.py ui.py; do
            case "$item" in
              manager.py) target="$MANAGER";;
              panel.py) target="$PANEL";;
              ui.py) target="$UI";;
            esac
            cp -a "$BACKUP/$item" "$target" || true
        done
        rm -f "$APP"/__pycache__/panel.*.pyc "$APP"/__pycache__/wpp_ui.*.pyc
        systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
    fi
    rm -rf -- "$WORK"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
download(){
    local rev="$1" file="$2"
    curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
      --connect-timeout 12 --max-time 90 \
      "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$rev/$file" \
      -o "$WORK/$file"
}
download 5a4f13f085a6158255f891a61d836fc142c77793 wpo-fast-delete-manager-patch.py
download 3e4effdc7d9ea2b7635e15413a6fda69ffd7323f wpo-fast-delete-controller-patch.py
download b68669ec2c32562accf9a8af094f80841803d93e wpo-fast-delete-ui-patch.py
python3 -m py_compile "$WORK/"*.py
python3 "$WORK/wpo-fast-delete-manager-patch.py" --input "$MANAGER" --output "$WORK/manager.py"
python3 "$WORK/wpo-fast-delete-controller-patch.py" --input "$PANEL" --output "$WORK/panel.py"
python3 "$WORK/wpo-fast-delete-ui-patch.py" --input "$UI" --output "$WORK/ui.py"
python3 -m py_compile "$WORK/manager.py" "$WORK/panel.py" "$WORK/ui.py"
if cmp -s "$WORK/manager.py" "$MANAGER" &&
   cmp -s "$WORK/panel.py" "$PANEL" &&
   cmp -s "$WORK/ui.py" "$UI"; then
    echo '✓ Тестовое ускорение уже установлено.'
    exit 0
fi
# Verify read-only manager access before risking the panel service.
PYTHONPATH="$APP" python3 "$WORK/manager.py" users |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d.get("users"),list)'
BACKUP="/var/lib/tproxy-panel/fast-delete-test-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o root -g root -m 0700 "$BACKUP"
cp -a "$MANAGER" "$BACKUP/manager.py"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$UI" "$BACKUP/ui.py"
CHANGED=1
install -o root -g root -m 0755 "$WORK/manager.py" "$MANAGER"
install -o root -g root -m 0644 "$WORK/panel.py" "$PANEL"
install -o root -g root -m 0644 "$WORK/ui.py" "$UI"
rm -f "$APP"/__pycache__/panel.*.pyc "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart tproxy-panel.service
PANEL_PATH="$(systemctl show -p Environment --value tproxy-panel.service |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] || exit 4
READY=0
for attempt in {1..15}; do
    if systemctl is-active --quiet tproxy-panel.service &&
       [[ "$(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
            "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null)" == OK ]]; then
        READY=1
        break
    fi
    sleep 1
done
[[ "$READY" == 1 ]] || exit 4
"$MANAGER" users | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d.get("users"),list)'
CHANGED=0
echo '✓ Тестовый WPO запущен; удаление VLESS/Hysteria и отзыв ключей ускорены.'
echo '✓ Лишняя надпись «Проверяем…» убрана, проверки не отключены.'
echo '✓ Сохранены пользователи, подписки, ключи и рабочие ноды.'
echo "Резервная копия: $BACKUP"
echo 'Это изменение тестового VPS, а не публикация обновления в GitHub main.'
