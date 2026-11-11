#!/usr/bin/env bash
# WEB PANEL ONLINE — focused preset-card visual refresh, without replacing Nodes Lab.
set -Eeuo pipefail
umask 077

[[ $EUID -eq 0 ]] || { echo "Запустите от root на основном VPS панели." >&2; exit 1; }
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
[[ -s "$UI" ]] || { echo "Не найден $UI" >&2; exit 1; }
systemctl cat "$SERVICE" >/dev/null 2>&1 || { echo "Не найдена служба панели." >&2; exit 1; }

STAGE="$(mktemp -d /tmp/wpo-presets-cards.XXXXXXXX)"
BACKUP="/var/lib/tproxy-panel/preset-cards-backup-$(date -u +%Y%m%dT%H%M%SZ)"
RESTORE=0
cleanup() {
  local code=$?
  trap - EXIT
  if (( code != 0 && RESTORE )); then
      cp -a "$BACKUP/wpp_ui.py" "$UI" || true
      systemctl restart "$SERVICE" || true
      echo "Ошибка обновления: исходный интерфейс восстановлен." >&2
  fi
  rm -rf -- "$STAGE"
  exit "$code"
}
trap cleanup EXIT
install -d -m 0700 "$BACKUP"
cp -a "$UI" "$BACKUP/wpp_ui.py"

# Pinned main snapshot so a concurrent GitHub commit cannot alter only part
# of the patch being applied.
REF=b8eca4d1cc808e983e7ef5217ba9663dfefe8fc8
curl -4fsSL --retry 3 --connect-timeout 12 --max-time 70 \
  "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF/wpp_ui.py" \
  -o "$STAGE/wpp_ui.py"
python3 -m py_compile "$STAGE/wpp_ui.py"

python3 - "$UI" "$STAGE/wpp_ui.py" <<'PY'
from pathlib import Path
import os,re,sys,tempfile
target=Path(sys.argv[1]); reference=Path(sys.argv[2])
original=target.read_text(encoding="utf-8")
current=original
ref=reference.read_text(encoding="utf-8")

begin='def editor_ui(source, path, csrf, presets, has_draft):'
end='\ndef openflux_ui('
css_begin='# Compact outlined preset gallery'
def block(src,a,b):
    p=src.find(a)
    q=src.find(b,p+len(a))
    if p<0 or q<0 or src.find(a,p+len(a))>=0:
        raise SystemExit('Не удалось однозначно определить блок: '+a)
    return src[p:q]
new_editor=block(ref,begin,end)
old_editor=block(current,begin,end)
if 'id="presetGallery"' not in new_editor:
    raise SystemExit("Исходная сборка не содержит новый дизайн пресетов.")
if 'id="editorForm"' not in old_editor and 'id="presetGallery"' not in old_editor:
    raise SystemExit("Неожиданная версия редактора. Файлы не изменены.")
if old_editor != new_editor:
    current=current.replace(old_editor,new_editor,1)
css=block(ref,css_begin,'\ndef editor_ui(')
if css.count("CSS += '''")!=1:
    raise SystemExit("Не удалось найти единственные стили галереи.")
if css_begin not in current:
    current=current.replace(begin,css+'\n'+begin,1)
elif current.count(css_begin)!=1:
    raise SystemExit("Найдены дублирующиеся стили карточек.")
else:
    old_css=block(current,css_begin,'\ndef editor_ui(')
    current=current.replace(old_css,css,1)

# All node code and functionality outside the two deliberate replacements
# remain untouched. The control markers must survive.
node_marks=set(re.findall(r'(?:#|/\*) wpo-node-[^\n]+',original))
if not node_marks.issubset(set(re.findall(r'(?:#|/\*) wpo-node-[^\n]+',current))):
    raise SystemExit('Затронута логика Nodes Lab; применение отменено.')
compile(current,str(target),'exec')
if current==original:
    print('Карточки уже обновлены в файле. Проверьте кеш браузера.')
else:
    fd,tmp=tempfile.mkstemp(prefix='.wpp-preset-cards-',dir=str(target.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(current)
            f.flush();os.fsync(f.fileno())
        st=target.stat()
        os.chown(tmp,st.st_uid,st.st_gid)
        os.chmod(tmp,st.st_mode & 0o777)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    print('✓ Компактные карточки и предпросмотр обновлены в действующей панели.')
PY
RESTORE=1
python3 -m py_compile "$UI"
systemctl restart "$SERVICE"
systemctl is-active --quiet "$SERVICE" || { echo "Служба панели не запустилась." >&2; exit 1; }
python3 - "$UI" <<'PY'
from pathlib import Path
import sys
s=Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'id="presetGallery"' in s, 'Встроенная галерея отсутствует'
assert '# Compact outlined preset gallery' in s, 'Стили карточек отсутствуют'
assert 'grid-template-columns:repeat(4,minmax(0,1fr))' in s, 'Компактная сетка не установлена'
print('✓ Проверка интерфейса: новый дизайн карточек присутствует.')
PY
RESTORE=0
echo "✓ Готово. Резервная копия: $BACKUP"
echo "Обновите страницу панели с очисткой кеша: Ctrl+Shift+R / Cmd+Shift+R."
