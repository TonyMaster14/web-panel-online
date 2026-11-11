#!/usr/bin/env bash
# WEB PANEL ONLINE 3.0 — website-only relay v6.
# Solves "profiles must contain between 1 and 32 entries", with NO fake WEB
# protocol. Build the pinned upstream Go relay with true zero-profile support.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Запустите от root на основном VPS панели." >&2; exit 1; }
APP=/opt/tproxy-panel
PANEL="$APP/panel.py"
MANAGER=/usr/local/sbin/web-proxy-panelctl
RELAY_BIN=/usr/local/bin/tproxy-server
RELAY=tproxy-server.service
PANEL_SERVICE=tproxy-panel.service
PROFILES=/etc/tproxy-server/profiles.json
CONFIG=/etc/tproxy-server/config.json
OVERRIDE=/etc/systemd/system/tproxy-server.service.d/30-wpp-public-site.conf
UPSTREAM=52a5feb7fac38f68da5afef9cedd9b3bfc8473ca
PATCH_REF=9229237d31444cd22b08479acfba4a090910f325
MANAGER_REF=4ac8929cb690e7038e8871f5698e0a98b414cc92
SOURCE=/root/tproxy-server

for file in "$PANEL" "$MANAGER" "$RELAY_BIN" "$PROFILES" "$CONFIG"; do
    [[ -s "$file" ]] || { echo "Отсутствует необходимый файл: $file. Ничего не изменено." >&2; exit 1; }
done
command -v flock >/dev/null || { echo "Для установки необходим flock." >&2; exit 1; }
exec 9>/run/lock/web-panel-proxy.lock
flock -w 15 9 || { echo "Установщик или обновление уже работает." >&2; exit 1; }

GO_BIN=""
for candidate in /opt/go1.26.5/bin/go /usr/local/go/bin/go /usr/bin/go; do
    if [[ -x "$candidate" ]]; then GO_BIN="$candidate"; break; fi
done
[[ -n "$GO_BIN" ]] || { echo "На сервере не найден установленный компилятор Go." >&2; exit 1; }

STAGE="$(mktemp -d /tmp/wpo-site-v6.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/site-only-v6-$(date -u +%Y%m%dT%H%M%SZ)"
TOUCHED=0
RELAY_WAS_ACTIVE="$(systemctl is-active "$RELAY" 2>/dev/null || true)"
RELAY_WAS_ENABLED="$(systemctl is-enabled "$RELAY" 2>/dev/null || true)"
finish() {
    local code=$?
    trap - EXIT
    if (( code != 0 && TOUCHED )); then
        echo "Ошибка исправления — возвращаю предыдущую версию файлов..." >&2
        if install -o root -g root -m 0755 "$BACKUP/tproxy-server" "$RELAY_BIN.wpo-v6-restore"; then
            mv -f -- "$RELAY_BIN.wpo-v6-restore" "$RELAY_BIN" || true
        fi
        cp -a "$BACKUP/web-proxy-panelctl" "$MANAGER" || true
        cp -a "$BACKUP/panel.py" "$PANEL" || true
        cp -a "$BACKUP/profiles.json" "$PROFILES" || true
        if [[ -f "$BACKUP/override.conf" ]]; then
            cp -a "$BACKUP/override.conf" "$OVERRIDE" || true
        else
            rm -f -- "$OVERRIDE"
        fi
        systemctl daemon-reload || true
        if [[ "$RELAY_WAS_ENABLED" != "enabled" ]]; then
            systemctl disable "$RELAY" >/dev/null 2>&1 || true
        fi
        if [[ "$RELAY_WAS_ACTIVE" == "active" ]]; then
            systemctl reset-failed "$RELAY" >/dev/null 2>&1 || true
            systemctl restart "$RELAY" >/dev/null 2>&1 || true
        else
            systemctl stop "$RELAY" >/dev/null 2>&1 || true
        fi
        systemctl try-restart "$PANEL_SERVICE" >/dev/null 2>&1 || true
        echo "Резервная копия: $BACKUP" >&2
        echo "Журнал релея (проверьте, нет ли секретов перед пересылкой):" >&2
        journalctl -u "$RELAY" -n 12 --no-pager --output=cat >&2 || true
    fi
    rm -rf -- "$STAGE"
    exit "$code"
}
trap finish EXIT

