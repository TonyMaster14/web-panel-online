#!/usr/bin/env bash
# MAIN WPO only: first-device preregistration and real remote VPN prewarm.
# No SSH, no node reinstallation, no VPN-core or Caddy restarts.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Запусти sudo на ОСНОВНОМ VPS WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
SUBS="$APP/wpp_subscriptions.py"
NODE_INSTALLER="$APP/wpp-node-agent-install.sh"
[[ -s "$PANEL" && -s "$SUBS" && -s "$NODE_INSTALLER" &&
   -s /var/lib/tproxy-panel/nodes.json &&
   -s /etc/web-proxy-panel/users.json && ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Нужна основная WPO с зарегистрированными нодами.' >&2; exit 2;
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Другое обновление WPO уже выполняется.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-happ-ready.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/happ-multinode-backup-$(date -u +%Y%m%dT%H%M%SZ)"
ROLLBACK=0
cleanup() {
  rc=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo 'Проверка панели не пройдена. Возвращаю прежние модули.' >&2
    cp -a "$BACKUP/panel.py" "$PANEL" || true
    cp -a "$BACKUP/wpp_subscriptions.py" "$SUBS" || true
    cp -a "$BACKUP/wpp-node-agent-install.sh" "$NODE_INSTALLER" || true
    for f in wpo_happ_async_feed.py wpo_happ_preparer.py; do
      if [[ -s "$BACKUP/$f" ]]; then cp -a "$BACKUP/$f" "$APP/$f" || true
      else rm -f "$APP/$f"; fi
    done
    rm -f "$APP"/__pycache__/panel.*.pyc \
          "$APP"/__pycache__/wpp_subscriptions.*.pyc
    systemctl restart tproxy-panel.service >/dev/null 2>&1 || true
  fi
  rm -rf -- "$WORK"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

REV=9efc115b6186aa0f5db94e0245a3e8940ac2dc7d
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV"
echo '=== Скачиваю закреплённые версии исправления WPO ==='
for f in wpo-happ-preallocate-patch.py wpo-happ-async-panel-patch.py \
         wpo_happ_async_feed.py wpo_happ_preparer.py; do
    curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
      --connect-timeout 12 --max-time 90 "$BASE/$f" -o "$WORK/$f"
done
# Future nodes must not inherit the proven read-only federation defect.
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3   --connect-timeout 12 --max-time 90   "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/50fc724db31fe2e8b20862dfc5eff67e99e67984/wpo-node-agent-install-v2.sh"   -o "$WORK/wpp-node-agent-install.sh"
bash -n "$WORK/wpp-node-agent-install.sh"
grep -Fqx 'ENGINE_REV=b4d2691a6e942c0ff1ff4652acd63819cc0e0c6f'   "$WORK/wpp-node-agent-install.sh"
grep -Fq 'wpo-node-site-template-fix.sh' "$WORK/wpp-node-agent-install.sh"

echo '=== Проверка кода и защиты существующих профилей ==='
python3 -m py_compile "$WORK/"*.py
python3 "$WORK/wpo-happ-preallocate-patch.py" --input "$SUBS" \
        --output "$WORK/wpp_subscriptions.py"
python3 "$WORK/wpo-happ-async-panel-patch.py" --panel "$PANEL" \
        --output "$WORK/panel.py"
python3 -m py_compile "$WORK/panel.py" "$WORK/wpp_subscriptions.py"
grep -Fq '# wpo-happ-preregister-first-device-v1' "$WORK/wpp_subscriptions.py"
grep -Fq '# wpo-happ-fast-feed-v1:' "$WORK/panel.py"
grep -Fq 'wpo_happ_async_feed.enqueue(' "$WORK/panel.py"
grep -Fq 'local_count=len(result["users"]) if local_selected else 0' "$WORK/panel.py"
grep -Fq 'len(distinct_nodes)>1' "$WORK/panel.py"
grep -Fq 'SUB_FETCH_SLOTS.release()' "$WORK/panel.py"
grep -Fq 'def prewarmed(' "$WORK/wpo_happ_async_feed.py"
grep -Fq 'def verified_links(' "$WORK/wpo_happ_async_feed.py"

install -d -o root -g root -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$SUBS" "$BACKUP/wpp_subscriptions.py"
cp -a "$NODE_INSTALLER" "$BACKUP/wpp-node-agent-install.sh"
for f in wpo_happ_async_feed.py wpo_happ_preparer.py; do
  if [[ -e "$APP/$f" ]]; then cp -a "$APP/$f" "$BACKUP/$f"; fi
done
ROLLBACK=1
install -o root -g root -m 0644 "$WORK/panel.py" "$PANEL"
install -o root -g root -m 0644 "$WORK/wpp_subscriptions.py" "$SUBS"
install -o root -g root -m 0755 "$WORK/wpp-node-agent-install.sh" "$NODE_INSTALLER"
for f in wpo_happ_async_feed.py wpo_happ_preparer.py; do
  install -o root -g root -m 0644 "$WORK/$f" "$APP/$f"
done
rm -f "$APP"/__pycache__/panel.*.pyc \
      "$APP"/__pycache__/wpp_subscriptions.*.pyc \
      "$APP"/__pycache__/wpo_happ_async_feed.*.pyc

echo '=== Перезапускаю только веб-панель WPO ==='
systemctl restart tproxy-panel.service
PANEL_PATH="$(systemctl show -p Environment --value tproxy-panel.service |
    tr ' ' '\n' | sed -n 's/^WEBPROXY_PANEL_PATH=//p' | head -n1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-zA-Z0-9_-]{3,80}$ ]] || {
    echo 'Не найден закрытый путь панели. Откатываю обновление.' >&2; exit 4;
}
READY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if systemctl is-active --quiet tproxy-panel.service &&
     [[ "$(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
         "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null)" == OK ]]; then
      READY=1; break
  fi
  sleep 1
