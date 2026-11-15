#!/usr/bin/env bash
# Apply and verify actual Nodes page HTML + stylesheet (not service startup alone).
# Test branch only. No user, subscription, VPN, Xray or Caddy modifications.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Нужен sudo на основном WPO VPS.' >&2; exit 2; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
[[ -s "$APP/panel.py" && -s "$UI" && -s /etc/web-proxy-panel/users.json &&
    ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Требуется основной контроллер WPO с Nodes Lab.' >&2; exit 2;
}
systemctl cat "$SERVICE" >/dev/null
exec 9>/run/lock/wpo-main-star-v2.lock
flock -n 9 || { echo 'Обновление интерфейса уже запущено.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-main-star-v2.XXXXXXXX)"
BACKUP=""
ROLLBACK=0
cleanup(){
    rc=$?
    trap - EXIT
    if [[ "$ROLLBACK" == 1 ]]; then
        echo 'Проверка HTML/службы не прошла. Восстанавливаю предыдущий интерфейс.' >&2
        cp -a "$BACKUP" "$UI" || true
        rm -f "$APP"/__pycache__/wpp_ui.*.pyc
        systemctl restart "$SERVICE" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$WORK"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
REV=c85509aee9c38cc148c627e5d6527cb57ad314d7
curl -4fsSL --retry 3 --proto '=https' --proto-redir '=https' \
     --connect-timeout 12 --max-time 90 \
     "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/wpo-node-main-star-v2-patch.py" \
     -o "$WORK/patch.py"
python3 -m py_compile "$WORK/patch.py"
PYTHONPATH="$APP" python3 "$WORK/patch.py" --input "$UI" --output "$WORK/ui.py"
python3 -m py_compile "$WORK/ui.py"
verify_ui(){
    PYTHONPATH="$APP" python3 - "$1" "$WORK/patch.py" <<'PY'
import importlib.util, pathlib,sys
ui_file=pathlib.Path(sys.argv[1])
patch_file=pathlib.Path(sys.argv[2])
spec=importlib.util.spec_from_file_location("wpo_star_v2_checker",patch_file)
checker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
checker.verify(ui_file.read_text(encoding="utf-8"))
print("✓ Фактическая HTML-карточка и CSS проверены.")
PY
}
verify_ui "$WORK/ui.py"
if cmp -s "$UI" "$WORK/ui.py"; then
    verify_ui "$UI"
    echo '✓ Новая разметка уже установлена. Обнови страницу с очисткой кэша (Ctrl+Shift+R).'
    exit 0
fi
BACKUP_DIR=/var/lib/tproxy-panel/nodes-main-star-backups
install -d -o root -g root -m 0700 "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/wpp_ui-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
ROLLBACK=1
install -o root -g root -m 0644 "$WORK/ui.py" "$UI"
rm -f "$APP"/__pycache__/wpp_ui.*.pyc
systemctl restart "$SERVICE"
PANEL_PATH="$(systemctl show -p Environment --value "$SERVICE" |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
if [[ ! "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]]; then
    PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
fi
[[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] || exit 4
READY=0
for i in {1..15}; do
    if systemctl is-active --quiet "$SERVICE" &&
       curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
            "http://127.0.0.1:8090$PANEL_PATH/__health" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done
[[ "$READY" == 1 ]] || exit 4
verify_ui "$UI"
ROLLBACK=0
echo '✓ Готово: у основной ноды звезда ★ после названия, а не на флаге.'
echo '✓ Жёлтый цвет #facc15 и новая версия стилей проверены.'
echo '✓ Ноды, VPN, Caddy, ключи и пользователи не изменены.'
echo "Резервная копия: $BACKUP"
echo 'Обнови страницу «Ноды» с очисткой кэша (Ctrl+Shift+R).'
