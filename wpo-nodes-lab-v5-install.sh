#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-title-v4' "$UI" || { echo 'Требуется установленный Nodes Lab v4. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v5-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-title-v5' in src:
    print('Nodes Lab v5 уже установлен.')
    raise SystemExit(0)

def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1: raise RuntimeError(f'{label}: ожидалось 1 совпадение, найдено {count}.')
    src=src.replace(old,new,1)

once(
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(connection_token)}</span></div>',
    '<a class="wpo-node-domain" href="https://{esc(connection_token)}" target="_blank" rel="noopener noreferrer" title="Открыть домен основной ноды"><span class="wpo-domain-mark">🌐</span><span>{esc(connection_token)}</span></a>',
    'Домен основной ноды')
once(
    '<div class="wpo-node-domain"><span class="wpo-domain-mark">🌐</span><span>{esc(hostname)}</span></div>',
    '<a class="wpo-node-domain" href="{esc(url)}" target="_blank" rel="noopener noreferrer" title="Открыть домен ноды"><span class="wpo-domain-mark">🌐</span><span>{esc(hostname)}</span></a>',
    'Домен удалённой ноды')
once(
    '.wpo-node-domain{display:flex;align-items:center;gap:6px;min-width:0;padding:2px 0;background:transparent;border:0;border-radius:0;color:var(--muted);font:400 11px ui-monospace,monospace;cursor:default}',
    '.wpo-node-domain{display:flex;align-items:center;gap:6px;min-width:0;padding:2px 0;background:transparent;border:0;border-radius:0;color:var(--muted);text-decoration:none;font:400 11px ui-monospace,monospace;cursor:pointer}',
    'Стиль домена')
once(
    '.wpo-domain-mark{font:11px system-ui,sans-serif;filter:grayscale(1);opacity:.65;flex:0 0 auto}',
    '.wpo-domain-mark{font:11px system-ui,sans-serif;filter:grayscale(1);opacity:.65;flex:0 0 auto}.wpo-node-domain[href]:hover span:last-child{text-decoration:underline;text-underline-offset:2px}.wpo-node-domain[href]:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:3px}',
    'Наведение на домен')
once(
    '<div class="wpo-node-card-bottom"><span>Локальный сервер</span><span class="muted">Основная</span></div>',
    '<div class="wpo-node-card-bottom"><span class="muted">Основная</span></div>',
    'Убрать Локальный сервер')
once(
    '<h2>Серверная сеть</h2>',
    '<h2>⚙️ Управление нодами</h2>',
    'Заголовок раздела')
once(
    '    # wpo-node-title-v4\n    css=',
    '    # wpo-node-title-v4\n    # wpo-node-title-v5\n    css=',
    'Маркер версии')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes5tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Готово: кликабельные домены, без подписи «Локальный сервер», новый заголовок.')
PY_PATCH
then
    echo 'Ошибка изменения. Возвращаю исходную версию.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Не прошла проверка или перезапуск. Возвращаю исходную версию.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v5 готов. Резервная копия: $BACKUP"
echo 'Основная ветка GitHub main не затронута.'
