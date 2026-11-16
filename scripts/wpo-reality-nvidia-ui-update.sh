#!/usr/bin/env bash
# Compatibility alias for the previous NVIDIA UI updater.
# WPO TEST ONLY: coordinated REALITY checking and fleet UI.
# Controller host only. No VPN/HAProxy/Xray config, user, SNI or key changes.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите с sudo на основном VPS WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
SERVICE=tproxy-panel.service
REV=7b673ffd20d256d8fb2204ea1cca9637b4707f94
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV"
for name in panel.py wpo_reality.py wpo_reality_ui.py wpp-node-agent-install.sh; do
    [[ -s "$APP/$name" && ! -L "$APP/$name" ]] ||
        { echo "Не найден установленный компонент: $APP/$name" >&2; exit 2; }
done
grep -Fq '/reality-action' "$APP/panel.py" ||
    { echo 'Маршрут REALITY не установлен в панели.' >&2; exit 2; }
systemctl cat "$SERVICE" >/dev/null 2>&1 ||
    { echo 'Служба WPO не найдена.' >&2; exit 2; }
STAGING="$(mktemp -d /tmp/wpo-reality-fleet.XXXXXXXX)"
BACKUP=""
TOUCHED=0
cleanup(){
    local rc=$?
    trap - EXIT
    if ((rc != 0 && TOUCHED == 1)) && [[ -n "$BACKUP" && -d "$BACKUP" ]]; then
        echo 'Обновление остановилось: возвращаю исходные файлы...' >&2
        for name in panel.py wpo_reality.py wpo_reality_ui.py wpo_reality_probe.py wpp-node-agent-install.sh; do
            if [[ -f "$BACKUP/$name" ]]; then cp -a "$BACKUP/$name" "$APP/$name" || true
            elif [[ -f "$BACKUP/absent-$name" ]]; then rm -f "$APP/$name" || true
            fi
        done
        systemctl restart "$SERVICE" || true
        echo "Старая версия восстановлена: $BACKUP" >&2
    fi
    rm -rf -- "$STAGING"
    exit "$rc"
}
trap cleanup EXIT
for name in wpo_reality.py wpo_reality_probe.py wpo_reality_ui.py; do
    curl -4fsSL --retry 3 --connect-timeout 12 --max-time 75 --proto '=https' \
      "$BASE/src/$name" -o "$STAGING/$name"
    python3 -m py_compile "$STAGING/$name"
done
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' \
  "$BASE/nodes/wpo-node-agent-install-v2.sh" -o "$STAGING/wpp-node-agent-install.sh"
bash -n "$STAGING/wpp-node-agent-install.sh"
grep -Fq 'wpo_reality_probe.probe(' "$STAGING/wpo_reality.py" ||
    { echo 'В пакете отсутствует реальная проверка REALITY.' >&2; exit 3; }
grep -Fq 'editor(path,csrf,public_nodes,fleet=True)' "$STAGING/wpo_reality_ui.py" ||
    { echo 'В пакете отсутствует массовое применение REALITY.' >&2; exit 3; }
grep -Fq 'REALITY_REV=f0d6344c76cfb3df1bd9a44f6902da61ac419d8e' "$STAGING/wpp-node-agent-install.sh" ||
    { echo 'Установщик новых нод использует старую версию REALITY.' >&2; exit 3; }
# The old generated controller handler has a Microsoft fallback if preset is
# omitted. Replace ONLY that exact literal, without modifying any other route.
python3 - "$APP/panel.py" "$STAGING/panel.py" <<'PY'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text()
old='form.get("preset","microsoft")'
if s.count(old)>1:raise RuntimeError('Неоднозначная версия обработчика REALITY')
s=s.replace(old,'form.get("preset","nvidia")')
compile(s,sys.argv[2],'exec')
Path(sys.argv[2]).write_text(s)
PY
if cmp -s "$STAGING/panel.py" "$APP/panel.py" &&
   cmp -s "$STAGING/wpo_reality.py" "$APP/wpo_reality.py" &&
   cmp -s "$STAGING/wpo_reality_probe.py" "$APP/wpo_reality_probe.py" &&
   cmp -s "$STAGING/wpo_reality_ui.py" "$APP/wpo_reality_ui.py" &&
   cmp -s "$STAGING/wpp-node-agent-install.sh" "$APP/wpp-node-agent-install.sh"; then
    echo 'WPO REALITY: массовые настройки и проверка Vision уже установлены.'
    exit 0
fi
install -d -m 0700 /var/backups/web-panel-online
BACKUP="/var/backups/web-panel-online/reality-fleet-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
for name in panel.py wpo_reality.py wpo_reality_probe.py wpo_reality_ui.py wpp-node-agent-install.sh; do
    if [[ -f "$APP/$name" ]]; then cp -a "$APP/$name" "$BACKUP/$name"
    else : > "$BACKUP/absent-$name"
    fi
done
echo "Резервная копия: $BACKUP"
TOUCHED=1
for name in panel.py wpo_reality.py wpo_reality_probe.py wpo_reality_ui.py wpp-node-agent-install.sh; do
    stage="$(mktemp "$APP/.wpo-fleet.XXXXXXXX.py")"
    cp "$STAGING/$name" "$stage"
    if [[ -f "$APP/$name" ]]; then
        chown --reference="$APP/$name" "$stage"
        chmod --reference="$APP/$name" "$stage"
    else
        chmod 0644 "$stage"
    fi
    mv -f "$stage" "$APP/$name"
done
python3 -m py_compile "$APP/panel.py" "$APP/wpo_reality.py" \
    "$APP/wpo_reality_probe.py" "$APP/wpo_reality_ui.py"
bash -n "$APP/wpp-node-agent-install.sh"
systemctl restart "$SERVICE"
ROUTE="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
[[ "$ROUTE" =~ ^/panel-[a-z0-9-]{3,64}$ ]] ||
    { echo 'Не удалось определить адрес панели.' >&2; exit 4; }
READY=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if systemctl is-active --quiet "$SERVICE" &&
       curl -4fsS --max-time 2 "http://127.0.0.1:8090$ROUTE/__health" >/dev/null 2>&1; then
        READY=1;break
    fi
    sleep 1
done
((READY)) || { echo 'Панель не отвечает после обновления.' >&2; exit 4; }
TOUCHED=0
echo '✓ Настройки REALITY из Подключений: вся сеть.'
echo '✓ Проверка цели: TLS 1.3, HTTP/2, Vision, реальный HTTPS 204.'
echo '✓ Сохранить: после проверки всех подключённых нод.'
echo '✓ Красивое меню целей и индикаторы проверки.'
echo 'Действующие SNI, ноды, пользователи, ключи и VPN-сервисы не изменены.'