install -d -o root -g root -m 0700 "$BACKUP"
cp -a "$RELAY_BIN" "$BACKUP/tproxy-server"
cp -a "$MANAGER" "$BACKUP/web-proxy-panelctl"
cp -a "$PANEL" "$BACKUP/panel.py"
cp -a "$PROFILES" "$BACKUP/profiles.json"
[[ ! -f "$OVERRIDE" ]] || cp -a "$OVERRIDE" "$BACKUP/override.conf"

echo "[1/5] Подготовка исходного Go-релея (официальная зафиксированная версия)..."
mkdir -p "$STAGE/source"
if [[ -d "$SOURCE/.git" ]] && git -C "$SOURCE" cat-file -e "$UPSTREAM^{commit}" 2>/dev/null; then
    git -C "$SOURCE" archive "$UPSTREAM" | tar -xf - -C "$STAGE/source"
else
    mkdir -p "$STAGE/repository"
    git -C "$STAGE/repository" init -q
    git -C "$STAGE/repository" remote add origin https://github.com/telegramdesktop/tproxy-server.git
    git -C "$STAGE/repository" -c credential.helper= fetch --depth 1 origin "$UPSTREAM"
    [[ "$(git -C "$STAGE/repository" rev-parse FETCH_HEAD)" == "$UPSTREAM" ]] ||
        { echo "Хеш исходного Go-релея не совпал." >&2; exit 1; }
    git -C "$STAGE/repository" archive FETCH_HEAD | tar -xf - -C "$STAGE/source"
fi
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 60 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$PATCH_REF/wpo-relay-zero-profiles-patch.py" \
    -o "$STAGE/patch.py"
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$MANAGER_REF/install-panel.sh" \
    -o "$STAGE/install-panel.sh"
python3 "$STAGE/patch.py" "$STAGE/source"
bash -n "$STAGE/install-panel.sh"

echo "[2/5] Go-тесты: сайт без WEB Proxy и закрытый доступ к прокси-сессиям..."
(
    cd "$STAGE/source"
    # The upstream credential-permissions test deliberately writes a 0444
    # file to assert that group/other reads are rejected outside systemd's
    # credentials directory. Installer umask 077 silently turns 0444 into
    # 0400, invalidating that test and causing a false failure.
    # Relax umask ONLY for the isolated Go test/build subprocess, not for
    # files, credentials, backups or the live service.
    umask 022
    "$GO_BIN" test ./internal/config ./internal/server ./internal/session -count=1
    "$GO_BIN" build -trimpath -ldflags='-s -w' -o "$STAGE/tproxy-server.new" ./cmd/tproxy-server
)
[[ -s "$STAGE/tproxy-server.new" ]] || { echo "Сборка Go-релея не завершилась." >&2; exit 1; }

printf '%s\n' '{"profiles":[]}' > "$STAGE/zero-profiles.json"
chmod 0600 "$STAGE/zero-profiles.json"
"$STAGE/tproxy-server.new" -config "$CONFIG" -profiles-file "$STAGE/zero-profiles.json" -check
"$STAGE/tproxy-server.new" -config "$CONFIG" -profiles-file "$PROFILES" -check

echo "[3/5] Обновление логики без фиктивных протоколов..."
python3 - "$MANAGER" "$PANEL" "$STAGE/install-panel.sh" "$STAGE" <<'PY_PATCH'
import ast
from pathlib import Path
import re
import sys
manager_path,panel_path,reference_path,stage=map(Path,sys.argv[1:])
manager=manager_path.read_text(encoding="utf-8")
panel=panel_path.read_text(encoding="utf-8")
reference=reference_path.read_text(encoding="utf-8")
# The Bash installer embeds two Python programs under separate heredocs.
def embedded_python(text,opening):
    marker=opening+"\n"
    if text.count(marker)!=1:
        raise RuntimeError("Не найден исходник "+opening)
    pos=text.index(marker)+len(marker)
    end=text.find("\nPY\n",pos)
    if end<0: raise RuntimeError("Не найден конец Python кода")
    source=text[pos:end]+"\n"
    ast.parse(source)
    return source
manager_reference=embedded_python(reference, """cat > "$MANAGER" <<'PY'""")
panel_reference=embedded_python(reference, """cat > "$APP_FILE" <<'PY'""")

def func(text,name):
    tree=ast.parse(text)
    hits=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==name]
    if len(hits)!=1: raise RuntimeError("Не найдена единственная функция "+name)
    lines=text.splitlines(keepends=True)
    node=hits[0]
    start=sum(map(len,lines[:node.lineno-1]))
    end=sum(map(len,lines[:node.end_lineno]))
    return start,end,text[start:end]

