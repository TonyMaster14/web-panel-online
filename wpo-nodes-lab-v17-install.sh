#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с панелью WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-finetune-v16' "$UI" || { echo 'Требуется установленный Nodes Lab v16. Ничего не изменено.'; exit 1; }
if grep -Fq '# wpo-node-globe-v17' "$UI"; then
  echo 'Оформление Nodes Lab v17 уже установлено.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v17-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

path=Path(sys.argv[1])
src=path.read_text(encoding='utf-8')
def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: найдено {count} совпадений вместо одного; файл не изменён.')
    src=src.replace(old,new,1)

# Both cards use the same monochrome, precisely aligned blue vector globe.
# Avoid platform-dependent emoji baseline and font sizing differences.
globe_svg=(
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
    'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9"/>'
    '<path d="M3 12h18M12 3c2.8 2.4 4 5.4 4 9s-1.2 6.6-4 9'
    'M12 3c-2.8 2.4-4 5.4-4 9s1.2 6.6 4 9"/>'
    '</svg>'
)
old_globe='<span class="wpo-domain-mark">🌐</span>'
count=src.count(old_globe)
if count != 2:
    raise RuntimeError(f'Глобусы основной и дополнительной ноды: найдено {count}, ожидается 2.')
src=src.replace(old_globe,'<span class="wpo-domain-mark">'+globe_svg+'</span>')

# Reduce both cards by another seven pixels, without moving top indicators.
once(
    '    grid-template-rows:40px minmax(0,1fr) 25px;\n    row-gap:6px;\n    min-height:149px;',
    '    grid-template-rows:40px minmax(0,1fr) 25px;\n    row-gap:6px;\n    min-height:142px;',
    'Высота двух карточек')
once(
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:149px}\n}',
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:142px}\n}',
    'Мобильная высота')

# Fix the icon and text baselines identically in both domain rows.
css="""
/* wpo-node-globe-v17: fixed SVG baseline for both domain rows */
.wpo-nodes-page .wpo-node-domain{
  display:grid;grid-template-columns:14px minmax(0,1fr);
  align-items:center;column-gap:7px;min-height:21px;line-height:1.35
}
.wpo-nodes-page .wpo-node-domain .wpo-domain-mark{
  display:flex;align-items:center;justify-content:center;
  width:14px;height:16px;min-width:14px;color:#38bdf8;
  font-size:0;line-height:0;filter:none;opacity:1;
}
.wpo-nodes-page .wpo-node-domain .wpo-domain-mark svg{
  display:block;width:14px;height:14px;flex:0 0 14px;
}
"""
once(
    "'''\n    js=r'''(()=>{const path=__PATH__",
    css+"\n'''\n    js=r'''(()=>{const path=__PATH__",
    'CSS выравнивания SVG')

once(
    '    # wpo-node-finetune-v16\n    # wpo-node-compact-v6',
    '    # wpo-node-finetune-v16\n    # wpo-node-globe-v17\n    # wpo-node-compact-v6',
    'Маркер v17')

compile(src,str(path),'exec')
tmp=path.with_suffix('.py.nodes17tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(path.stat().st_mode & 0o777)
tmp.replace(path)
print('Глобусы выровнены и заменены на голубые SVG, карточки уменьшены на 7px.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Изменения не применены. Восстановлена резервная копия.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки или запуска: выполнен откат.'
  exit 1
fi
echo 'Nodes Lab v17: одинаковые голубые глобусы, карточки ниже на 7px.'
echo "Резервная копия: $BACKUP"
echo 'Данные, функции нод и GitHub main не изменены.'
