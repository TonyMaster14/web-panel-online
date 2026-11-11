#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo "Запустите от root."; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба $SERVICE"; exit 1; }
grep -q 'wpo-node-compact-v3' "$UI" || { echo 'Нужен установленный Nodes Lab v3. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v4-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-title-v4' in src:
    print('Оформление v4 уже установлено.')
    raise SystemExit(0)

def one(old, new, label):
    global src
    count=src.count(old)
    if count != 1: raise RuntimeError(f'{label}: найдено {count} совпадений, требуется одно.')
    src=src.replace(old,new,1)

# Title and country/location return to the flag row; status stays aligned on the right.
one(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span>{status("local","online")}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span><div class="wpo-node-label"><h3>{esc(lname)}</h3><small>Основная нода</small></div>{status("local","online")}</div>',
    'Название основной ноды')
one(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    'Название удалённой ноды')
one(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div>{status(uid,state)}</div>',
    'Название установки')

# Remove former large centered names to avoid duplication.
one(
    '<div class="wpo-node-card-body"><small class="wpo-node-eyebrow">ОСНОВНАЯ НОДА</small><h3>{esc(lname)}</h3>',
    '<div class="wpo-node-card-body">',
    'Заголовок основной карточки')
one(
    '<div class="wpo-node-card-body"><small class="wpo-node-eyebrow">{esc(country)}</small><h3 title="{esc(name)}">{esc(name)}</h3>',
    '<div class="wpo-node-card-body">',
    'Заголовок удалённой карточки')
one(
    '<div class="wpo-node-card-body"><small class="wpo-node-eyebrow">ПОДКЛЮЧЕНИЕ НОДЫ</small><h3>Установка</h3>',
    '<div class="wpo-node-card-body">',
    'Заголовок установки')

# Domain becomes quiet secondary metadata, not an action or a prominent tile.
one(
    '.wpo-node-domain{display:flex;align-items:center;gap:8px;min-width:0;padding:8px 10px;background:var(--input);border:1px solid var(--line);border-radius:8px;color:var(--text);font:500 12px ui-monospace,monospace;cursor:default}',
    '.wpo-node-domain{display:flex;align-items:center;gap:6px;min-width:0;padding:2px 0;background:transparent;border:0;border-radius:0;color:var(--muted);font:400 11px ui-monospace,monospace;cursor:default}',
    'Спокойная подпись домена')
one(
    '.wpo-domain-mark{font:14px system-ui,sans-serif;flex:0 0 auto}',
    '.wpo-domain-mark{font:11px system-ui,sans-serif;filter:grayscale(1);opacity:.65;flex:0 0 auto}',
    'Иконка домена')
one(
    '.wpo-node-card-head,.wpo-node-card-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}',
    '.wpo-node-card-head,.wpo-node-card-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}.wpo-node-label{display:grid;min-width:0;flex:1;gap:3px}.wpo-node-label h3{margin:0;font-size:15px;font-weight:650;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.wpo-node-label small{font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    'Название возле флага')
one(
    '    # wpo-node-compact-v3\n    css=',
    '    # wpo-node-compact-v3\n    # wpo-node-title-v4\n    css=',
    'Маркер обновления')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes4tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Название перенесено к флагу, домен стал компактной подписью.')
PY_PATCH
then
    echo 'Патч не применён. Возвращаю резервную копию.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Проверка или перезапуск не удались. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Обновление Nodes Lab v4 установлено. Резервная копия: $BACKUP"
echo 'Основная ветка main не изменена.'
