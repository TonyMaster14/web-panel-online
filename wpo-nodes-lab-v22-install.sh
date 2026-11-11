#!/usr/bin/env bash
# Nodes Lab v22: horizontal continuous node list and correctly sized install card.
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите на основном VPS с WPO от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Отсутствует $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба WPO не найдена.'; exit 1; }
grep -Fq '/* wpo-node-heading-v21 */' "$UI" || { echo 'Сначала нужен Nodes Lab v21.'; exit 1; }

if grep -Fq '/* wpo-node-pending-row-v22 */' "$UI"; then
  echo 'Nodes Lab v22 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v22-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys
p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,what):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{what}: найдено {count} совпадений, ожидалось одно; исходник не изменён.')
    src=src.replace(old,new,1)

# Install card uses the SAME three visual rows as an ordinary node.
# The long live progress text moves out of the header to the compact lower row.
old_head=(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span>'
    '<div class="wpo-node-label"><h3>Установка</h3>'
    '<small data-node-progress="{esc(uid)}" title="{esc(detail)}">{esc(detail)}</small></div>'
    '<div class="wpo-node-head-tools">{status(uid,state)}'
    '<div class="wpo-node-actions">{delete}</div></div></div>'
)
new_head=(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span>'
    '<div class="wpo-node-label"><h3>Установка</h3></div>{status(uid,state)}</div>'
)
once(old_head,new_head,'Заголовок ожидающей ноды')

globe_svg=(
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9"/>'
    '<path d="M3 12h18M12 3c2.8 2.4 4 5.4 4 9s-1.2 6.6-4 9'
    'M12 3c-2.8 2.4-4 5.4-4 9s1.2 6.6 4 9"/>'
    '</svg>'
)
old_body=(
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">{icon("link")}'
    '<span data-node-domain="{esc(uid)}">{esc(domain or "Домен определяется")}</span>'
    '</div></div>'
)
new_body=(
    '<div class="wpo-node-card-body"><div class="wpo-node-domain">'
    '<span class="wpo-domain-mark">'+globe_svg+'</span>'
    '<span data-node-domain="{esc(uid)}">{esc(domain or "Домен определяется")}</span></div>'
    '<div class="wpo-node-meta-row">'
    '<p class="wpo-node-template wpo-node-install-detail" data-node-progress="{esc(uid)}"'
    ' title="{esc(detail)}">{esc(detail)}</p>'
    '<div class="wpo-node-actions">{delete}</div></div></div>'
)
once(old_body,new_body,'Домен и нижняя полоса ожидающей ноды')

css=r"""
/* wpo-node-pending-row-v22 */
/* Nodes always fill the first available slot from left to right. */
.wpo-nodes-page .wpo-node-grid{
    display:grid;
    grid-template-columns:repeat(5,minmax(0,1fr));
    gap:9px;
    grid-auto-flow:row;
    align-items:stretch;
    justify-content:stretch;
    min-width:0;
}
@media(max-width:850px){
    .wpo-nodes-page .wpo-node-grid{
        grid-template-columns:repeat(3,minmax(0,1fr));
    }
}
@media(max-width:700px){
    .wpo-nodes-page .wpo-node-grid{
        grid-template-columns:minmax(0,1fr);
    }
}
/* Match installed-node card dimensions and keep everything inside the card. */
.wpo-nodes-page .wpo-pending-node{
    display:grid;
    grid-template-rows:40px minmax(0,1fr);
    row-gap:5px;
    min-height:140px;
    padding:10px 12px;
    min-width:0;
    overflow:hidden;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head{
    display:flex;
    align-items:center;
    min-height:40px;
    min-width:0;
    gap:7px;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-label{
    display:flex;
    min-width:0;
    flex:1 1 auto;
    overflow:hidden;
    white-space:nowrap;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-label h3{
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
    max-width:100%;
    font-size:12px;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-head>.wpo-node-status{
    margin-left:auto;
    flex:0 0 auto;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-card-body{
    display:grid;
    grid-template-rows:21px minmax(0,1fr);
    gap:7px;
    align-content:stretch;
    align-self:stretch;
    padding:11px 0 0;
    min-width:0;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-domain{
    display:grid;
    grid-template-columns:14px minmax(0,1fr);
    align-items:center;
    column-gap:7px;
    min-width:0;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-domain .wpo-domain-mark{
    color:#38bdf8;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    line-height:1;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-meta-row{
    min-width:0;
    overflow:hidden;
}
.wpo-nodes-page .wpo-pending-node .wpo-node-install-detail{
    margin:0;
    display:block;
    flex:1 1 0;
    min-width:0;
    max-width:calc(100% - 36px);
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
    text-align:left;
    font-size:10.5px;
    color:var(--muted);
}
.wpo-nodes-page .wpo-pending-node .wpo-node-actions{
    flex:0 0 auto;
    margin-left:auto;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Сетка и компактный дизайн временной ноды')
compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes22tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Ноды идут слева направо; третья карточка в первом ряду, установка без вылезающего текста.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'v22 не применился; восстановлен исходный интерфейс.'
  exit 1
fi

if ! python3 -m py_compile "$UI" ||
   ! systemctl restart "$SERVICE" ||
   ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или перезапуска; выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v22 готов: слева направо, одинаковые карточки, компактная установка.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main, Node Agent и работа протоколов не изменены.'
