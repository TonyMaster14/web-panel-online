#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service

[[ $EUID -eq 0 ]] || { echo 'Запустите от root на основном VPS с WPO.'; exit 1; }
[[ -s "$UI" ]] || { echo "Файл не найден: $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo 'Служба панели не найдена.'; exit 1; }
grep -Fq '# wpo-node-polish-v15' "$UI" || { echo 'Требуется установленный Nodes Lab v15. Ничего не изменено.'; exit 1; }
if grep -Fq '# wpo-node-finetune-v16' "$UI"; then
  echo 'Nodes Lab v16 уже установлен.'
  exit 0
fi

BACKUP="/var/lib/tproxy-panel/nodes-lab-v16-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')

def once(old,new,label):
    global src
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: найдено {n} совпадений вместо 1. Изменений нет.')
    src=src.replace(old,new,1)

# Keep both node columns identical; reduce each card by only eight pixels.
once(
    '    grid-template-rows:40px minmax(0,1fr) 27px;\n    row-gap:7px;\n    min-height:157px;',
    '    grid-template-rows:40px minmax(0,1fr) 25px;\n    row-gap:6px;\n    min-height:149px;',
    'Высота двух карточек')

# Move the domain down equally in the main and additional node.
once(
    '    gap:6px;min-width:0;padding:0;flex:none;',
    '    gap:6px;min-width:0;padding:7px 0 0;flex:none;',
    'Домены чуть ниже')

# Align the gear icon and site-template name with the globe and domain text.
once(
    '    display:flex;align-items:center;justify-content:center;gap:4px;\n'
    '    min-width:0;margin:3px 0 0;line-height:1.35;\n'
    '    text-align:center;transform:translateX(-6px);font-size:10.5px',
    '    display:flex;align-items:center;justify-content:flex-start;gap:7px;\n'
    '    min-width:0;margin:3px 0 0;line-height:1.35;\n'
    '    text-align:left;transform:none;font-size:10.5px',
    'Подпись шаблона слева, по сетке домена')

once(
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:157px}\n}',
    '@media(max-width:700px){\n  .wpo-nodes-page .wpo-node-card{min-height:149px}\n}',
    'Адаптация мобильного вида')

once(
    '    # wpo-node-polish-v15\n    # wpo-node-compact-v6',
    '    # wpo-node-polish-v15\n    # wpo-node-finetune-v16\n    # wpo-node-compact-v6',
    'Маркер v16')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes16tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Высота карточек уменьшена на 8px, домены опущены, подпись шаблона выровнена по тексту.')
PY_PATCH
then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  echo 'Ошибка правки: интерфейс восстановлен.'
  exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  cp -a "$BACKUP/wpp_ui.py" "$UI"
  systemctl restart "$SERVICE" || true
  echo 'Ошибка проверки/перезапуска: выполнен откат.'
  exit 1
fi

echo 'Nodes Lab v16: карточки чуть ниже, домены опущены, строка шаблона слева.'
echo "Резервная копия: $BACKUP"
echo 'Функции нод не затронуты. Основная ветка main не изменена.'