done
[[ "$READY" == 1 ]] || { echo 'Панель не ответила. Выполняю откат.' >&2; exit 4; }
ROLLBACK=0
echo '✓ WPO работает. Быстрый Happ и создание первого профиля установлены.'
echo '✓ Установщик будущих нод обновлён: исправлена песочница VPN Federation.'

# Watch subscription changes; every worker uses controller's existing
# authorized Node API and never asks for node SSH passwords.
cat >/etc/systemd/system/wpo-happ-preparer.service <<'UNIT'
[Unit]
Description=WPO — prepare selected remote VPN profiles before Happ
After=network-online.target tproxy-panel.service
Wants=network-online.target
[Service]
Type=oneshot
User=root
Group=root
UMask=0077
ExecStart=/usr/bin/python3 /opt/tproxy-panel/wpo_happ_preparer.py
TimeoutStartSec=240
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/tproxy-panel
UNIT
cat >/etc/systemd/system/wpo-happ-preparer.path <<'UNIT'
[Unit]
Description=WPO — prepare nodes after subscription changes
[Path]
PathChanged=/etc/web-proxy-panel/users.json
Unit=wpo-happ-preparer.service
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/wpo-happ-preparer.timer <<'UNIT'
[Unit]
Description=WPO — retry unfinished multi-node VPN profiles
[Timer]
OnBootSec=20s
OnUnitInactiveSec=90s
Persistent=true
Unit=wpo-happ-preparer.service
[Install]
WantedBy=timers.target
UNIT
chmod 0644 /etc/systemd/system/wpo-happ-preparer.service \
            /etc/systemd/system/wpo-happ-preparer.path \
            /etc/systemd/system/wpo-happ-preparer.timer
systemctl daemon-reload
systemctl enable --now wpo-happ-preparer.path wpo-happ-preparer.timer
echo '=== Подготавливаю все уже выбранные дополнительные VPN-ноды ==='
if python3 "$APP/wpo_happ_preparer.py"; then
  echo '✓ Все существующие удалённые VPN-профили готовы.'
  echo '✓ Теперь обнови существующую подписку в Happ.'
else
  echo '✗ Часть дополнительных нод отказала в реальном POST создания VPN-профиля.' >&2
  echo '  WPO теперь быстро отдаёт только уже проверенные подключения.' >&2
  echo '  Повторная подготовка нод включена; но их рабочее состояние не подтверждено.' >&2
  echo '  Это не успешная трёхнодовая подписка, несмотря на работающую основную WPO.' >&2
  echo "Резервная копия: $BACKUP" >&2
  exit 6
fi
echo '✓ Основная панель работает. Создание профиля могло перезапустить Xray на дополнительных нодах.'
echo "Резервная копия: $BACKUP"
