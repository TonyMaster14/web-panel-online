#!/usr/bin/env bash
# Main-WPO controller upgrade. No SSH or changes to additional VPS services.
set -Eeuo pipefail
umask 077
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
SUBS="$APP/wpp_subscriptions.py"
[[ "$EUID" == 0 ]] || { echo 'Запусти на основном VPS WPO от root.' >&2; exit 2; }
[[ -s "$PANEL" && -s "$SUBS" && -s "$APP/wpp_nodes.py" &&
   ! -f /etc/wpp-node-agent/config.json ]] || {
    echo 'Не найдена ОСНОВНАЯ WPO. Дополнительные VPS менять не нужно.' >&2; exit 2;
}
command -v flock >/dev/null && command -v curl >/dev/null && command -v python3 >/dev/null || {
  echo 'Не установлены необходимые системные инструменты.' >&2; exit 2;
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'WPO уже выполняет обновление. Ничего не изменено.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-happ-ready.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/happ-ready-backup-$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK=0
FILES="panel.py wpp_subscriptions.py wpo_happ_async_feed.py wpo_happ_preparer.py"
rollback(){
  echo 'Проверка WPO не прошла. Возвращаю прежние файлы.' >&2
  for file in $FILES; do
    if [[ -f "$BACKUP/$file" ]]; then
      cp -a "$BACKUP/$file" "$APP/$file" || true
    else
      rm -f "$APP/$file"
    fi
  done
  rm -f "$APP"/__pycache__/panel.*.pyc "$APP"/__pycache__/wpp_subscriptions.*.pyc
  systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
}
finish(){
  status=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then rollback; fi
  rm -rf -- "$WORK"
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT TERM
REV=a67b59268363fdc61aef04d7406a1cb90142f171
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV"
for file in wpo_happ_async_feed.py wpo_happ_preparer.py wpo-happ-preallocate-patch.py wpo-happ-async-panel-patch.py; do
  curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
    --connect-timeout 15 --max-time 90 "$BASE/$file" -o "$WORK/$file"
  python3 -m py_compile "$WORK/$file"
done
python3 "$WORK/wpo-happ-preallocate-patch.py" --input "$SUBS" --output "$WORK/wpp_subscriptions.py"
python3 "$WORK/wpo-happ-async-panel-patch.py" --panel "$PANEL" --output "$WORK/panel.py"
python3 -m py_compile "$WORK/wpp_subscriptions.py" "$WORK/panel.py"
grep -Fq 'wpo-happ-preregister-first-device-v1' "$WORK/wpp_subscriptions.py"
grep -Fq 'wpo-happ-fast-feed-v1' "$WORK/panel.py"
grep -Fq 'wpo-happ-prewarm-on-create-v1' "$WORK/panel.py"
grep -Fq 'prewarmed(remotes,remote_id,wanted)' "$WORK/panel.py"
grep -Fq 'profile-update-interval":"1"' "$WORK/panel.py"
grep -Fq 'def verified_links' "$WORK/wpo_happ_async_feed.py"
grep -Fq 'def prepare():' "$WORK/wpo_happ_preparer.py"
install -d -m 0700 -o root -g root "$BACKUP"
for file in $FILES; do
  if [[ -f "$APP/$file" ]]; then cp -a "$APP/$file" "$BACKUP/$file"; fi
done
ROLLBACK=1
for file in $FILES; do
  install -o root -g root -m 0644 "$WORK/$file" "$APP/$file"
done
rm -f "$APP"/__pycache__/panel.*.pyc "$APP"/__pycache__/wpp_subscriptions.*.pyc
systemctl restart tproxy-panel.service
PANEL_PATH="$(systemctl show -p Environment --value tproxy-panel.service |
  tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n 1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] || {
  echo 'Не найден защищённый путь основной панели.' >&2; exit 4;
}
ready=0
for n in {1..15}; do
  if systemctl is-active --quiet tproxy-panel.service &&
     [[ "$(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
        "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null)" == OK ]]; then
    ready=1; break
  fi
  sleep 1
done
[[ "$ready" == 1 ]] || { echo 'Основная панель не ответила, откатываю.' >&2; exit 4; }
ROLLBACK=0
echo '✓ Основная WPO работает; одиночные подключения и работающие VPN-службы не тронуты.'
echo '✓ Happ не ждёт долгих перезапусков Xray на дополнительных VPS.'
echo '✓ Новые многонодовые подписки заранее резервируют первый профиль устройства.'
cat >/etc/systemd/system/wpo-happ-prepare.service <<'UNIT'
[Unit]
Description=WPO pre-provision selected remote Happ VPN profiles
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=root
Group=root
UMask=0077
ExecStart=/usr/bin/python3 /opt/tproxy-panel/wpo_happ_preparer.py
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/tproxy-panel /run/lock
UNIT
cat >/etc/systemd/system/wpo-happ-prepare.timer <<'UNIT'
[Unit]
Description=Maintain prepared multi-node WPO Happ subscriptions
[Timer]
OnBootSec=15s
OnUnitInactiveSec=30s
OnCalendar=*:0/1
AccuracySec=5s
Persistent=true
Unit=wpo-happ-prepare.service
[Install]
WantedBy=timers.target
UNIT
chmod 0644 /etc/systemd/system/wpo-happ-prepare.service /etc/systemd/system/wpo-happ-prepare.timer
systemctl daemon-reload
systemctl enable --now wpo-happ-prepare.timer
echo '✓ Автоматическая подготовка дополнительных нод включена.'
echo '=== Подготовка VPN-профилей существующих подписок ==='
if python3 "$APP/wpo_happ_preparer.py"; then
  echo '✓ Выбранные удалённые VPN-профили проверены. Обнови текущую подписку в Happ.'
else
  echo '✗ Одна из нод не создала профиль. Её HTTP-ошибка указана выше.' >&2
  echo 'Happ теперь импортирует доступные реальные подключения без долгого ожидания.' >&2
  echo 'WPO продолжит проверять остальные ноды автоматически; ключи не удалены.' >&2
  exit 6
fi
echo "Резервная копия основной панели: $BACKUP"
