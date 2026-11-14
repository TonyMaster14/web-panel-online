#!/usr/bin/env bash
# WPO focused compatibility repair: standard Happ links for single-node subscriptions.
# Does not modify users, subscriptions, node agents, Xray, Caddy, or VPN credentials.
set -Eeuo pipefail
umask 077
[[ ${EUID} -eq 0 ]] || { echo 'Запустите с sudo на основном VPS WPO.' >&2; exit 1; }
APP=/opt/tproxy-panel/panel.py
SERVICE=tproxy-panel.service
[[ -s "$APP" && -s /etc/systemd/system/tproxy-panel.service ]] || {
  echo 'Основная WPO на этом VPS не найдена. Ничего не изменено.' >&2; exit 2;
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Другое обновление WPO выполняется. Ничего не изменено.' >&2; exit 2; }
TMP="$(mktemp -d /tmp/wpo-happ-single.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/panel-happ-single-$(date -u +%Y%m%dT%H%M%SZ).bak.py"
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )); then
    echo 'Ошибка проверки — восстанавливаю предыдущий panel.py.' >&2
    cp -a "$BACKUP" "$APP" || true
    rm -f /opt/tproxy-panel/__pycache__/panel.*.pyc
    systemctl restart "$SERVICE" || true
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
python3 - "$APP" "$TMP/panel.py" <<'PY'
from pathlib import Path
import ast
import sys

src=Path(sys.argv[1]).read_text(encoding='utf-8')
start='    def serve_subscription(self,token):'
end='    def serve_direct_profile(self,token):'
if src.count(start)!=1 or src.count(end)!=1:
    raise SystemExit('Неизвестная версия обработчика подписок. Исходный файл не изменён.')
head,rest=src.split(start,1)
handler,tail=rest.split(end,1)
original=handler

old_auto='            failover=bool(lines)'
new_auto='''            # wpo-happ-single-node-v1: no leastLoad for one node.
            distinct_nodes={urlparse(link).hostname for link in lines if urlparse(link).hostname}
            failover=bool(subscription.get("failover_enabled",True)) and len(distinct_nodes)>1'''
old_happ='if requested_format in ("xray","xray-json","json") or (happ and bool(xray_configs)):'
new_happ='if requested_format in ("xray","xray-json","json") or (happ and (selected_routing or failover)):'

if handler.count(old_auto)==1:
    handler=handler.replace(old_auto,new_auto,1)
elif 'failover=bool(subscription.get("failover_enabled",True)) and len(distinct_nodes)>1' not in handler:
    raise SystemExit('Не совпадает логика автовыбора. Патч не применён.')

if handler.count(old_happ)==1:
    handler=handler.replace(old_happ,new_happ,1)
elif handler.count(new_happ)!=1:
    raise SystemExit('Не совпадает формат Happ JSON. Патч не применён.')

if handler.count('distinct_nodes={urlparse(link).hostname for link in lines if urlparse(link).hostname}')!=1:
    raise SystemExit('Не найдена проверка числа отдельных нод.')
if handler.count('failover=bool(subscription.get("failover_enabled",True)) and len(distinct_nodes)>1')!=1:
    raise SystemExit('Не найдена безопасная логика автовыбора.')
if handler.count(new_happ)!=1:
    raise SystemExit('Happ JSON должен сохраняться и для одной ноды.')

result=head+start+handler+end+tail
ast.parse(result,filename='panel.py')
Path(sys.argv[2]).write_text(result,encoding='utf-8')
print('✓ Проверка: автовыбор только для нескольких разных серверов.')
print('✓ Проверка: одиночная нода отдаёт стандартные VLESS/Hysteria ссылки.')
print('✓ Проверка: Xray JSON сохранён для явного запроса, специальных правил и автовыбора нескольких нод.')
print('✓ Проверка: существующие ключи и ссылки подписок не изменяются.')
PY
python3 -m py_compile "$TMP/panel.py"
if cmp -s "$APP" "$TMP/panel.py"; then
  echo '✓ Это исправление уже установлено. Повторное обновление не требуется.'
  exit 0
fi
cp -a "$APP" "$BACKUP"
CHANGED=1
install -o root -g root -m 0755 "$TMP/panel.py" "$APP"
rm -f /opt/tproxy-panel/__pycache__/panel.*.pyc
systemctl restart "$SERVICE"
PANEL_PATH="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service | head -n1)"
[[ "$PANEL_PATH" =~ ^/panel-[a-z0-9-]{3,64}$ ]] || { echo 'Путь WPO не определён.' >&2; exit 3; }
HEALTHY=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if systemctl is-active --quiet "$SERVICE" &&
     curl -4fsS --max-time 3 "http://127.0.0.1:8090${PANEL_PATH}/__health" | grep -qx 'OK'; then
      HEALTHY=1
      break
  fi
  sleep 1
done
(( HEALTHY == 1 )) || { echo 'WPO не ответила после перезапуска. Выполняется откат.' >&2; exit 3; }
cmp -s "$APP" "$TMP/panel.py" || { echo 'Установленная версия не совпадает с проверенной.' >&2; exit 3; }
CHANGED=0
echo '✓ Исправление Happ установлено. Служба WPO работает.'
echo '✓ Одиночная нода — стандартная ссылка VLESS/Hysteria без лишнего Xray JSON и «Автовыбора».'
echo '✓ Для пользовательской маршрутизации и нескольких нод JSON сохранён.'
echo '✓ В Happ обновите подписку; если старый JSON сохранён в приложении, удалите только профиль Happ и импортируйте тот же URL снова.'
echo "Резервная копия кода: $BACKUP"
