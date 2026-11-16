#!/usr/bin/env bash
# WPO test-only: update REALITY defaults/UI code, not live VPN configuration.
# Run only on the controller VPS; no action is required on remote nodes.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Запустите через sudo на VPS основной панели WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
SERVICE=tproxy-panel.service
REF=cb3a516a44e7631d2d239c472de497cd14ddeb62
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/src"
for name in panel.py wpo_reality.py wpo_reality_ui.py; do
  [[ -s "$APP/$name" && ! -L "$APP/$name" ]] || { echo "Не найден компонент REALITY: $APP/$name" >&2; exit 2; }
done
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба WPO не найдена.' >&2; exit 2; }
command -v curl >/dev/null && command -v python3 >/dev/null || exit 2
WORK="$(mktemp -d /tmp/wpo-reality-ui.XXXXXXXX)"
BACKUP=""
TOUCHED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if ((rc != 0 && TOUCHED == 1)) && [[ -n "$BACKUP" && -d "$BACKUP" ]]; then
     for name in wpo_reality.py wpo_reality_ui.py; do cp -a "$BACKUP/$name" "$APP/$name" || true; done
     systemctl restart "$SERVICE" || true
     echo 'Обновление не удалось. Старые файлы панели восстановлены.' >&2
  fi
  rm -rf -- "$WORK"
  exit "$rc"
}
trap cleanup EXIT
for name in wpo_reality.py wpo_reality_ui.py; do
  curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 --proto '=https' \
     "$BASE/$name" -o "$WORK/$name"
  python3 -m py_compile "$WORK/$name"
done
if ! grep -Fq "'preset': 'nvidia', 'sni': 'www.nvidia.com'" "$WORK/wpo_reality.py" ||
   grep -Fq "'microsoft':" "$WORK/wpo_reality.py" ||
   ! grep -Fq 'wpo-main-node-label' "$WORK/wpo_reality_ui.py" ||
   ! grep -Fq 'selected_preset(profile)' "$WORK/wpo_reality_ui.py"; then
  echo 'Получена неверная версия компонентов. Ничего не изменено.' >&2
  exit 3
fi
if cmp -s "$WORK/wpo_reality.py" "$APP/wpo_reality.py" &&
   cmp -s "$WORK/wpo_reality_ui.py" "$APP/wpo_reality_ui.py"; then
  echo 'WPO: NVIDIA и размещение карандаша уже обновлены.'
  exit 0
fi
install -d -m 0700 /var/backups/web-panel-online
BACKUP="/var/backups/web-panel-online/reality-nvidia-ui-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
for name in wpo_reality.py wpo_reality_ui.py; do
  cp -a "$APP/$name" "$BACKUP/$name"
done
echo "Резервная копия: $BACKUP"
TOUCHED=1
for name in wpo_reality.py wpo_reality_ui.py; do
  STAGE="$(mktemp "$APP/.wpo-reality-ui.XXXXXXXX.py")"
  cp "$WORK/$name" "$STAGE"
  chown --reference="$APP/$name" "$STAGE"
  chmod --reference="$APP/$name" "$STAGE"
  mv -f "$STAGE" "$APP/$name"
done
python3 -m py_compile "$APP/wpo_reality.py" "$APP/wpo_reality_ui.py"
systemctl restart "$SERVICE"
READY=0
ROUTE="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
[[ "$ROUTE" =~ ^/panel-[a-z0-9-]{3,64}$ ]] || { echo 'Не найден адрес панели.' >&2; exit 4; }
for attempt in $(seq 1 12); do
  if systemctl is-active --quiet "$SERVICE" &&
     curl -4fsS --max-time 2 "http://127.0.0.1:8090$ROUTE/__health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
(( READY == 1 )) || { echo 'Панель не прошла проверку после обновления.' >&2; exit 4; }
TOUCHED=0
echo 'WPO: NVIDIA по умолчанию; Microsoft удалён из пресетов REALITY.'
echo 'Карандаш основной ноды расположен справа в нижнем ряду.'
echo 'Ноды, подписки, ключи и действующие параметры SNI не изменялись.'
