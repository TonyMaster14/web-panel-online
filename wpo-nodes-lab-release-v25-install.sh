#!/usr/bin/env bash
# Frozen WPO Nodes Lab v25 deployment for an EXISTING WPO 3.0 controller VPS.
set -Eeuo pipefail
umask 077

REF="1f0915eadc802c84fe9b643a07c47d2561f18943"
BASE="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/$REF"
APP="/opt/tproxy-panel"
SERVICE="tproxy-panel.service"
DATA="/var/lib/tproxy-panel"
PANEL="$APP/panel.py"
UI="$APP/wpp_ui.py"
AGENT="$APP/wpp-node-agent-install.sh"
GEO="$APP/wpo_node_geo.py"
AUTO="$APP/wpo_node_autotemplate.py"
NODE="$APP/wpp_nodes.py"
SUB="$APP/wpp_subscriptions.py"

die(){ echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die 'Запустите от root на основном VPS WPO.'
command -v curl >/dev/null || die 'Требуется curl.'
command -v python3 >/dev/null || die 'Требуется python3.'
for file in "$PANEL" "$UI" "$NODE" "$SUB"; do
    [[ -s "$file" ]] || die "Сначала установите оригинальную WPO 3.0: отсутствует $file"
done
systemctl cat "$SERVICE" >/dev/null 2>&1 || die "Не найдена служба $SERVICE."
install -d -m 0700 "$DATA"

STAGE="$(mktemp -d /tmp/wpo-nodes-release.XXXXXXXX)"
BACKUP=""
TOUCHED=0
cleanup(){
    local rc=$?
    trap - EXIT
    if (( rc != 0 && TOUCHED == 1 )); then
        echo "Ошибка ($rc): возвращаю исходные файлы контроллера..." >&2
        for name in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py wpp-node-agent-install.sh wpo_node_geo.py wpo_node_autotemplate.py; do
            if [[ -f "$BACKUP/$name" ]]; then
                cp -a "$BACKUP/$name" "$APP/$name" || true
            elif [[ -f "$BACKUP/absent-$name" ]]; then
                rm -f "$APP/$name" || true
            fi
        done
        systemctl restart "$SERVICE" || true
        echo "Код восстановлен из $BACKUP. Данные пользователей и нод не удалены." >&2
    fi
    rm -rf "$STAGE"
    exit "$rc"
}
trap cleanup EXIT

# Download and syntax-check all versions BEFORE touching the panel.
for v in $(seq 1 25); do
    if [[ "$v" == 1 ]]; then file="wpo-nodes-lab-install.sh"
    else file="wpo-nodes-lab-v$v-install.sh"
    fi
    curl -4fsSL --retry 3 --connect-timeout 15 --max-time 80 "$BASE/$file" -o "$STAGE/$file"
    [[ -s "$STAGE/$file" ]] || die "Не удалось получить $file"
    bash -n "$STAGE/$file" || die "Повреждённый скрипт $file"
done
for file in wpo-node-agent-install-v2.sh wpo-node-geo-v13.py wpo-node-autotemplate-v20.py; do
    curl -4fsSL --retry 3 --connect-timeout 15 --max-time 80 "$BASE/$file" -o "$STAGE/$file"
    [[ -s "$STAGE/$file" ]] || die "Не удалось получить $file"
done
bash -n "$STAGE/wpo-node-agent-install-v2.sh"
python3 -m py_compile "$STAGE/wpo-node-geo-v13.py" "$STAGE/wpo-node-autotemplate-v20.py"

# Freeze nested downloads to the same snapshot, not the moving nodes-lab tip.
python3 - "$STAGE" "$REF" <<'PY_PIN'
from pathlib import Path
import sys
root, ref=Path(sys.argv[1]),sys.argv[2]
old='https://raw.githubusercontent.com/TonyMaster14/web-panel-online/nodes-lab/'
new='https://raw.githubusercontent.com/TonyMaster14/web-panel-online/'+ref+'/'
for version in (2,10,11,12,13,20,23):
    path=root/('wpo-nodes-lab-v'+str(version)+'-install.sh')
    content=path.read_text(encoding='utf-8')
    if old not in content:
        raise RuntimeError('Ожидаемый адрес не найден: '+path.name)
    path.write_text(content.replace(old,new),encoding='utf-8')
PY_PIN

BACKUP="$DATA/nodes-lab-release-v25-backup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$BACKUP"
for name in panel.py wpp_ui.py wpp_nodes.py wpp_subscriptions.py wpp-node-agent-install.sh wpo_node_geo.py wpo_node_autotemplate.py; do
    if [[ -f "$APP/$name" ]]; then cp -a "$APP/$name" "$BACKUP/$name"
    else : > "$BACKUP/absent-$name"
    fi
done

apply(){
    local script="$1" file="$2" marker="$3"
    if grep -Fq -- "$marker" "$file" 2>/dev/null; then
        echo "✓ Уже есть: $script"
    else
        echo "→ Применяю: $script"
        TOUCHED=1
        bash "$STAGE/$script"
    fi
}
apply wpo-nodes-lab-install.sh "$PANEL" "def wpo_pending_load"
apply wpo-nodes-lab-v2-install.sh "$UI" "wpo-node-card-head"
apply wpo-nodes-lab-v3-install.sh "$UI" "# wpo-node-compact-v3"
apply wpo-nodes-lab-v4-install.sh "$UI" "# wpo-node-title-v4"
apply wpo-nodes-lab-v5-install.sh "$UI" "# wpo-node-title-v5"
apply wpo-nodes-lab-v6-install.sh "$UI" "# wpo-node-compact-v6"
apply wpo-nodes-lab-v7-install.sh "$UI" "# wpo-node-width-v7"
apply wpo-nodes-lab-v8-install.sh "$UI" "wpo-node-spinner-v8"
apply wpo-nodes-lab-v9-install.sh "$UI" "# wpo-node-aligned-v9"

# The final v12 agent installer includes all v10–v12 email fixes.
# It lives on the controller, not on already enrolled remote VPSs.
if ! cmp -s "$STAGE/wpo-node-agent-install-v2.sh" "$AGENT"; then
    echo '→ Обновляю установщик Node Agent до финальной версии v12'
    TOUCHED=1
    install -m 0700 "$STAGE/wpo-node-agent-install-v2.sh" "$AGENT"
fi

apply wpo-nodes-lab-v13-install.sh "$PANEL" "# wpo-node-country-v13"
apply wpo-nodes-lab-v14-install.sh "$UI" "# wpo-node-visual-v14"
apply wpo-nodes-lab-v15-install.sh "$UI" "# wpo-node-polish-v15"
apply wpo-nodes-lab-v16-install.sh "$UI" "# wpo-node-finetune-v16"
apply wpo-nodes-lab-v17-install.sh "$UI" "# wpo-node-globe-v17"
apply wpo-nodes-lab-v18-install.sh "$UI" "# wpo-node-divider-v18"
apply wpo-nodes-lab-v19-install.sh "$UI" "# wpo-node-server-icon-v19"
apply wpo-nodes-lab-v20-install.sh "$PANEL" "# wpo-node-auto-v20"
apply wpo-nodes-lab-v21-install.sh "$UI" "/* wpo-node-heading-v21 */"
apply wpo-nodes-lab-v22-install.sh "$UI" "/* wpo-node-pending-row-v22 */"
apply wpo-nodes-lab-v23-install.sh "$AGENT" "wpo-node-agent-reinstall-v23"
apply wpo-nodes-lab-v24-install.sh "$UI" "/* wpo-node-indicator-center-v24 */"
apply wpo-nodes-lab-v25-install.sh "$PANEL" "# wpo-node-template-save-v25"

for file in "$PANEL" "$UI" "$GEO" "$AUTO"; do [[ -s "$file" ]] || die "Отсутствует файл: $file"; done
# Validate the final generated-node installer and controller feature set.
grep -Fq 'node-agent-installer.sh' "$PANEL" || die 'Нет маршрута установщика ноды.'
grep -Fq '# wpo-node-country-v13' "$PANEL" || die 'Нет геолокации нод.'
grep -Fq '# wpo-node-auto-v20' "$PANEL" || die 'Нет автоматического выбора шаблона.'
grep -Fq '/* wpo-node-heading-v21 */' "$UI" || die 'Не применён интерфейс v21.'
grep -Fq '/* wpo-node-pending-row-v22 */' "$UI" || die 'Не применена компактная сетка v22.'
grep -Fq 'site-template' "$AGENT" || die 'Установщик ноды не поддерживает шаблоны.'
grep -Fq 'for EMAIL_ATTEMPT in 1 2 3' "$AGENT" || die 'Установщик ноды не обновлён до итоговой версии.'
grep -Fq 'wpo-node-agent-reinstall-v23' "$AGENT" || die 'Исправление повторной установки ноды v23 отсутствует.'
grep -Fq '/* wpo-node-indicator-center-v24 */' "$UI" || die 'Центровка индикатора v24 отсутствует.'
grep -Fq '# wpo-node-template-save-v25' "$PANEL" || die 'Мгновенная публикация шаблона v25 отсутствует.'
grep -Fq '# wpo-node-template-sync-v25' "$AUTO" || die 'Синхронизация шаблонов v25 отсутствует.'
grep -Fq 'Шаблон: {esc(site_name)}' "$UI" || die 'Подпись шаблона v25 отсутствует.'
grep -Fq '__WPO_CONTROLLER_ENROLL_URL__' "$AGENT" || die 'Установщик ноды не связан с основной панелью.'
python3 -m py_compile "$PANEL" "$UI" "$GEO" "$AUTO"
bash -n "$AGENT"
systemctl is-active --quiet "$SERVICE" || die "Служба $SERVICE не активна."
echo
echo '✓ WPO Nodes Lab v25 установлен/проверен.'
echo "✓ Фиксированная версия: $REF"
echo "✓ Резервная копия до обновления: $BACKUP"
echo '✓ Геолокация, флаги, карточки и мгновенный выбор шаблонов сайтов сохранены.'
echo '✓ Основная ветка GitHub main не затронута.'
echo 'Важно: Node Agent 0.2 управляет HTTPS-страницей и статусом. VPN на удалённой ноде пока не активирован.'
