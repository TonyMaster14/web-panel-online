#!/usr/bin/env bash
# WPO TEST: preserve Happ REALITY links across decoy transitions on main panel.
# Does not rotate keys, UUIDs, Short IDs, change the preferred SNI or install nodes.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Запустите с sudo на VPS основной панели WPO." >&2; exit 2; }
APP=/opt/tproxy-panel
MANAGER=/usr/local/sbin/web-proxy-panelctl
XRAY=/opt/web-panel-proxy/xray/xray
XRAY_CONF=/etc/web-panel-proxy-xray/config.json
REALITY=/etc/web-proxy-panel/reality
MODULE="$APP/wpo_reality.py"
REV=a3d7a3084cbe09b2fb7d5fe23321393930659b3a
URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/src/wpo_reality.py"
for file in "$APP/panel.py" "$MODULE" "$MANAGER" "$XRAY_CONF" "$REALITY/profile.json" "$REALITY/private.key" "$REALITY/haproxy.cfg"; do
    [[ -s "$file" && ! -L "$file" ]] || { echo "Не найден REALITY компонент основной панели: $file" >&2; exit 2; }
done
for unit in web-panel-proxy-xray.service wpo-tls-router.service tproxy-panel.service; do
    systemctl is-active --quiet "$unit" || { echo "Неактивна служба $unit. Не меняю конфигурации." >&2; exit 2; }
done
WORK="$(mktemp -d /tmp/wpo-compat-panel.XXXXXXXX)"
BACKUP=""
INSTALLED=0
cleanup() {
    local code=$?
    trap - EXIT
    if (( code != 0 && INSTALLED == 1 )) && [[ -n "$BACKUP" && -d "$BACKUP" ]]; then
        echo "Ошибка обновления: восстанавливаю прежний REALITY основной панели..." >&2
        cp -a "$BACKUP/wpo_reality.py" "$MODULE" || true
        cp -a "$BACKUP/haproxy.cfg" "$REALITY/haproxy.cfg" || true
        cp -a "$BACKUP/xray.json" "$XRAY_CONF" || true
        cp -a "$BACKUP/profile.json" "$REALITY/profile.json" || true
        systemctl restart web-panel-proxy-xray.service wpo-tls-router.service tproxy-panel.service || true
        echo "Резервная копия: $BACKUP" >&2
    fi
    rm -rf -- "$WORK"
    exit "$code"
}
trap cleanup EXIT
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 75 --proto '=https' \
    "$URL" -o "$WORK/wpo_reality.py"
python3 -m py_compile "$WORK/wpo_reality.py"
grep -Fq "def reality_routes(" "$WORK/wpo_reality.py" &&
grep -Fq "config['inbounds'].extend(inbounds(clients))" "$WORK/wpo_reality.py" ||
    { echo "Получена неподходящая версия REALITY панели." >&2; exit 3; }
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 75 --proto '=https' \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REV/scripts/wpo-reality-compat-smoke.py" -o "$WORK/compat-smoke.py"
python3 -m py_compile "$WORK/compat-smoke.py"
PYTHONPATH="$WORK:$APP" python3 - "$WORK" <<'PY'
import copy,json,sys
from pathlib import Path
import wpo_reality as r
folder=Path(sys.argv[1])
profile=r.read_profile()
existing=json.loads(Path('/etc/web-panel-proxy-xray/config.json').read_text())
old=[x for x in existing.get('inbounds',[]) if x.get('streamSettings',{}).get('security')=='reality']
if len(old)!=1:raise SystemExit('В панели ожидался один REALITY backend. Ничего не изменено.')
clients=old[0].get('settings',{}).get('clients',[])
new=r.inbounds(clients,profile)
candidate=copy.deepcopy(existing)
candidate['inbounds']=[x for x in candidate['inbounds']
    if x.get('streamSettings',{}).get('security')!='reality']+new
(folder/'candidate-xray.json').write_text(json.dumps(candidate))
(folder/'candidate-haproxy.cfg').write_text(r.haproxy_config(profile['sni']))
assert len(new)==len(r.reality_routes(profile))
assert 'www.microsoft.com' not in {n['streamSettings']['realitySettings']['serverNames'][0] for n in new}
PY
"$XRAY" run -test -config "$WORK/candidate-xray.json" >/dev/null
haproxy -c -f "$WORK/candidate-haproxy.cfg" >/dev/null
BACKUP="/var/backups/web-panel-online/reality-compat-panel-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 /var/backups/web-panel-online "$BACKUP"
cp -a "$MODULE" "$BACKUP/wpo_reality.py"
cp -a "$XRAY_CONF" "$BACKUP/xray.json"
cp -a "$REALITY/haproxy.cfg" "$BACKUP/haproxy.cfg"
cp -a "$REALITY/profile.json" "$BACKUP/profile.json"
echo "Резервная копия: $BACKUP"
STAGE="$(mktemp "$APP/.wpo-reality-compat.XXXXXXXX.py")"
cp "$WORK/wpo_reality.py" "$STAGE"
chown --reference="$MODULE" "$STAGE"
chmod --reference="$MODULE" "$STAGE"
INSTALLED=1
mv -f "$STAGE" "$MODULE"
# Apply already saved REALITY settings, with identical UUID, keys and SNI.
PYTHONPATH="$APP" python3 - <<'PY'
import json,subprocess
from pathlib import Path
profile=json.loads(Path("/etc/web-proxy-panel/reality/profile.json").read_text())
request={k:profile[k] for k in ("preset","sni","fingerprint")}
result=subprocess.run(["/usr/local/sbin/web-proxy-panelctl","reality-config"],
    input=json.dumps(request),text=True,capture_output=True,timeout=100)
if result.returncode:raise RuntimeError("Не удалось активировать дополнительные REALITY backend")
response=json.loads(result.stdout)
if not response.get("ok"):raise RuntimeError("REALITY backend не подтверждены")
PY
systemctl restart tproxy-panel.service
for unit in web-panel-proxy-xray.service wpo-tls-router.service tproxy-panel.service; do
    systemctl is-active --quiet "$unit" || { echo "Служба $unit неактивна." >&2; exit 4; }
done
# Actual REALITY Vision HTTP 204 for each previously used SNI.
# Any failed handshake invokes the EXIT rollback to restore the panel.
python3 -u "$WORK/compat-smoke.py"
PYTHONPATH="$APP" python3 - <<'PY'
import json
from pathlib import Path
import wpo_reality as r
profile=r.read_profile()
cfg=json.loads(Path('/etc/web-panel-proxy-xray/config.json').read_text())
for host,port in r.reality_routes(profile):
    matches=[x for x in cfg['inbounds'] if x.get('port')==port
             and x.get('streamSettings',{}).get('security')=='reality']
    assert len(matches)==1
    assert matches[0]['streamSettings']['realitySettings']['target']==host+':443'
print("✓ Основная панель: отдельные Xray/HAProxy маршруты для NVIDIA, Apple, Yahoo, Amazon.")
PY
INSTALLED=0
echo "✓ Прежние профили Happ продолжают приниматься для поддерживаемых SNI."
echo "✓ Предпочтительный SNI, ключи, UUID, Short ID и пользователи не менялись."
echo "✓ Дополнительные VPS не изменены. Резервная копия сохранена."
