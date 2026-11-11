#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
UI=/opt/tproxy-panel/wpp_ui.py
SERVICE=tproxy-panel.service
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI"; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Служба $SERVICE не найдена."; exit 1; }
grep -q 'wpo-node-title-v5' "$UI" || { echo 'Нужен установленный Nodes Lab v5. Ничего не изменено.'; exit 1; }

BACKUP="/var/lib/tproxy-panel/nodes-lab-v6-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"
if ! python3 - "$UI" <<'PY_PATCH'
from pathlib import Path
import sys

p=Path(sys.argv[1])
src=p.read_text(encoding='utf-8')
if '# wpo-node-compact-v6' in src:
    print('Компактное оформление v6 уже установлено.')
    raise SystemExit(0)

def once(old,new,label):
    global src
    count=src.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: найдено {count} совпадений, требуется одно. Изменения не записаны.')
    src=src.replace(old,new,1)

# Remove the empty footer from the primary card.
once(
    '      <div class="wpo-node-card-bottom"><span class="muted">Основная</span></div>\n      </article>',
    '      </article>',
    'Нижняя полоса основной ноды')

# Put edit/delete controls beside the status, so other nodes need no footer.
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">{esc(node_flag(code))}</span><div class="wpo-node-label"><h3 title="{esc(name)}">{esc(name)}</h3><small>{esc(country)}</small></div><div class="wpo-node-head-tools">{status(uid,state)}<div class="wpo-node-actions">{edit}{delete}</div></div></div>',
    'Кнопки подключённой ноды')
once(
    '          <div class="wpo-node-card-bottom"><span>Агент {esc(n.get("version","—"))}</span><div class="wpo-node-actions">{edit}{delete}</div></div>',
    '',
    'Нижняя полоса подключённой ноды')
once(
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)}</p></div>',
    '<p class="wpo-node-template">{icon("settings")} {esc(site_name)} · Агент {esc(n.get("version","—"))}</p></div>',
    'Версия ноды рядом с шаблоном')
once(
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div>{status(uid,state)}</div>',
    '<div class="wpo-node-card-head"><span class="wpo-node-flag">◇</span><div class="wpo-node-label"><h3>Установка</h3><small>Подключение ноды</small></div><div class="wpo-node-head-tools">{status(uid,state)}<div class="wpo-node-actions">{delete}</div></div></div>',
    'Корзина временной установки')
once(
    '          <div class="wpo-node-card-bottom"><span>Одноразовый установщик</span><div class="wpo-node-actions">{delete}</div></div></article>',
    '          </article>',
    'Нижняя полоса временной установки')

# Remove empty placeholder and the legend under the grid.
once(
    '    empty=\'\' if nodes or pending_nodes else \'<div class="wpo-node-empty"><b>Дополнительных нод пока нет</b><small>Добавьте ноду, чтобы подключить отдельный VPS.</small></div>\'\n',
    '',
    'Пустой блок')
once(
    '+\'<div class="wpo-node-stats">\'+stats+\'</div><div class="wpo-node-grid">\'+\'\'.join(cards)+(empty if empty else \'\')+\'</div>\'',
    '+\'<div class="wpo-node-stats">\'+stats+\'</div><div class="wpo-node-grid">\'+\'\'.join(cards)+\'</div>\'',
    'Сетка без пустой карточки')
once(
    '+\'<div class="wpo-node-legend"><span><i class="online"></i>В сети</span><span><i class="installing"></i>Установка</span><span><i class="registration"></i>Регистрация</span><span><i class="offline"></i>Не в сети</span><span><i class="error"></i>Ошибка</span></div></section>\'',
    '+\'</section>\'',
    'Удаление легенды под нодами')

# Compact cards in the same two-column, left-to-right flow.
once(
    'aspect-ratio:auto;min-width:0;min-height:172px;margin:0;padding:14px;',
    'aspect-ratio:auto;min-width:0;min-height:108px;margin:0;padding:12px;',
    'Высота карточек')
once(
    '.wpo-node-card-body{display:grid;gap:7px;min-width:0;align-content:center;flex:1;padding:9px 0}',
    '.wpo-node-card-body{display:grid;gap:5px;min-width:0;align-content:center;flex:0 0 auto;padding:6px 0 0}',
    'Компактное содержимое')
once(
    '.wpo-node-card-head,.wpo-node-card-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}',
    '.wpo-node-card-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.wpo-node-head-tools{display:flex;align-items:center;gap:5px;flex:0 0 auto;min-width:0}',
    'Кнопки и статус в заголовке')
once(
    '.wpo-node-card-bottom{padding-top:10px;border-top:1px solid var(--line);min-height:38px;font-size:10px;color:var(--muted)}.wpo-node-actions{display:flex;align-items:center;gap:5px}.wpo-node-actions form{margin:0}',
    '.wpo-node-actions{display:flex;align-items:center;gap:3px}.wpo-node-actions form{margin:0}',
    'Убрать нижний разделитель')
once(
    '.wpo-nodes-page .wpo-node-icon{height:34px;width:34px;padding:6px;',
    '.wpo-nodes-page .wpo-node-icon{height:29px;width:29px;padding:5px;',
    'Размер кнопок управления')
once(
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start}',
    '.wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,410px));gap:12px;align-items:start;justify-content:start;grid-auto-flow:row}',
    'Порядок слева направо')
once(
    '.wpo-nodes-page .wpo-node-card{min-height:172px}',
    '.wpo-nodes-page .wpo-node-card{min-height:108px}',
    'Мобильная высота')
once(
    '    # wpo-node-title-v5\n    css=',
    '    # wpo-node-title-v5\n    # wpo-node-compact-v6\n    css=',
    'Маркер обновления')

compile(src,str(p),'exec')
tmp=p.with_suffix('.py.nodes6tmp')
tmp.write_text(src,encoding='utf-8')
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print('Карточки укорочены, элементы управления сохранены, пустой блок и нижняя легенда удалены.')
PY_PATCH
then
    echo 'Патч не применён. Восстанавливаю файл.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    exit 1
fi

if ! python3 -m py_compile "$UI" || ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
    echo 'Ошибка проверки или запуска. Выполняю откат.'
    cp -a "$BACKUP/wpp_ui.py" "$UI"
    systemctl restart "$SERVICE" || true
    exit 1
fi
echo "Nodes Lab v6 установлен. Резервная копия: $BACKUP"
echo 'Ветка main не изменена.'
