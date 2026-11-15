#!/usr/bin/env bash
# WPO single-entrypoint repair from MAIN PANEL VPS. The controller-only API
# cannot change remote Caddy/relay services, so affected nodes need root SSH.
# Does not SSH into the main node or change its Xray/Happ subscriptions.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите команду через sudo на ОСНОВНОЙ панели WPO.' >&2; exit 2; }
PANEL=/opt/tproxy-panel/panel.py
REGISTRY=/var/lib/tproxy-panel
[[ -s "$PANEL" && -d "$REGISTRY" && ! -e /etc/wpp-node-agent/config.json ]] || {
    echo 'Этот установщик предназначен ТОЛЬКО для основного VPS WPO, не для дополнительной ноды.' >&2
    exit 2
}
command -v ssh >/dev/null || { echo 'SSH-клиент отсутствует на основном VPS.' >&2; exit 2; }
command -v curl >/dev/null || { echo 'curl отсутствует на основном VPS.' >&2; exit 2; }
WORK="$(mktemp -d /tmp/wpo-main-site-repair.XXXXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT

# Discover the actual WPO registered-node JSON, do not assume a specific
# name. Never print or pass API keys, one-time install tokens, or passwords.
python3 - "$REGISTRY" > "$WORK/nodes.tsv" <<'PY_NODES'
import json,re,sys,urllib.parse
from pathlib import Path
root=Path(sys.argv[1])
candidates=[]
for path in sorted(root.glob("*.json")):
    if not path.is_file():
        continue
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,UnicodeError):
        continue
    if not isinstance(data,list):
        continue
    nodes=[]
    for item in data:
        if not isinstance(item,dict):
            continue
        uid=item.get("id")
        raw=item.get("url")
        if not isinstance(uid,str) or not re.fullmatch(r"[a-f0-9]{16}",uid):
            continue
        if not isinstance(raw,str):
            continue
        parsed=urllib.parse.urlsplit(raw)
        host=(parsed.hostname or "").lower()
        if (parsed.scheme!="https" or parsed.username or parsed.password or
            parsed.path not in ("","/") or parsed.query or parsed.fragment or
            parsed.port not in (None,443) or not
            re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",host)):
            continue
        if item.get("enabled",True):
            nodes.append((uid,host))
    if nodes:
        candidates.append((path,nodes))
if len(candidates)!=1:
    raise SystemExit("Не удалось однозначно найти реестр дополнительных нод WPO. Ничего на нодах не менялось.")
seen=set()
for uid,host in candidates[0][1]:
    if host in seen:
        continue
    seen.add(host)
    print(uid+"\t"+host)
PY_NODES
[[ -s "$WORK/nodes.tsv" ]] || { echo 'Дополнительные ноды WPO не найдены.' >&2; exit 2; }

# Use immutable, CI-tested versions on this test branch. Save the latest
# installer for future nodes using the controller's existing safe updater.
BASE=https://raw.githubusercontent.com/TonyMaster14/web-panel-online
CONTROLLER_REV=56a4d5b9e2aafdc8bf6e407901a91199d8ec9738
REPAIR_REV=c7a026d48cf928b5f10b988199baff433cc36698
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
    --connect-timeout 12 --max-time 90 \
    "$BASE/$CONTROLLER_REV/wpo-nodes-routing-update.sh" -o "$WORK/main-update.sh"
curl -4fsSL --proto '=https' --proto-redir '=https' --retry 3 \
    --connect-timeout 12 --max-time 90 \
    "$BASE/$REPAIR_REV/wpo-node-site-template-fix.sh" -o "$WORK/site-repair.sh"
bash -n "$WORK/main-update.sh"
bash -n "$WORK/site-repair.sh"
grep -Fq 'PATCH_REV=c339beaa3702af5c48769c688833b09268427b2c' "$WORK/main-update.sh" || {
    echo 'Неожиданная версия обновления WPO. Ничего не изменено.' >&2; exit 3;
}
grep -Fq 'public_upstream' "$WORK/site-repair.sh" || {
    echo 'Неожиданная версия исправления сайтов. Ничего не изменено.' >&2; exit 3;
}

echo '=== ОСНОВНАЯ WPO: обновление установщика новых нод ==='
bash "$WORK/main-update.sh"
echo
echo '=== ВОССТАНОВЛЕНИЕ ШАБЛОНОВ НА ПОДКЛЮЧЁННЫХ НОДАХ ==='
echo 'Если требуется, SSH запросит пароль root или авторизацию по ключу для каждой ноды.'
echo 'Пароли и API-ключи в WPO/GitHub не отправляются.'
success=0
failure=0
while IFS=$'\t' read -r node_id host; do
    [[ -n "$host" ]] || continue
    echo "→ Нода $host"
    # Verify this exact Node Agent domain on remote host *before* executing
    # any maintenance. Host is strict lowercase DNS name, validated above.
    remote_check="test \"\$(python3 -c 'import json;print(json.load(open(\"/etc/wpp-node-agent/config.json\"))[\"domain\"])')\" = '$host' && bash -s"
    if ssh -T \
       -o ConnectTimeout=8 \
       -o ConnectionAttempts=1 \
       -o StrictHostKeyChecking=accept-new \
       -o NumberOfPasswordPrompts=2 \
       -o ServerAliveInterval=5 \
       -o ServerAliveCountMax=2 \
       "root@$host" "$remote_check" < "$WORK/site-repair.sh"; then
        echo "✓ $host: шаблон сайта восстановлен, VPN оставлен без изменений."
        success=$((success+1))
    else
        echo "✗ $host: исправление не выполнено. Проверьте SSH-доступ root с основной панели." >&2
        failure=$((failure+1))
    fi
done < "$WORK/nodes.tsv"
echo
echo "Результат: исправлено $success; не удалось подключиться/исправить $failure."
echo 'Установщик будущих нод обновлён; основная VPN-нода и подписки не изменялись.'
if (( failure > 0 )); then
    echo 'Для неуспешных нод необходим SSH-доступ с основного VPS; через один API WPO серверные службы менять нельзя.' >&2
    exit 6
fi
echo '✓ WPO: шаблоны сайтов восстановлены на всех доступных зарегистрированных нодах.'
