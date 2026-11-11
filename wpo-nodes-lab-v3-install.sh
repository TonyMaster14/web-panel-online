#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo "Запустите скрипт от root."; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI."; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-card-body' "$UI" || { echo "Nodes Lab v2 не обнаружен. Обновление не применено."; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v3-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY'
from pathlib import Path
import sys

p=Path(sys.argv[1])
source=p.read_text(encoding='utf-8')
if "wpo-node-compact-v3" in source:
    print("Компактный дизайн уже установлен.")
    raise SystemExit(0)

def one(old, new, label):
    global source
    count=source.count(old)
    if count!=1:
        raise RuntimeError(f"{label}: ожидалось 1 совпадение, найдено {count}. Ничего не записано.")
    source=source.replace(old,new,1)

one(
    'grid-template-columns:repeat(2,minmax(0,320px));gap:14px;align-items:start;justify-content:start',
    'grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start',
    'Две колонки')
one(
    'aspect-ratio:1/1;min-width:0;min-height:298px;margin:0;padding:18px;',
    'aspect-ratio:auto;min-width:0;min-height:172px;margin:0;padding:14px;',
    'Прямоугольные карточки')
one(
    'flex:0 0 48px;width:48px;height:48px;',
    'flex:0 0 40px;width:40px;height:40px;',
    'Компактный флаг')
one(
    'border-radius:12px;background:var(--input);font-size:25px}',
    'border-radius:10px;background:var(--input);font-size:22px}',
    'Размер флага')
one(
    '.wpo-node-card-body{display:grid;gap:9px;min-width:0;align-content:center;flex:1;padding:12px 0}',
    '.wpo-node-card-body{display:grid;gap:7px;min-width:0;align-content:center;flex:1;padding:9px 0}',
    'Высота содержимого')
one(
    '.wpo-node-card-body h3{font-size:18px;',
    '.wpo-node-card-body h3{font-size:16px;',
    'Размер заголовка')
one(
    '<a class="wpo-node-domain" href="https://{esc(connection_token)}" target="_blank" rel="noopener noreferrer">{icon("link")}<span>{esc(connection_token)}</span></a>',
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(connection_token)}</span></div>',
    'Домен основной ноды')
one(
    '<a class="wpo-node-domain" href="{esc(url)}" target="_blank" rel="noopener noreferrer" title="Открыть сайт ноды">{icon(\'link\')}<span>{esc(hostname)}</span></a>',
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(hostname)}</span></div>',
    'Домен дополнительной ноды')
one(
    '.wpo-node-domain{display:flex;align-items:center;gap:8px;min-width:0;padding:10px 11px;background:var(--input);border:1px solid var(--line);border-radius:9px;text-decoration:none;color:var(--accent);font:500 12px ui-monospace,monospace}',
    '.wpo-node-domain{display:flex;align-items:center;gap:8px;min-width:0;padding:8px 10px;background:var(--input);border:1px solid var(--line);border-radius:8px;color:var(--text);font:500 12px ui-monospace,monospace;cursor:default}',
    'Оформление домена')
one(
    '.wpo-node-domain:hover{border-color:var(--accent)}',
    '.wpo-domain-mark{font:14px system-ui,sans-serif;flex:0 0 auto}',
    'Неактивный домен')
one(
    '@media(max-width:700px){.wpo-nodes-toolbar{align-items:stretch;flex-direction:column}.wpo-add-node{width:100%;justify-content:center}.wpo-node-stats{grid-template-columns:repeat(2,1fr)}.wpo-node-grid{grid-template-columns:minmax(0,340px)}.wpo-nodes-page .wpo-node-card{min-height:298px}.wpo-node-legend{gap:9px}}',
    '@media(max-width:700px){.wpo-nodes-toolbar{align-items:stretch;flex-direction:column}.wpo-add-node{width:100%;justify-content:center}.wpo-node-stats{grid-template-columns:repeat(2,1fr)}.wpo-node-grid{grid-template-columns:minmax(0,410px)}.wpo-nodes-page .wpo-node-card{min-height:172px}.wpo-node-legend{gap:9px}}',
    'Мобильная разметка')
one(
    '    css=\'\'\'\n.wpo-nodes-page',
    '    # wpo-node-compact-v3\n    css=\'\'\'\n.wpo-nodes-page',
    'Маркер обновления')

compile(source,str(p),'exec')
tmp=p.with_suffix('.py.nodes3tmp')
tmp.write_text(source,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print("Карточки стали прямоугольными, домены больше не являются ссылками.")
PY
then
    echo "Обновление не удалось, возвращаю резервную копию."
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo "Ошибка проверки или перезапуска. Возвращаю прежнюю версию."
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Дизайн нод обновлён. Резервная копия: $BACKUP"
echo "Главная ветка main не затронута."