def swap_function(dst,src,name,needle):
    start,end,old=func(dst,name)
    new=func(src,name)[2]
    if needle not in new: raise RuntimeError("Отсутствует новая функция "+name)
    return dst[:start]+new+dst[end:]

# Avoid replacing whole manager functions: their optional Nodes Lab
# extensions are not always marked. Change only the few relay lines.
def edit_function(text,name,transform):
    start,end,old=func(text,name)
    updated=transform(old)
    if updated==old and name=="sync_profiles" and 'wpo-site-always-on-v5' in old:
        raise RuntimeError("Не удалось удалить фиктивный профиль.")
    return text[:start]+updated+text[end:]

def site_only_sync(original):
    code=original
    marker='    # wpo-site-always-on-v5'
    dummy='keep.append({"name":"wpp-site-standby"'
    if dummy in code:
        start=code.find(marker)
        end=code.find('    tmp=PROFILES+".tmp"',start)
        if start<0 or end<0 or end-start>1100:
            raise RuntimeError("Неизвестная реализация фиктивного профиля.")
        code=code[:start]+'''    # WPO v6: profiles: [] is valid. No hidden WEB Proxy credentials.
'''+code[end:]
    if '    if keep:\n        c=run(' in code:
        begin=code.index('    if keep:\n        c=run(')
        end=code.find('    os.replace(tmp,PROFILES)',begin)
        if end<0 or end-begin>1000:
            raise RuntimeError("Неизвестный блок проверки профилей.")
        lines=code[begin:end].splitlines(keepends=True)
        dedented=''.join(line[4:] if line.startswith('    ') else line for line in lines[1:])
        code=code[:begin]+dedented+code[end:]
    if dummy in code:
        raise RuntimeError("В менеджере остался скрытый профиль.")
    if 'tproxy-server","-config"' not in code:
        raise RuntimeError("Не найдена проверка конфигурации релея.")
    return code

def site_only_economy(code):
    old='run("systemctl","disable","--now","tproxy-server.service",check=False)'
    new='run("systemctl","enable","--now","tproxy-server.service",check=True)'
    if old in code:
        return code.replace(old,new,1)
    if new in code:
        return code
    raise RuntimeError("Неизвестная настройка экономии MTProxy.")

manager=edit_function(manager,"sync_profiles",site_only_sync)
manager=edit_function(manager,"set_mtproxy_economy",site_only_economy)
panel=swap_function(panel,panel_reference,"restart_public_site","wpo-zero-profiles-v6")

# Only adjust the obsolete relay shutdown block inside apply(), preserving
# Node Lab and every other manager function.
old_start='            if web_changed and not os.path.exists(MTPROXY_ECONOMY):'
new_start='            if web_changed:'
if old_start in manager:
    i=manager.index(old_start)
    j=manager.find('\n    except Exception:',i)
    if j<0 or j-i>1800 or 'disable","--now","tproxy-server.service' not in manager[i:j]:
        raise RuntimeError("Неизвестный блок отключения веб-сайта в apply()")
    replacement='''            if web_changed:
                # A zero-profile relay still serves the public website.
                run("systemctl","enable","tproxy-server.service",check=True)
                run("systemctl","restart","tproxy-server.service",check=True)'''
    manager=manager[:i]+replacement+manager[j:]
elif (
    new_start not in func(manager,"apply")[2]
    or 'run("systemctl","disable","--now","tproxy-server.service",check=True)' in func(manager,"apply")[2]
):
    raise RuntimeError("Неизвестная версия менеджера WEB Proxy; отмена.")

# Preserve all existing Node Lab markers.
for previous,updated,name in (
    (manager_path.read_text(encoding="utf-8"),manager,"manager"),
    (panel_path.read_text(encoding="utf-8"),panel,"panel")
):
    markers=set(re.findall(r'wpo-node-[^\n]+',previous))
    if not markers.issubset(set(re.findall(r'wpo-node-[^\n]+',updated))):
        raise RuntimeError("Исправление затрагивает Nodes Lab ("+name+"); отмена.")
    compile(updated,name,"exec")

(stage/"manager.py").write_text(manager,encoding="utf-8")
(stage/"panel.py").write_text(panel,encoding="utf-8")
print("✓ WEB Proxy можно удалить полностью; сайт теперь независим.")
PY_PATCH
python3 -m py_compile "$STAGE/manager.py" "$STAGE/panel.py"

