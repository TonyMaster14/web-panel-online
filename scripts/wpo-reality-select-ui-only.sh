#!/usr/bin/env bash
# WPO UI only: apply the REALITY-style single-border dropdowns without
# overwriting the node-agent customizations or touching network services.
set -Eeuo pipefail
umask 077
APP=/opt/tproxy-panel
UI="$APP/wpp_ui.py"
SERVICE=tproxy-panel.service
BACKUP_DIR=/var/lib/tproxy-panel/wpo-ui-backups
[[ $EUID -eq 0 ]] || { echo "Запустите с sudo на основной панели WPO." >&2; exit 1; }
[[ -s "$UI" ]] || { echo "Не найден $UI" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Не найден Python 3" >&2; exit 1; }
mkdir -p -m 0700 "$BACKUP_DIR"
STAGE="$(mktemp -d /tmp/wpo-reality-select-style.XXXXXXXX)"
BACKUP=""
CHANGED=0
cleanup() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )) && [[ -s "$BACKUP" ]]; then
    echo "Ошибка: возвращаю прежний интерфейс WPO..." >&2
    cp -a "$BACKUP" "$UI" || true
    systemctl restart "$SERVICE" || true
  fi
  rm -rf "$STAGE"
  exit "$rc"
}
trap cleanup EXIT
cat > "$STAGE/style.pyfrag" <<'WPO_STYLE_FRAG_END'
# WPO_REALITY_SELECT_STYLE_BEGIN
# Use the same single-border, 41px control as "Сайт для REALITY".
# Native selects remain native and keep their existing enabled/disabled behavior.
CSS += '''
#connectionProtocol,
#clientFilter,
#protocolFilter,
#clientSort,
#wpoEditNodeDialog select[name="site_template"],
#panelRelease,
#xrayRelease,
#openfluxRelease {
  box-sizing:border-box;
  width:100%;
  height:41px;
  min-height:41px;
  min-width:0;
  padding:0 38px 0 13px;
  border:1px solid var(--line);
  border-radius:10px;
  background-color:var(--input);
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2391aeb8' stroke-width='2.1' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat:no-repeat;
  background-position:right 12px center;
  background-size:16px 16px;
  color:var(--text);
  font:500 12px/1.4 "Segoe UI",system-ui,sans-serif;
  box-shadow:none;
  appearance:none;
  -webkit-appearance:none;
}
#clientFilter,
#protocolFilter,
#clientSort {width:auto;min-width:128px;max-width:175px}
#clientSort {min-width:118px}
#connectionProtocol:disabled,
#panelRelease:disabled,
#xrayRelease:disabled,
#openfluxRelease:disabled {
  opacity:1;
  color:var(--muted);
  cursor:not-allowed;
}
#connectionProtocol:focus-visible,
#clientFilter:focus-visible,
#protocolFilter:focus-visible,
#clientSort:focus-visible,
#wpoEditNodeDialog select[name="site_template"]:focus-visible,
#panelRelease:focus-visible,
#xrayRelease:focus-visible,
#openfluxRelease:focus-visible {
  outline:1px solid var(--muted);
  outline-offset:0;
  border-color:var(--line);
  box-shadow:none;
}
@media(max-width:700px) {
  #clientFilter,
  #protocolFilter,
  #clientSort {max-width:100%;min-width:0}
}
'''
# WPO_REALITY_SELECT_STYLE_END
WPO_STYLE_FRAG_END
set +e
python3 - "$UI" "$STAGE/style.pyfrag" "$STAGE/wpp_ui.py" <<'WPO_PATCH_PY'
import pathlib
import shutil
import sys
source, block_file, dest = map(pathlib.Path, sys.argv[1:4])
original = source.read_text(encoding="utf-8")
block = block_file.read_text(encoding="utf-8").strip()
a = "# WPO_REALITY_SELECT_STYLE_BEGIN"
b = "# WPO_REALITY_SELECT_STYLE_END"
if "CSS =" not in original or "COMMON_JS" not in original:
    raise SystemExit("Файл интерфейса WPO не распознан.")
if original.count(a)>1 or original.count(b)>1:
    raise SystemExit("Найдены дублирующиеся маркеры стиля. Отмена.")
if a in original:
    first = original.index(a)
    stop = original.index(b, first)+len(b)
    original = original[:first]+block+original[stop:]
else:
    original = original.rstrip()+"\n\n"+block+"\n"
marker = "# WPO_REALITY_SELECT_ASSET_REV"
recompute = marker+"\nASSET_REV = hashlib.sha256((CSS + COMMON_JS).encode('utf-8')).hexdigest()[:12]"
if marker in original:
    first = original.index(marker)
    last = original.find("\n", first + len(marker))
    if last<0:
        raise SystemExit("Некорректный маркер версии стилей.")
    # The generated reassignment line is always directly after the marker.
    end = original.find("\n", last+1)
    end = len(original) if end<0 else end
    original=original[:first]+recompute+original[end:]
else:
    original=original.rstrip()+"\n"+recompute+"\n"
compile(original, str(source), "exec")
if original==source.read_text(encoding="utf-8"):
    print("Стиль уже установлен. Изменений нет.",flush=True)
    raise SystemExit(77)
shutil.copy2(source,dest)
dest.write_text(original,encoding="utf-8")
compile(dest.read_text(encoding="utf-8"), str(dest), "exec")
print("Проверено: меняется только CSS пользовательских списков.",flush=True)
WPO_PATCH_PY
status=$?
set -e
if (( status == 77 )); then exit 0; fi
if (( status != 0 )); then exit "$status"; fi
BACKUP="$BACKUP_DIR/wpp_ui-before-selects-$(date -u +%Y%m%dT%H%M%SZ).py"
cp -a "$UI" "$BACKUP"
cp -a "$STAGE/wpp_ui.py" "$UI"
CHANGED=1
if ! systemctl restart "$SERVICE" || ! systemctl is-active --quiet "$SERVICE"; then
  echo "WPO не запустилась после изменения. Включается автоматический откат." >&2
  exit 1
fi
CHANGED=0
echo "Готово: четыре группы списков WPO теперь в стиле «Сайт для REALITY»."
echo "Функциональность, REALITY, VPN, ноды и маршруты не изменены."
echo "Резервная копия интерфейса: $BACKUP"
