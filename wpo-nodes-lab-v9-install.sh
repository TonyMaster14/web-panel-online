#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-spinner-v8' "$UI" || { echo 'Требуется установленный Nodes Lab v8. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v9-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-aligned-v9' in src:
    print('Выравнивание v9 уже установлено.')
    raise SystemExit(0)

def once(old, new, name):
    global src
    count=src.count(old)
    if count != 1:
        raise RuntimeError(f'{name}: ожидается одно совпадение, найдено {count}. Ничего не изменено.')
    src=src.replace(old,new,1)

# Progress is shown under "Установка", where normal nodes show the country.
# Domain remains on the second line; no additional third line extends the card.
once(
    '<div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div>',
    '<div class="wpo-node-label"><h3>Установка</h3><small data-node-progress="{esc(uid)}" title="{esc(detail)}">{esc(detail)}</small></div>',
    'Прогресс в заголовке')
once(
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">{icon("link")}<span>{esc(domain or "Домен определяется")}</span></div><p class="wpo-node-template">{esc(detail)}</p></div>',
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">{icon("link")}<span data-node-domain="{esc(uid)}">{esc(domain or "Домен определяется")}</span></div></div>',
    'Убрать лишнюю строку установки')
# Keep progress and domain updated every second without reloading the page.
once(
    'for(const n of [...(d.nodes||[]),...(d.pending||[])]){const el=document.querySelector(',
    'for(const n of [...(d.nodes||[]),...(d.pending||[])]){if(n.id&&n.id.startsWith("p-")){const progress=document.querySelector("[data-node-progress="+CSS.escape(n.id)+"]");if(progress&&typeof n.detail==="string"){progress.textContent=n.detail;progress.title=n.detail}const domain=document.querySelector("[data-node-domain="+CSS.escape(n.id)+"]");if(domain&&n.domain)domain.textContent=n.domain}const el=document.querySelector(',
    'Живое обновление прогресса и домена')
once(
    '    # wpo-node-title-v5\n    # wpo-node-compact-v6',
    '    # wpo-node-title-v5\n    # wpo-node-aligned-v9\n    # wpo-node-compact-v6',
    'Маркер v9')
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes9tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Временная карточка выровнена с основной; анимация и статус сохранены.')
PY_PATCH
then
    echo 'Ошибка изменения. Возвращаю исходный файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Ошибка проверки или перезапуска. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v9 готов. Резервная копия: $BACKUP"
echo 'Основная ветка main не затронута.'
