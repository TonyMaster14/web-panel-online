#!/usr/bin/env bash
# WPO TEST controller bridge: live VPN capabilities and multi-node subscriptions.
# Run on the MAIN panel VPS only, not on additional nodes.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo 'Run as root on the WPO controller VPS.' >&2; exit 1; }
APP=/opt/tproxy-panel/panel.py
SERVICE=tproxy-panel.service
[[ -s "$APP" ]] || { echo 'WPO controller is not installed.' >&2; exit 2; }
if [[ "${WPO_NODES_VPN_DURING_INSTALL:-0}" != 1 ]]; then
    exec 8>/run/lock/web-panel-proxy.lock
    flock -n 8 || { echo 'Another WPO installation/update is active.' >&2; exit 2; }
fi
if grep -Fq '# wpo-vpn-controller-v27' "$APP"; then
    echo 'WPO VPN controller bridge already installed.'
    exit 0
fi
BACKUP="/var/lib/tproxy-panel/controller-vpn-backup-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$APP" "$BACKUP"
RESTORE=1
rollback(){
    rc=$?
    trap - EXIT
    if (( rc != 0 && RESTORE == 1 )); then
        cp -a "$BACKUP" "$APP" || true
        if [[ "${WPO_NODES_BATCH_RESTART:-0}" != 1 ]]; then
            systemctl restart "$SERVICE" || true
        fi
        echo "Controller restored from $BACKUP" >&2
    fi
    exit "$rc"
}
trap rollback EXIT
python3 - "$APP" <<'PY_PATCH'
from pathlib import Path
import sys
path=Path(sys.argv[1]);source=path.read_text(encoding='utf-8')
def swap(old,new,label):
    global source
    if source.count(old)!=1:
        raise SystemExit('Unexpected controller version; no patch applied: '+label)
    source=source.replace(old,new)

# The node status endpoint is refreshed by the browser every few seconds.
# Refresh CAPABILITIES too, otherwise an existing 0.2 node stays listed as
# "site-only" after an in-place VPN upgrade to v0.3.
swap('''                    node["version"]=str(state.get("version",node.get("version","")))[:32]
                    node["status_checked_at"]=now''',
'''                    node["version"]=str(state.get("version",node.get("version","")))[:32]
                    node["capabilities"]=[str(c)[:32] for c in state.get("capabilities",[]) if isinstance(c,str)][:16]
                    node["status_checked_at"]=now''','live capability refresh')

# Do NOT trust old cached capabilities when provisioning: query the node live,
# require the EXACT protocol set selected by the user, then allow creation.
swap('''                registered=node_api.load_nodes(NODES_FILE)
                unsupported=[n for n in registered if n.get("id") in chosen_nodes and isinstance(n.get("capabilities"),list) and n.get("capabilities") and "federation" not in n.get("capabilities",[])]
                if unsupported:
                    create_error("Нода зарегистрирована, но установка VPN-служб и выпуск профилей на ней — следующий этап тестирования. Подписка не создана.",409); return''',
'''                # wpo-vpn-controller-v27: no phantom remote connections
                registered=node_api.load_nodes(NODES_FILE)
                wanted_protocols={str(item.get("protocol","")) for item in connection_specs}
                unavailable=[]
                for node in registered:
                    if node.get("id") not in chosen_nodes: continue
                    try:
                        status=node_api.request(node,"GET",node_api.API_PREFIX+"/status",timeout=5)
                        caps=set(status.get("capabilities",[]))
                        if not status.get("ok") or "federation" not in caps or not wanted_protocols.issubset(caps):
                            unavailable.append(node)
                    except node_api.NodeError:
                        unavailable.append(node)
                if unavailable:
                    create_error("VPN-службы выбранной ноды недоступны или не поддерживают нужные протоколы. Обновите Node Agent и проверьте Xray.",409); return''',
     'node live capability validation')

# The actual sync endpoint will reject unsupported agents. Do not silently
# omit a VPN-enabled node because old registry capabilities are still cached.
swap('''                    capabilities=node.get("capabilities")
                    if isinstance(capabilities,list) and capabilities and "federation" not in capabilities: continue
                    try:''',
'''                    # wpo-vpn-controller-v27: use authenticated federation API
                    try:''',
     'remove stale capability skip')

compile(source,str(path),'exec')
temp=path.with_suffix('.vpn-test')
temp.write_text(source,encoding='utf-8')
temp.chmod(0o755)
temp.replace(path)
PY_PATCH
python3 -m py_compile "$APP"
if [[ "${WPO_NODES_BATCH_RESTART:-0}" != 1 ]]; then
    systemctl restart "$SERVICE"
    systemctl is-active --quiet "$SERVICE" || {
        echo 'Controller did not restart with VPN patch.' >&2; exit 3; }
fi
RESTORE=0
echo '✓ WPO controller: live remote-node capability validation enabled.'
echo '✓ Subscription feed no longer ignores freshly upgraded VPN nodes.'
