#!/usr/bin/env bash
# WEB PANEL ONLINE - repair the actual root cause of empty/public sites.
# The relay previously stopped with the last WEB client, although it serves
# the HTTPS website for every domain.
set -Eeuo pipefail
umask 077

[[ $EUID -eq 0 ]] || { echo "Запустите от root на основном VPS панели." >&2; exit 1; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
MANAGER=/usr/local/sbin/web-proxy-panelctl
PROFILES=/etc/tproxy-server/profiles.json
CONFIG=/etc/tproxy-server/config.json
RELAY=tproxy-server.service
PANEL_SERVICE=tproxy-panel.service
OVERRIDE=/etc/systemd/system/tproxy-server.service.d/30-wpp-public-site.conf
REF=4fdd087830df987c8e5f9f399c1e09121c5e3c12
SOURCE_URL="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/install-panel.sh"
[[ -s "$PANEL" && -s "$MANAGER" && -s "$PROFILES" && -s "$CONFIG" ]] ||
    { echo "Не найдены необходимые файлы работающей панели. Ничего не изменено." >&2; exit 1; }
command -v flock >/dev/null || { echo "flock не найден." >&2; exit 1; }
exec 9>/run/lock/web-panel-proxy.lock
flock -w 10 9 || { echo "Другое обновление ещё работает." >&2; exit 1; }

STAGE="$(mktemp -d /tmp/wpp-site-relay.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/site-relay-backup-$(date -u +%Y%m%dT%H%M%SZ)"
TOUCHED=0
finish() {
    local rc=$?
    trap - EXIT
    if (( rc != 0 && TOUCHED )); then
        echo "Возвращаю файлы панели и настройки релея из резервной копии…" >&2
        cp -a "$BACKUP/panel.py" "$PANEL" || true
        cp -a "$BACKUP/web-proxy-panelctl" "$MANAGER" || true
        cp -a "$BACKUP/profiles.json" "$PROFILES" || true
        if [[ -f "$BACKUP/override.conf" ]]; then
            cp -a "$BACKUP/override.conf" "$OVERRIDE" || true
        else
            rm -f -- "$OVERRIDE"
        fi
        systemctl daemon-reload || true
        systemctl try-restart "$RELAY" "$PANEL_SERVICE" >/dev/null 2>&1 || true
        echo "Причина ошибки запуска сайта (без изменения паролей):" >&2
        journalctl -u "$RELAY" -n 12 --no-pager --output=cat 2>/dev/null |
          sed -E 's/(secret|token|password)=[^ ]+/\1=[hidden]/Ig' >&2 || true
    fi
    rm -rf -- "$STAGE"
    exit "$rc"
}
trap finish EXIT
install -d -m 0700 "$BACKUP"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$MANAGER" "$BACKUP/web-proxy-panelctl"
cp -a "$PROFILES" "$BACKUP/profiles.json"
[[ ! -f "$OVERRIDE" ]] || cp -a "$OVERRIDE" "$BACKUP/override.conf"

echo "[1/5] Загрузка фиксированной версии ядра публикации (без полной установки)..."
curl -4fsSL --retry 3 --connect-timeout 10 --max-time 90 "$SOURCE_URL" -o "$STAGE/install-panel.sh"
bash -n "$STAGE/install-panel.sh"

echo "[2/5] Исправление причины отключения сайта при удалении WEB пользователей..."
# Rollback must also cover a Python patch that stops halfway through writing.
TOUCHED=1
python3 - "$MANAGER" "$PANEL" "$STAGE/install-panel.sh" <<'PY_PATCH'
from pathlib import Path
import os,re,sys,tempfile
manager_path=Path(sys.argv[1]);panel_path=Path(sys.argv[2])
reference=Path(sys.argv[3]).read_text(encoding="utf-8")
original_manager=manager_path.read_text(encoding="utf-8")
original_panel=panel_path.read_text(encoding="utf-8")
manager=original_manager
panel=original_panel

def section(text,start,end):
    first=text.find(start)
    last=text.find(end,first+len(start))
    if first<0 or last<0 or text.find(start,first+len(start))>=0:
        raise RuntimeError("Неизвестная версия программы, блок "+start)
    return text[first:last]

def swap(src,start,end,expected):
    new=section(reference,start,end)
    old=section(src,start,end)
    if expected not in new:
        raise RuntimeError("В репозитории не найдено ожидаемое исправление "+start)
    return src.replace(old,new,1)

# Exact function replacement only for the profile loader and economy switch.
# Both functions have no Nodes Lab code in the current official release.
manager=swap(manager,"def sync_profiles(d):","\ndef sync_firewall(","wpo-site-always-on-v5")
manager=swap(manager,"def set_mtproxy_economy(request):","\ndef wake_primary_proxy_if_needed(","sync_profiles(d)")

# Patch the one stopping condition, not the entire manager apply() function,
# which could contain operator-specific or newer Node Lab additions.
old='''            if web_changed and not os.path.exists(MTPROXY_ECONOMY):
                with open(PROFILES,encoding="utf-8") as stream:
                    relay_profiles=json.load(stream).get("profiles",[])
                if relay_profiles:
                    run("systemctl","enable","tproxy-server.service",check=True)
                    run("systemctl","restart","tproxy-server.service",check=True)
                else:
                    # No public WEB Proxy profiles remain. Disable the relay
                    # instead of restarting it with an invalid empty profile set.
                    run("systemctl","disable","--now","tproxy-server.service",check=True)'''
new='''            if web_changed:
                # The site must remain alive with zero WEB Proxy clients.
                run("systemctl","enable","tproxy-server.service",check=True)
                run("systemctl","restart","tproxy-server.service",check=True)'''
if old in manager:
    manager=manager.replace(old,new,1)
elif new not in manager:
    raise RuntimeError("Менеджер имеет другой способ отключения релея; автоматическое исправление остановлено.")

# Expose real failure diagnostics in the panel, instead of the unhelpful
# 'Relay health endpoint did not become ready' message.
panel=swap(panel,"def restart_public_site():","def fetch_published(","wpo-site-always-on-v5")

for label,source in (("manager",manager),("panel",panel)):
    before=original_manager if label=="manager" else original_panel
    if not set(re.findall(r'wpo-node-[^\n]+',before)).issubset(set(re.findall(r'wpo-node-[^\n]+',source))):
        raise RuntimeError("Обнаружено изменение Nodes Lab в "+label+"; отказ в обновлении.")
    compile(source,label,"exec")

def atomic(path,code):
    if path.read_text(encoding="utf-8")==code:return
    st=path.stat()
    fd,temp=tempfile.mkstemp(prefix=".wpp-site-fix-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(code);f.flush();os.fsync(f.fileno())
        os.chown(temp,st.st_uid,st.st_gid)
        os.chmod(temp,st.st_mode & 0o777)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

atomic(manager_path,manager)
atomic(panel_path,panel)
print("✓ WEB Proxy можно удалять без остановки сайта.")
PY_PATCH

echo "[3/5] Независимая работа сайта от экономии MTProxy..."
install -d -m 0755 "$(dirname "$OVERRIDE")"
cat > "$OVERRIDE" <<'UNIT'
[Unit]
Wants=
Wants=network-online.target
UNIT
chmod 0644 "$OVERRIDE"
systemctl daemon-reload

# The upstream relay requires >=1 profile to serve *any* static web page.
# When all WEB clients and the primary profile were removed, create a secret,
# internal-only standby profile without altering any client/node credentials.
python3 - "$PROFILES" <<'PY_PROFILES'
from pathlib import Path
import json,os,secrets,sys,tempfile
path=Path(sys.argv[1]);data=json.loads(path.read_text(encoding="utf-8"))
items=data.get("profiles")
if not isinstance(items,list):
    raise RuntimeError("Неизвестная конфигурация релея: profiles не является списком.")
if items:
    print("✓ Существующие профили релея сохранены без изменений.")
else:
    data["profiles"]=[{"name":"wpp-site-standby",
                       "secret":secrets.token_hex(16),
                       "backend":"127.0.0.1:2398",
                       "carrier_mode":"https"}]
    stat=path.stat()
    fd,temp=tempfile.mkstemp(prefix=".wpp-site-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,indent=2)
            stream.write("\n")
            stream.flush();os.fsync(stream.fileno())
        os.chown(temp,stat.st_uid,stat.st_gid)
        os.chmod(temp,stat.st_mode & 0o777)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    print("✓ Создан закрытый служебный профиль для сайта (не для пользователей).")
PY_PROFILES

# This checks JSON, identities and static site files before touching services.
if ! /usr/local/bin/tproxy-server -config "$CONFIG" -profiles-file "$PROFILES" -check >/dev/null; then
    echo "Проверка конфигурации релея не прошла. Изменения отменены." >&2
    exit 1
fi
if ! runuser -u tproxy -- test -r /srv/tproxy-site/index.html; then
    echo "Ошибка прав: служба tproxy не может прочитать главную страницу сайта." >&2
    exit 1
fi

echo "[4/5] Запуск веб-сервера для домена (MTProxy и ноды не перезапускаем)..."
systemctl enable "$RELAY" >/dev/null
systemctl restart "$RELAY"
READY=0
for attempt in $(seq 1 20); do
    if curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 2 \
        'http://127.0.0.1:8081/healthz' 2>/dev/null | grep -Fxq ok; then
        READY=1;break
    fi
    sleep 0.4
done
if (( ! READY )); then
    echo "Веб-сервер не запустился. Состояние: $(systemctl is-active "$RELAY" || true)" >&2
    exit 1
fi

# Confirm that its *public* listener answers as the configured domain.
DOMAIN="$(python3 - "$CONFIG" <<'PY_DOMAIN'
import json,sys
print(json.load(open(sys.argv[1],encoding="utf-8"))["public_hostname"])
PY_DOMAIN
)"
curl -4fsS --noproxy '*' --connect-timeout 2 --max-time 5 \
  -H "Host: $DOMAIN" "http://127.0.0.1:8080/?wpp-relay-ready=1" -o "$STAGE/site.html"
[[ -s "$STAGE/site.html" ]] || { echo "Пустой ответ релея." >&2; exit 1; }

echo "[5/5] Перезапуск панели для новой публикации..."
python3 -m py_compile "$PANEL" "$MANAGER"
systemctl restart "$PANEL_SERVICE"
systemctl is-active --quiet "$PANEL_SERVICE"
echo
echo "✓ Сервер сайта запущен, даже если WEB Proxy отключён."
echo "✓ Ноды, подписки, пользователи и пароли сохранены."
echo "✓ Теперь применяйте шаблон кнопкой «Применить» в разделе Настройки."
echo "✓ Резервная копия: $BACKUP"
