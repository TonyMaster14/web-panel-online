#!/usr/bin/env bash
# WPO UI-only: REALITY first; routing green dots reflect saved active rules, not selected tab.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Запустите через sudo на основной панели WPO.' >&2; exit 2; }
APP=/opt/tproxy-panel
TARGET="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
[[ -s "$TARGET" && ! -L "$TARGET" && -s "$APP/panel.py" ]] || {
  echo 'Файлы основной панели WPO не найдены. Ничего не изменено.' >&2; exit 2;
}
systemctl is-active --quiet "$SERVICE" || {
  echo 'Служба WPO не запущена. Изменения не выполнены.' >&2; exit 2;
}
TMP="$(mktemp -d /tmp/wpo-routing-tabs.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup(){
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -n "$BACKUP" && -s "$BACKUP/wpp_ui.py" ]]; then
    cp -a "$BACKUP/wpp_ui.py" "$TARGET" || true
    systemctl restart "$SERVICE" || true
    echo "Обновление не прошло проверку. UI восстановлен: $BACKUP" >&2
  fi
  rm -rf -- "$TMP"
  exit "$rc"
}
trap cleanup EXIT
python3 - "$TARGET" "$TMP/patched.py" <<'PY'
from pathlib import Path
import sys
src = Path(sys.argv[1]).read_text(encoding="utf-8")

def update(before, after, name):
    global src
    a, b = src.count(before), src.count(after)
    if (a, b) == (1, 0):
        src = src.replace(before, after, 1)
    elif (a, b) != (0, 1):
        raise RuntimeError(f"Несовместимый код WPO ({name}): найдено исходных={a}, новых={b}; файлы не изменены.")

update(
    "key=lambda item: {'vless':0,'reality':1,'hysteria':2,'awg20':3,'awg31':4}.get(item.get('protocol'),4))",
    "key=lambda item: {'reality':0,'vless':1,'hysteria':2,'awg20':3,'awg31':4}.get(item.get('protocol'),4))",
    "сортировка подключений")
update(
    "        return bool(saved.get('enabled'))\n    routing_tabs=[]",
    "        return bool(saved.get('enabled', True) and (\n"
    "            any(saved.get(key) for key in routing_store.ROUTING_FLAGS)\n"
    "            or saved.get('direct_domains') or saved.get('proxy_domains')))\n"
    "    routing_tabs=[]",
    "проверка реально включённых правил")
update(
    "for protocol,title in (('vless','VLESS XHTTP'),('reality','VLESS TCP REALITY Vision'),('hysteria','Hysteria2'),",
    "for protocol,title in (('reality','VLESS TCP REALITY Vision'),('vless','VLESS XHTTP'),('hysteria','Hysteria2'),",
    "порядок карточек")
update(
    "protocol_title='Hysteria2' if item.get('protocol')=='hysteria' else 'VLESS XHTTP'",
    "protocol_title=('Hysteria2' if item.get('protocol')=='hysteria' else\n"
    "                         'VLESS TCP REALITY Vision' if item.get('protocol')=='reality' else 'VLESS XHTTP')",
    "заголовок REALITY")
update(
    'data-routing-stored="{"1" if has_profile and profile.get(\'enabled\') else "0"}"',
    'data-routing-stored="{"1" if routing_enabled(item) else "0"}"',
    "согласованность сохранённого статуса")
update(
    '.routing-protocol-card.is-selected .routing-tab-dot{{border-color:#22c55e;background:color-mix(in srgb,#22c55e 12%,transparent)}}',
    '.routing-protocol-card[data-routing-enabled="1"] .routing-tab-dot{{border-color:#22c55e;background:color-mix(in srgb,#22c55e 12%,transparent)}}',
    "зелёная рамка точки")
update(
    '.routing-protocol-card.is-selected .routing-tab-dot i{{background:#22c55e}}',
    '.routing-protocol-card[data-routing-enabled="1"] .routing-tab-dot i{{background:#22c55e}}',
    "зелёная середина точки")
if 'def routing_ui(' not in src or 'routing_store.ROUTING_FLAGS' not in src:
    raise RuntimeError("Маршрутизация WPO не распознана; изменения не выполнены.")
compile(src, sys.argv[2], "exec")
Path(sys.argv[2]).write_text(src, encoding="utf-8")
PY
python3 -m py_compile "$TMP/patched.py"
if cmp -s "$TMP/patched.py" "$TARGET"; then
  echo '✓ Маршрутизация WPO уже в нужном порядке; точки соответствуют сохранённым правилам.'
  exit 0
fi
BACKUP="/var/backups/web-panel-online/routing-dots-order-$(date -u +%Y%m%dT%H%M%SZ)-$$"
install -d -m 0700 "$BACKUP"
cp -a "$TARGET" "$BACKUP/wpp_ui.py"
STAGE="$(mktemp "$APP/.wpp-routing-dots.XXXXXXXX.py")"
cp "$TMP/patched.py" "$STAGE"
chown --reference="$TARGET" "$STAGE"
chmod --reference="$TARGET" "$STAGE"
CHANGED=1
mv -f "$STAGE" "$TARGET"
python3 -m py_compile "$TARGET"
systemctl restart "$SERVICE"
READY=0
for i in $(seq 1 15); do
  if systemctl is-active --quiet "$SERVICE"; then
    CODE="$(curl -4sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ 2>/dev/null || true)"
    if [[ "$CODE" =~ ^[234][0-9][0-9]$ ]]; then READY=1; break; fi
  fi
  sleep 1
done
(( READY )) || { echo 'Панель не ответила после перезапуска; выполняется откат.' >&2; exit 4; }
CHANGED=0
echo '✓ REALITY теперь первая карточка, XHTTP — вторая.'
echo '✓ Зелёные точки отображаются только у подключений с активными сохранёнными правилами.'
echo '✓ Синяя рамка показывает выбранное подключение независимо от маршрутизации.'
echo '✓ Изменён только UI-модуль. Правила, подписки и VPN-конфигурации не изменялись.'
echo "✓ Резервная копия: $BACKUP"
