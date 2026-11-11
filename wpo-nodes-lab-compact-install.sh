#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_DIR=/opt/tproxy-panel
DATA_DIR=/var/lib/tproxy-panel
SERVICE=tproxy-panel.service
FILE="$APP_DIR/wpp_ui.py"
[[ $EUID -eq 0 ]] || { echo 'Запустите от root: sudo -i bash wpo-nodes-lab-compact-install.sh'; exit 1; }
[[ -s "$FILE" ]] || { echo "Не найден $FILE. Ничего не изменено."; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба $SERVICE."; exit 1; }
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$DATA_DIR/nodes-lab-compact-backup-$STAMP"
install -d -m 0700 "$BACKUP"
cp -a "$FILE" "$BACKUP/wpp_ui.py"
export WPO_UI_FILE="$FILE"
if ! python3 - <<'PY_PATCH'
import os
from pathlib import Path
p=Path(os.environ["WPO_UI_FILE"])
src=p.read_text(encoding="utf-8")
edits=[
(".wpo-node-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}",
 ".wpo-node-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,340px));gap:9px;align-items:start}"),
(".wpo-node-card{margin:0;padding:16px;border:1px solid",
 ".wpo-node-card{margin:0;padding:11px;width:100%;max-width:340px;box-sizing:border-box;border:1px solid"),
(".wpo-node-flag{display:grid;place-items:center;flex:0 0 42px;height:42px;border:1px solid var(--line);border-radius:11px;background:var(--input);font-size:22px}",
 ".wpo-node-flag{display:grid;place-items:center;flex:0 0 34px;height:34px;border:1px solid var(--line);border-radius:9px;background:var(--input);font-size:18px}"),
(".wpo-node-status{display:inline-flex;align-items:center;gap:6px;flex:0 0 auto;padding:6px 8px;border:1px solid var(--line);border-radius:20px;font-size:9px;white-space:nowrap}",
 ".wpo-node-status{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;padding:4px 7px;border:1px solid var(--line);border-radius:20px;font-size:8px;white-space:nowrap}"),
(".wpo-node-card-meta{display:flex;justify-content:space-between;gap:10px;margin-top:13px;padding-top:11px;border-top:1px solid var(--line);font-size:9px;color:var(--muted)}",
 ".wpo-node-card-meta{display:flex;justify-content:space-between;gap:8px;margin-top:8px;padding-top:7px;border-top:1px solid var(--line);font-size:8px;color:var(--muted)}"),
(".wpo-node-card-actions{display:flex;justify-content:flex-end;align-items:center;gap:7px;margin-top:10px}",
 ".wpo-node-card-actions{display:flex;justify-content:flex-end;align-items:center;gap:6px;margin-top:5px}"),
(".wpo-node-card-title strong{font-size:12px;",
 ".wpo-node-card-title strong{font-size:11px;")
]
for old,new in edits:
    n=src.count(old)
    if n!=1:
        raise SystemExit(f"Нельзя применить: CSS-фрагмент найден {n} раз. Файлы не изменены.")
    src=src.replace(old,new,1)
compile(src,str(p),"exec")
tmp=p.with_suffix(".py.compacttmp")
tmp.write_text(src,encoding="utf-8")
tmp.chmod(p.stat().st_mode & 0o777)
tmp.replace(p)
print("Компактная разметка подготовлена; синтаксис Python проверен.")
PY_PATCH
then
  echo 'Изменение не применено. Исходный файл сохранён без изменений.'
  exit 1
fi
if ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  echo 'Панель не запустилась. Выполняю откат.'
  cp -a "$BACKUP/wpp_ui.py" "$FILE"
  systemctl restart "$SERVICE" || true
  exit 1
fi
echo
echo 'Компактные карточки нод включены.'
echo "Резервная копия: $BACKUP"
echo 'GitHub main не изменялся.'
