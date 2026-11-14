#!/usr/bin/env bash
# WEB PANEL ONLINE 3.0 — terminal installer, consolidated Nodes Lab v26.
# A legacy noninteractive entrypoint is retained for automation and ZIP users.
set -Eeuo pipefail
umask 077
export GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
REPOSITORY="https://github.com/TonyMaster14/web-panel-online.git"
RELEASE_REF="${WEB_PANEL_PROXY_REF:-main}"
SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
LOCAL_BASE=""
if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
    LOCAL_BASE="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
fi

error(){ printf '\n\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || error 'Запускайте установщик с sudo или от root.'

# The wizard is an optional front-end; core services keep the original
# documented unattended workflow and all existing port/security checks.
USE_WIZARD=0
if [[ -t 0 && -t 1 && "${WPO_CLASSIC_INSTALL:-0}" != 1 ]]; then USE_WIZARD=1; fi
FINAL_SCREEN=0
WORK="" CREDENTIALS="" PROGRESS="" RESULT="" INSTALL_PID="" LOG=""
cleanup(){
    if [[ -n "$INSTALL_PID" ]] && kill -0 "$INSTALL_PID" 2>/dev/null; then
        kill "$INSTALL_PID" 2>/dev/null || true
        wait "$INSTALL_PID" 2>/dev/null || true
    fi
    if [[ -n "$CREDENTIALS" && -f "$CREDENTIALS" ]]; then
        command -v shred >/dev/null 2>&1 && shred -u "$CREDENTIALS" 2>/dev/null || rm -f -- "$CREDENTIALS"
    fi
    [[ -n "$RESULT" && -f "$RESULT" ]] && { shred -u "$RESULT" 2>/dev/null || rm -f -- "$RESULT"; }
    [[ -n "$PROGRESS" && -f "$PROGRESS" ]] && rm -f -- "$PROGRESS"
    [[ -n "$WORK" && -d "$WORK" ]] && rm -rf -- "$WORK"
    if (( USE_WIZARD )); then printf '\033[0m\033[?25h'; fi
    # EXIT traps must not turn a successful installation into exit code 1
    # just because the final optional cleanup condition was false.
    return 0
}
trap cleanup EXIT
trap 'printf "\n"; exit 130' INT TERM

WPO_LEFT=1
inset='  '
blue=$'\033[38;5;75m' cyan=$'\033[38;5;51m' ice=$'\033[38;5;153m'
gray=$'\033[38;5;245m' bold=$'\033[1m' reset=$'\033[0m' red=$'\033[38;5;203m' success=$'\033[38;5;83m'
# Use normal terminal flow: no full-screen canvas or saved cursor coordinates.
terminal_size(){
    local rows=""
    UI_COLS=""
    read -r rows UI_COLS < <(stty size </dev/tty 2>/dev/null) || true
    [[ "$UI_COLS" =~ ^[0-9]+$ ]] || UI_COLS=80
    (( UI_COLS >= 20 )) || UI_COLS=80
    UI_ROWS="${rows:-24}"
}
# Boxes fit the viewport and start in the same column as the shell prompt.
box_rule(){
    BOX_WIDTH=$((UI_COLS-3))
    (( BOX_WIDTH > 62 )) && BOX_WIDTH=62
    # Only on the final success screen: match the actual access-card border.
    if [[ "${WPO_FINAL_BANNER_INNER_WIDTH:-}" =~ ^[0-9]+$ ]]; then
        BOX_WIDTH="$WPO_FINAL_BANNER_INNER_WIDTH"
    fi
    printf -v BOX_RULE '%*s' "$BOX_WIDTH" ''
    BOX_RULE="${BOX_RULE// /─}"
}
box_text(){
    local text="$1" color="$2" chunk left right padl padr
    while [[ -n "$text" ]]; do
        chunk="${text:0:BOX_WIDTH}"; text="${text:BOX_WIDTH}"
        left=$(((BOX_WIDTH-${#chunk})/2)); right=$((BOX_WIDTH-${#chunk}-left))
        printf -v padl '%*s' "$left" ''; printf -v padr '%*s' "$right" ''
        printf '%s│%s%s%s%s%s│%s\n' "$blue" "$color" "$padl" "$chunk" "$padr" "$reset$blue" "$reset"
    done
}
banner(){
    box_rule
    printf '\n%s╭%s╮%s\n' "$blue" "$BOX_RULE" "$reset"
    box_text 'WEB PANEL ONLINE 3.0' "$bold$ice"
    box_text 'МАСТЕР УСТАНОВКИ' "$bold$cyan"
    printf '%s╰%s╯%s\n' "$blue" "$BOX_RULE" "$reset"
}
welcome(){
    printf '\n%sДобро пожаловать в мастер установки!%s\n' "$cyan" "$reset"
    box_rule
    printf '%s╭%s╮%s\n' "$blue" "$BOX_RULE" "$reset"
    box_text 'ENTER — установить   │   q — выход' "$bold$cyan"
    printf '%s╰%s╯%s\n' "$blue" "$BOX_RULE" "$reset"
}
render_context(){
    banner
    welcome
    printf '\n'
    if [[ "${UPDATE:-0}" == 1 ]]; then
        printf '%sОбновление панели: данные сохранены.%s\n' "$ice" "$reset"
    else
        local gap='\n\n'
        (( UI_ROWS < 30 )) && gap='\n'
        printf '%sДомен: %s%s' "$cyan" "${DOMAIN:-}" "$reset"
        printf '%b' "$gap"
        printf '%sEmail: %s%s' "$cyan" "${EMAIL:-}" "$reset"
        printf '%b' "$gap"
        printf '%sЛогин: %s%s' "$cyan" "${DISPLAY_ADMIN:-}" "$reset"
        printf '%b' "$gap"
        printf '%sПароль (не отображается)%s\n' "$cyan" "$reset"
    fi
}
valid_domain(){
    local d="$1" part
    [[ "$d" == *.* && ${#d} -le 253 && "$d" != *..* && "$d" =~ ^[a-z0-9].*[a-z0-9]$ ]] || return 1
    IFS=. read -ra parts <<< "$d"
    for part in "${parts[@]}"; do
        [[ ${#part} -ge 1 && ${#part} -le 63 &&
           "$part" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || return 1
    done
}
valid_email(){ [[ "$1" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; }
ask_domain(){
    while true; do
        printf '%s%sДомен:%s ' "$inset" "$cyan" "$reset"
        read -r DOMAIN || exit 130
        DOMAIN="${DOMAIN,,}"
        valid_domain "$DOMAIN" && break
        printf '%s  Укажите действительный домен без https:// и пробелов.%s\n' "$gray" "$reset"
    done
}
ask_email(){
    while true; do
        printf '%s%sEmail:%s ' "$inset" "$cyan" "$reset"
        read -r EMAIL || exit 130
        valid_email "$EMAIL" && break
        printf '%s  Нужен настоящий адрес формата name@example.com.%s\n' "$gray" "$reset"
    done
}
ask_admin(){
    while true; do
        printf '%s%sЛогин:%s ' "$inset" "$cyan" "$reset"
        read -r ADMIN || exit 130
        ADMIN="${ADMIN:-admin}"
        [[ ${#ADMIN} -le 64 && "$ADMIN" =~ ^[[:alnum:]_.@-]+$ ]] && break
        printf '%s  Используйте буквы, цифры, _, точку или дефис.%s\n' "$gray" "$reset"
    done
}
ask_password(){
    while true; do
        # Password is entered once, invisibly at the prompt after the colon.
        printf '%s%sПароль (не отображается):%s ' "$inset" "$cyan" "$reset"
        read -r -s PASS || exit 130
        printf '\n'
        if (( ${#PASS} < 3 )); then
            printf '%s  Пароль должен содержать минимум 3 символа.%s\n' "$gray" "$reset"
            unset PASS
            continue
        fi
        break
    done
}

# Classic mode remains compatible with previous invocation patterns.
if (( ! USE_WIZARD )); then
    if [[ -n "$LOCAL_BASE" && -s "$LOCAL_BASE/install-final.sh" && -s "$LOCAL_BASE/wpp_subscriptions.py" && -s "$LOCAL_BASE/node-install.sh" ]]; then
        bash "$LOCAL_BASE/install-final.sh"
        exit $?
    fi
    echo 'WEB PANEL ONLINE V 3.0.0 — загрузка файлов установки...'
    if ! command -v git >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get -o Acquire::ForceIPv4=true -o DPkg::Lock::Timeout=600 update
        apt-get -o Acquire::ForceIPv4=true -o DPkg::Lock::Timeout=600 install -y --no-install-recommends git ca-certificates
    fi
    WORK="$(mktemp -d /tmp/web-panel-proxy-install.XXXXXXXX)"
    git clone --depth 1 --branch "$RELEASE_REF" "$REPOSITORY" "$WORK/source"
    [[ -s "$WORK/source/install-final.sh" ]] || error 'Неполный пакет GitHub.'
    chmod 0700 "$WORK/source"/*.sh
    bash "$WORK/source/install-final.sh"
    exit $?
fi

# Start the wizard on a clean visible screen; retain terminal scrollback.
# This runs once, never during input, progress updates or terminal resizing.
printf '\033[0m\033[2J\033[H'
terminal_size
banner
welcome
while true; do
    printf '%s' "$inset"
    read -r choice || exit 130
    [[ "$choice" != q && "$choice" != Q ]] || exit 0
    [[ -z "$choice" ]] && break
    printf '%s  Нажмите Enter или q для выхода.%s\n' "$gray" "$reset"
done

UPDATE=0
if [[ -s /var/lib/tproxy-panel/data.json && -f /etc/systemd/system/tproxy-panel.service ]] &&
   grep -Eq 'Environment=WEBPROXY_PANEL_PATH=/panel-[a-z0-9-]{3,64}' /etc/systemd/system/tproxy-panel.service; then
    UPDATE=1
    printf '\n%s  Найдена установленная панель: обновляем код, учётные данные сохраняем.%s\n' "$cyan" "$reset"
    DOMAIN="" EMAIL=""
else
    ask_domain
    printf '\n'
    ask_email
    printf '\n'
    ask_admin
    printf '\n'
    ask_password
    CREDENTIALS="$(mktemp /run/wpo-ui-credentials.XXXXXXXX)"
    chmod 0600 "$CREDENTIALS"
    printf '%s\n%s\n' "$ADMIN" "$PASS" > "$CREDENTIALS"
    DISPLAY_ADMIN="$ADMIN"
    unset PASS ADMIN
fi


install -d -o root -g root -m 0700 /var/log/web-panel-online
LOG="/var/log/web-panel-online/install-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
: > "$LOG"
chmod 0600 "$LOG"
PROGRESS="$(mktemp /run/wpo-ui-progress.XXXXXXXX)"
RESULT="$(mktemp /run/wpo-ui-result.XXXXXXXX)"
chmod 0600 "$PROGRESS" "$RESULT"
printf '1\tЗагрузка пакета\n' > "$PROGRESS"

# Keep one five-row progress block: status, gap, bar, gap, current stage.
# Reserve its rows once. Resize events rebuild the layout once on the new screen.
DRAW_LAST="" DRAW_READY=0 DRAW_RESIZED=0
trap 'DRAW_RESIZED=1' WINCH
draw(){
    local pct="$1" label="$2" elapsed="$3" width filled empty bar rest key
    local status stage packet prefix="" maxtext
    [[ "$label" != 'Установка нод' ]] || label='Установка ноды'
    if (( pct >= 90 && pct < 100 )); then label='Завершение установки'; fi
    key="$pct|$label|$elapsed"
    [[ "$key" != "$DRAW_LAST" || "$DRAW_RESIZED" == 1 ]] || return 0
    DRAW_LAST="$key"
    local previous_cols="$UI_COLS" previous_rows="${UI_ROWS:-24}"
    terminal_size
    if [[ "$UI_COLS" != "$previous_cols" || "$UI_ROWS" != "$previous_rows" ]]; then DRAW_RESIZED=1; fi
    if (( DRAW_RESIZED )); then
        printf '\033[0m\033[2J\033[H'
        render_context
        DRAW_READY=0
        DRAW_RESIZED=0
    fi
    if (( ! DRAW_READY )); then
        # Ensure all rows exist even when the previous prompt was near the bottom.
        printf '\n\n\n\n\n'
        DRAW_READY=1
    fi
    prefix=$'\033[4A\r'
    width=$((UI_COLS-24))
    (( width > 40 )) && width=40
    (( width < 1 )) && width=1
    filled=$((pct*width/100)); empty=$((width-filled))
    printf -v bar '%*s' "$filled" ''; bar="${bar// /█}"
    printf -v rest '%*s' "$empty" ''; rest="${rest// /░}"
    maxtext=$((UI_COLS-3))
    status='УСТАНОВКА …'
    stage="Этап: $label"
    if (( pct == 100 )); then
        status='УСТАНОВКА ЗАВЕРШЕНА!'
        stage=''
    fi
    printf -v packet '%s\033[2K  %s%s%s\n\r\033[2K\n\r\033[2K  %s%s%s%s%s  %3d%%  %s%02d:%02d:%02d%s\n\r\033[2K\n\r\033[2K  %s%s%s' \
        "$prefix" "$bold$success" "${status:0:maxtext}" "$reset" \
        "$cyan" "$bar" "$blue" "$rest" "$reset" "$pct" \
        "$ice" "$((elapsed/3600))" "$(((elapsed%3600)/60))" "$((elapsed%60))" "$reset" \
        "$ice" "${stage:0:maxtext}" "$reset"
    printf '%s' "$packet"
}
printf '\033[?25l'
started=$SECONDS
shown=1
label='Загрузка пакета'
draw "$shown" "$label" "$((SECONDS-started))"
SOURCE=""
if [[ -n "$LOCAL_BASE" && -s "$LOCAL_BASE/install-final.sh" && -s "$LOCAL_BASE/wpp_subscriptions.py" && -s "$LOCAL_BASE/node-install.sh" ]]; then
    SOURCE="$LOCAL_BASE"
else
    if ! command -v git >/dev/null 2>&1; then
        if ! { export DEBIAN_FRONTEND=noninteractive; apt-get -o Acquire::ForceIPv4=true -o DPkg::Lock::Timeout=600 update &&
            apt-get -o Acquire::ForceIPv4=true -o DPkg::Lock::Timeout=600 install -y --no-install-recommends git ca-certificates; } >> "$LOG" 2>&1; then
            printf '\n'; error "Не удалось подготовить Git. Журнал: $LOG"
        fi
    fi
    WORK="$(mktemp -d /tmp/web-panel-proxy-install.XXXXXXXX)"
    git clone --depth 1 --branch "$RELEASE_REF" "$REPOSITORY" "$WORK/source" >> "$LOG" 2>&1 &
    INSTALL_PID=$!
    while kill -0 "$INSTALL_PID" 2>/dev/null; do
        draw "$shown" 'Загрузка GitHub' "$((SECONDS-started))"
        sleep 0.2
    done
    if ! wait "$INSTALL_PID"; then
        INSTALL_PID=""
        printf '\n'; error "Не удалось загрузить GitHub. Журнал: $LOG"
    fi
    INSTALL_PID=""
    SOURCE="$WORK/source"
fi
[[ -s "$SOURCE/install-final.sh" && -s "$SOURCE/node-install.sh" ]] || {
    printf '\n'; error "Неполный пакет установщика. Журнал: $LOG"
}
chmod 0700 "$SOURCE"/*.sh
printf '7\tПроверка установочного пакета\n' > "$PROGRESS"
label='Проверка установочного пакета'
# Show the actual verified milestone immediately, not one extra second per %.
shown=7
draw "$shown" "$label" "$((SECONDS-started))"
confirmed=7

WEB_PANEL_PROXY_DOMAIN="$DOMAIN" WEB_PANEL_PROXY_ACME_EMAIL="$EMAIL" \
    WPO_UI_CREDENTIALS_FILE="$CREDENTIALS" WPO_UI_PROGRESS_FILE="$PROGRESS" \
    WPO_UI_RESULT_FILE="$RESULT" WPO_CARD_WIZARD=0 WPO_CARD_COLUMNS="$UI_COLS" \
    bash "$SOURCE/install-final.sh" >> "$LOG" 2>&1 &
INSTALL_PID=$!
label='Проверка установочного пакета'
while kill -0 "$INSTALL_PID" 2>/dev/null; do
    if IFS=$'\t' read -r target current_label < "$PROGRESS"; then
        if [[ "$target" =~ ^[0-9]+$ ]] && (( target >= shown && target < 100 )); then
            # Animate toward confirmed progress without running ahead of the installer.
            (( target > confirmed )) && confirmed="$target"
            [[ -n "$current_label" ]] && label="$current_label"
        fi
    fi
    # The backend writes only verified milestones. Never artificially lag
    # behind it by one percent per second on fast VPS installations.
    if (( shown < confirmed )); then shown=$confirmed; fi
    draw "$shown" "$label" "$((SECONDS-started))"
    sleep 1
done
code=0
wait "$INSTALL_PID" || code=$?
INSTALL_PID=""
if (( code == 0 )); then
    # Never display 100% or success if the final access card is missing.
    if [[ ! -s "$RESULT" ]]; then
        printf '\n'
        error "Нет итоговой карточки доступа. Проверьте журнал: $LOG"
    fi
    # A successful backend and valid result permit 100% immediately: no
    # artificial 1-second-per-percent countdown before the finished screen.
    shown=100
    draw "$shown" "$label" "$((SECONDS-started))"
    # Show verified access details two seconds after the 100% milestone.
    sleep 2
    # One final screen transition after the two-second success hold.
    # Clear the visible screen only; do not erase terminal scrollback.
    printf '\033[0m\033[2J\033[H'
    terminal_size
    # Match the upper banner's horizontal extent to the lower access frame.
    # The result file may start with a color-reset-only line, so locate the
    # actual ╭...╮ line instead of assuming it is the first line.
    final_card_rule=""
    while IFS= read -r final_card_line; do
        if [[ "$final_card_line" == *"╭"*"╮"* ]]; then
            final_card_rule="${final_card_line#*╭}"
            final_card_rule="${final_card_rule%%╮*}"
            # Strip the leading ANSI color sequence without changing the ─.
            final_card_rule="${final_card_rule##*m}"
            break
        fi
    done < "$RESULT"
    [[ "$final_card_rule" =~ ^─+$ ]] || error 'Не удалось определить длину итоговой рамки.'
    WPO_FINAL_BANNER_INNER_WIDTH="${#final_card_rule}"
    banner
    cat -- "$RESULT"
    FINAL_SCREEN=1
else
    printf '\n%s  ✖ Установка прервана (код %d)%s\n' "$red" "$code" "$reset"
    hint="$(grep -Ei 'too many certificates|rateLimited|invalidContact|invalid_email|^ERROR:|^Ошибка|HTTPS.*не готов|failed|ошибка' "$LOG" | tail -n 1 || true)"
    [[ -z "$hint" ]] || printf '  %s\n' "$hint"
    printf '  Подробности: %s\n' "$LOG"
    printf '  Установку можно повторить, не очищая VPS.\n'
    exit "$code"
fi