echo "[4/5] Атомарная замена релея и включение публичного сайта..."
TOUCHED=1
install -o root -g root -m 0755 "$STAGE/tproxy-server.new" "$RELAY_BIN.wpo-v6-new"
mv -f -- "$RELAY_BIN.wpo-v6-new" "$RELAY_BIN"
install -o root -g root -m 0755 "$STAGE/manager.py" "$MANAGER.wpo-v6-new"
mv -f -- "$MANAGER.wpo-v6-new" "$MANAGER"
install -o root -g root -m 0644 "$STAGE/panel.py" "$PANEL.wpo-v6-new"
mv -f -- "$PANEL.wpo-v6-new" "$PANEL"

# Remove only an exact former WPO standby profile, if one exists. All real
# clients/profiles are preserved. Empty is now a first-class supported state.
python3 - "$PROFILES" <<'PY_CLEAN'
import json,os,sys,tempfile
from pathlib import Path
path=Path(sys.argv[1])
data=json.loads(path.read_text(encoding="utf-8"))
profiles=data.get("profiles")
if not isinstance(profiles,list):
    raise RuntimeError("Неправильный формат profiles.json")
kept=[entry for entry in profiles if not (isinstance(entry,dict) and entry.get("name")=="wpp-site-standby")]
if len(kept)!=len(profiles):
    data["profiles"]=kept
    st=path.stat()
    fd,tmp=tempfile.mkstemp(prefix=".wpo-profiles-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(data,out,ensure_ascii=True,indent=2)
            out.write("\n");out.flush();os.fsync(out.fileno())
        os.chown(tmp,st.st_uid,st.st_gid)
        os.chmod(tmp,st.st_mode & 0o777)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
print("✓ Реальных WEB Proxy профилей:",len(kept),"; фиктивных профилей нет.")
PY_CLEAN
"$RELAY_BIN" -config "$CONFIG" -profiles-file "$PROFILES" -check >/dev/null

install -d -m 0755 "$(dirname "$OVERRIDE")"
cat > "$OVERRIDE" <<'UNIT'
[Unit]
Wants=
Wants=network-online.target
UNIT
chmod 0644 "$OVERRIDE"
systemctl daemon-reload
systemctl reset-failed "$RELAY" >/dev/null 2>&1 || true
systemctl enable "$RELAY" >/dev/null
systemctl restart "$RELAY"

echo "[5/5] Проверка работающего сайта и панели..."
READY=0
for attempt in $(seq 1 20); do
    if curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 2 \
       'http://127.0.0.1:8081/healthz' 2>/dev/null | grep -Fxq ok; then
        READY=1;break
    fi
    sleep 0.4
done
if (( ! READY )); then
    echo "Сервер не прошёл healthcheck после сборки." >&2
    exit 1
fi
DOMAIN="$(python3 - "$CONFIG" <<'PY_DOMAIN'
import json,sys
print(json.load(open(sys.argv[1],encoding="utf-8"))["public_hostname"])
PY_DOMAIN
)"
curl -4fsS --noproxy '*' --connect-timeout 2 --max-time 6 \
    -H "Host: $DOMAIN" 'http://127.0.0.1:8080/?wpo-site-v6=1' \
    -o "$STAGE/published.html"
python3 - "$STAGE/published.html" /srv/tproxy-site/index.html <<'PY_SITE'
from pathlib import Path
import hashlib,sys
actual=Path(sys.argv[1]).read_bytes()
saved=Path(sys.argv[2]).read_bytes()
if not actual or hashlib.sha256(actual).digest()!=hashlib.sha256(saved).digest():
    raise SystemExit("Релей отвечает не тем HTML, который сохранён на диске.")
print("✓ Публичный сайт действительно загружен в память сервера.")
PY_SITE
systemctl restart "$PANEL_SERVICE"
systemctl is-active --quiet "$PANEL_SERVICE"
echo
echo "============================================================="
echo "  WEB PANEL ONLINE — ПУБЛИЧНЫЙ САЙТ РАБОТАЕТ БЕЗ WEB PROXY"
echo "============================================================="
echo "  Домен: https://$DOMAIN/"
echo "  WEB Proxy: необязателен, фиктивных профилей нет."
echo "  Ноды, клиенты и остальные протоколы сохранены."
echo "  Теперь нажмите «Применить» у нужного шаблона."
echo "  Резервная копия: $BACKUP"
