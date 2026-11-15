#!/usr/bin/env bash
# Update only the controller's generated Happ Auto-select configuration.
# Does not change subscriber keys, node agents, Xray servers or Caddy.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Нужен sudo на основной WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
MODULE="$APP/wpp_routing.py"
[[ -s "$MODULE" && -s "$APP/panel.py" && ! -e /etc/wpp-node-agent/config.json ]] || {
  echo 'Нужна основная панель WPO; изменений нет.' >&2; exit 2;
}
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || { echo 'Другое обновление WPO выполняется.' >&2; exit 2; }
RELEASE_REV=8fe127085605acf76452973d00099e7d95c1dae3
WORK=$(mktemp -d /tmp/wpo-autoselect.XXXXXXXX)
BACKUP=''
CHANGED=0
cleanup(){
  code=$?
  trap - EXIT
  if [[ "$CHANGED" == 1 ]]; then
    echo 'Панель не прошла проверку; возвращаю прежний модуль.' >&2
    cp -a "$BACKUP/wpp_routing.py" "$MODULE" || true
    rm -f "$APP"/__pycache__/wpp_routing.*.pyc
    systemctl restart tproxy-panel.service || true
  fi
  rm -rf -- "$WORK"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
  --connect-timeout 12 --max-time 90 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$RELEASE_REV/wpp_routing.py" \
  -o "$WORK/wpp_routing.py"
python3 - "$WORK/wpp_routing.py" <<'PY'
import ast,runpy,sys
from pathlib import Path
path=Path(sys.argv[1]);source=path.read_text();ast.parse(source)
if '# wpo-live-failover-v2:' not in source:raise SystemExit('Неверная версия модуля')
module=runpy.run_path(str(path))
links=[f'vless://11111111-1111-4111-8111-111111111111@{host}.example:443?type=xhttp'
       for host in ('nl','pl','se')]
cfg=module['failover_xray_config'](links)
bal=cfg['routing']['balancers'][0]
assert bal['strategy']['type']=='leastPing'
assert bal['fallbackTag']=='block'
assert cfg['observatory']['enableConcurrency'] is True
assert cfg['observatory']['probeInterval']=='10s'
assert len([o for o in cfg['outbounds'] if o['tag'].startswith('proxy-')])==3
print('✓ Конфигурация автовыбора проверена.')
PY
PANEL_PATH=$(python3 - <<'PY'
import re,shlex,subprocess
value=subprocess.check_output(['systemctl','show','tproxy-panel.service',
                               '-p','Environment','--value'],text=True)
for item in shlex.split(value):
    if item.startswith('WEBPROXY_PANEL_PATH='):
        path=item.split('=',1)[1]
        if re.fullmatch(r'/panel-[a-zA-Z0-9_-]{3,80}',path):
            print(path);break
else:raise SystemExit('Не найден путь проверки основной панели')
PY
)
if cmp -s "$WORK/wpp_routing.py" "$MODULE"; then
  echo '✓ Эта версия уже установлена. Обновите подписку в Happ и переподключите Автовыбор.'
  exit 0
fi
BACKUP=$(mktemp -d /var/lib/tproxy-panel/auto-select-backup.XXXXXXXX)
cp -a "$MODULE" "$BACKUP/wpp_routing.py"
CHANGED=1
install -o root -g root -m 0644 "$WORK/wpp_routing.py" "$MODULE"
rm -f "$APP"/__pycache__/wpp_routing.*.pyc
systemctl restart tproxy-panel.service
READY=0
for attempt in {1..15}; do
  if systemctl is-active --quiet tproxy-panel.service &&
     [[ $(curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
         "http://127.0.0.1:8090$PANEL_PATH/__health" 2>/dev/null) == OK ]]; then
    READY=1; break
  fi
  sleep 1
done
[[ "$READY" == 1 ]] || exit 4
cmp -s "$WORK/wpp_routing.py" "$MODULE" || exit 4
CHANGED=0
echo '✓ Автовыбор обновлён. Ключи и ноды сохранены.'
echo 'В Happ: обновите подписку, выберите Автовыбор, отключите и включите подключение.'
echo "Резервная копия: $BACKUP"
