#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите на основном VPS от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл панели не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-visual-v14' "$UI" || { echo 'Сначала требуется Nodes Lab v14. Изменения не применены.'; exit 1; }

if grep -Fq '# wpo-node-polish-v15' "$UI"; then
  echo 'Nodes Lab v15 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v15-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: найдено {n} совпадений вместо 1. Ничего не изменено.')
    src=src.replace(old,new,1)

# Main node: one centered country name and a discreet starred flag. Status unchanged.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(lc))}</span><div class="wpo-node-label"><h3>{esc(lname)}</h3><small>Основная нода</small></div>{status("local","online")}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag wpo-node-main-flag">{esc(node_flag(lc))}<span class="wpo-node-main-mark" title="Основная нода" aria-label="Основная нода">★</span></span><div class="wpo-node-label"><h3>{esc(lname)}</h3></div>{status("local","online")}</div>',
    'Основная нода без подписи и со звёздочкой')

# Additional nodes: no duplicated country subtitle. Keep status at the right.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3></div>{status(uid,state)}</div>',
    'Убрать повтор названия страны у дополнительных нод')

css=r"""
/* wpo-node-polish-v15 — clean grid, equal domain baselines, blue globe */
.wpo-nodes-page .wpo-node-card{
    display:grid;
    grid-template-rows:40px minmax(0,1fr) 27px;
    row-gap:7px;
    min-height:157px;
    align-content:stretch;
    justify-content:stretch;
}
.wpo-nodes-page .wpo-node-card-head{min-height:40px;align-items:center;gap:7px}
.wpo-nodes-page .wpo-node-label{
    display:flex;align-items:center;min-width:0;flex:1;min-height:40px;gap:0
}
.wpo-nodes-page .wpo-node-label h3{
    margin:0;font-size:14px;line-height:1.2;font-weight:650;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis
}
.wpo-nodes-page .wpo-node-card-head>.wpo-node-status{margin-left:auto;flex-shrink:0}
.wpo-nodes-page .wpo-node-card-body{
    grid-row:2;display:grid;align-content:start;align-self:start;
    gap:6px;min-width:0;padding:0;flex:none;
}
.wpo-nodes-page .wpo-node-domain{
    display:flex;align-items:center;gap:7px;min-width:0;
    margin:0;padding:3px 0;background:transparent;border:0;
    color:var(--muted);text-decoration:none;cursor:pointer;
    font:500 10.5px/1.3 ui-monospace,monospace;letter-spacing:-.16px
}
.wpo-nodes-page .wpo-node-domain .wpo-domain-mark{
    filter:none;opacity:1;color:#38bdf8;
    font:13px/1 system-ui,sans-serif;flex:0 0 13px
}
.wpo-nodes-page .wpo-node-domain span:last-child{
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0
}
.wpo-nodes-page .wpo-node-domain:hover{color:var(--accent)}
.wpo-nodes-page .wpo-node-template{
    display:flex;align-items:center;justify-content:center;gap:4px;
    min-width:0;margin:3px 0 0;line-height:1.35;
    text-align:center;transform:translateX(-6px);font-size:10.5px
}
.wpo-nodes-page .wpo-node-template .ico{
    flex:0 0 13px;width:13px;height:13px;margin:0;vertical-align:middle
}
.wpo-nodes-page .wpo-node-card-bottom{
    grid-row:3;align-self:end;min-height:27px;margin:0;padding:0;
    display:flex;align-items:center;justify-content:flex-end
}
.wpo-nodes-page .wpo-node-card-bottom .wpo-node-actions{margin-left:auto}
.wpo-nodes-page .wpo-node-main-flag{position:relative}
.wpo-nodes-page .wpo-node-main-mark{
    position:absolute;top:-5px;right:-5px;display:grid;place-items:center;
    width:16px;height:16px;border:1px solid var(--line);border-radius:50%;
    background:var(--surface);color:#eab308;
    font:700 10px/1 system-ui,sans-serif
}
@media(max-width:700px){
  .wpo-nodes-page .wpo-node-card{min-height:157px}
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'Единая сетка и оформление доменов')

once(
    '    # wpo-node-visual-v14\n    # wpo-node-compact-v6',
    '    # wpo-node-visual-v14\n    # wpo-node-polish-v15\n    # wpo-node-compact-v6',
    'Маркер v15')

compile(src,str(path),'exec')
temp=path.with_suffix('.py.nodes15tmp')
temp.write_text(src,encoding='utf-8')
temp.chmod(path.stat().st_mode & 0o777)
temp.replace(path)
print('Карточки выровнены, названия по центру флага, домены на одной линии.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Ошибка обновления: восстановлен предыдущий интерфейс.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или перезапуска: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v15: визуал карточек нод обновлён.'
echo "Резервная копия: $BACKUP"
echo 'Подключения, настройки и Node Agent не изменены. GitHub main не затронут.'
