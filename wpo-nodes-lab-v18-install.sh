#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-globe-v17' "$UI" || { echo 'Требуется установленный Nodes Lab v17. Ничего не изменено.'; exit 1; }
if grep -Fq '# wpo-node-divider-v18' "$UI"; then
  echo 'Nodes Lab v18 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v18-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    matches=src.count(old)
    if matches!=1:
        raise RuntimeError(f'{label}: найдено {matches} совпадений вместо одного. Файл не изменён.')
    src=src.replace(old,new,1)

# Primary node: preserve the complete flag/title/status/domain, add matching
# metadata under its domain. Restrict replacement to the local card only.
start=src.index('    cards.append(f\'\'\'<article class="card wpo-node-card">')
end=src.index('    for n in nodes:',start)
main=src[start:end]
if main.count('</a></div>')!=1 or 'href="https://{esc(connection_token)}"' not in main:
    raise RuntimeError('Не найдена ожидаемая основная карточка; ничего не изменено.')
main=main.replace('</a></div>',
    '</a><div class="wpo-node-meta-row"><p class="wpo-node-template wpo-main-node-label">Основная нода</p></div></div>',1)
src=src[:start]+main+src[end:]

# Additional nodes: template and action buttons share the same separated row.
# Template name remains dynamic ("Технические работы", "Открытие кофейни"...).
once(
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p></div><div class="wpo-node-card-bottom"><div class="wpo-node-actions">{edit}{delete}</div></div>',
    '<div class="wpo-node-meta-row"><p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p><div class="wpo-node-actions">{edit}{delete}</div></div></div>',
    'Строка шаблона и кнопок')

# Exactly the same layout for local/remote nodes. Installation cards are
# excluded, so their spinner and progress presentation stay unchanged.
css=r"""
/* wpo-node-divider-v18: matched meta rows with subtle separators */
.wpo-nodes-page .wpo-node-card:not(.wpo-pending-node){
    display:grid;
    grid-template-rows:40px minmax(0,1fr);
    row-gap:5px;
    min-height:140px;
    padding:10px 12px;
}
.wpo-nodes-page .wpo-node-card:not(.wpo-pending-node) .wpo-node-card-body{
    display:grid;
    grid-template-rows:21px minmax(0,1fr);
    row-gap:7px;
    align-content:stretch;
    align-self:stretch;
    padding:11px 0 0;
    min-width:0;
}
.wpo-nodes-page .wpo-node-meta-row{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:5px;
    align-self:end;
    min-height:35px;
    min-width:0;
    position:relative;
    padding:6px 0 0;
    border-top:1px solid var(--line);
}
.wpo-nodes-page .wpo-node-meta-row::before{
    content:"";
    position:absolute;
    top:-1px;left:0;
    height:1px;width:55%;
    background:linear-gradient(90deg,color-mix(in srgb,var(--accent) 44%,var(--line)),transparent);
    pointer-events:none;
}
.wpo-nodes-page .wpo-node-meta-row .wpo-node-template{
    margin:0;
    padding:0;
    display:flex;
    justify-content:flex-start;
    align-items:center;
    gap:6px;
    text-align:left;
    transform:none;
    min-width:0;
    line-height:1.35;
    font-size:10.5px;
    overflow:hidden;
    white-space:nowrap;
    text-overflow:ellipsis;
}
.wpo-nodes-page .wpo-node-meta-row:has(.wpo-node-actions) .wpo-node-template{
    max-width:calc(100% - 61px);
}
.wpo-nodes-page .wpo-node-meta-row .wpo-node-actions{
    margin-left:auto;
    display:flex;
    flex:0 0 auto;
    align-items:center;
    justify-content:flex-end;
    gap:3px;
}
.wpo-nodes-page .wpo-node-meta-row .wpo-main-node-label{
    font-size:12px;
    line-height:1.35;
    font-weight:650;
    color:var(--text);
    letter-spacing:.01em;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Стили разделителя и общей сетки')

once(
    '    # wpo-node-globe-v17\n    # wpo-node-compact-v6',
    '    # wpo-node-globe-v17\n    # wpo-node-divider-v18\n    # wpo-node-compact-v6',
    'Маркер v18')

compile(src,str(p),'exec')
temp=p.with_suffix('.py.nodes18tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(p.stat().st_mode & 0o777)
temp.replace(p)
print('Добавлены одинаковые разделители; "Основная нода" и шаблон сайта стоят на одной линии.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Правка не применена, интерфейс восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Проверка или запуск панели не удались. Выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v18: обе карточки с разделителем, подписи на одном уровне, немного компактнее.'
echo "Резервная копия: $BACKUP"
echo 'Сервисы нод, шаблоны, статусы и GitHub main не затронуты.'
