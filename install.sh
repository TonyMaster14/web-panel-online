#!/usr/bin/env bash
# WEB PANEL ONLINE 3.0 — blue terminal test installer, consolidated Nodes Lab v26.
# A legacy noninteractive entrypoint is retained for automation and ZIP users.
set -Eeuo pipefail
umask 077
export GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
REPOSITORY="https://github.com/TonyMaster14/web-panel-online.git"
RELEASE_REF="${WEB_PANEL_PROXY_REF:-test/wpo-3-unified-blue-v26}"
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
    (( USE_WIZARD )) && printf '\033[0m' || true
    # EXIT traps must not turn a successful installation into exit code 1
    # just because the final optional cleanup condition was false.
    return 0
}
trap cleanup EXIT
trap 'printf "\n"; exit 130' INT TERM

blue=$'\033[38;5;75m' cyan=$'\033[38;5;51m' ice=$'\033[38;5;153m'
gray=$'\033[38;5;245m' bold=$'\033[1m' reset=$'\033[0m' red=$'\033[38;5;203m' success=$'\033[38;5;83m'
# Original midnight-blue neon canvas, only in an interactive SSH wizard.
if (( USE_WIZARD )); then
    reset=$'\033[0m\033[48;5;17m'
    printf '%s\033[2J\033[H' "$reset"
fi
banner(){
    printf '\n%s  ╭──────────────────────────────────────────────────────────────╮%s\n' "$blue" "$reset"
    printf '%s  │%s                 WEB PANEL ONLINE 3.0                         %s│%s\n' "$blue" "$bold$ice" "$blue" "$reset"
    printf '%s  │%s                    МАСТЕР УСТАНОВКИ                          %s│%s\n' "$blue" "$bold$cyan" "$blue" "$reset"
    printf '%s  ╰──────────────────────────────────────────────────────────────╯%s\n' "$blue" "$reset"
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
        read -r -p "  ${cyan}Домен:${reset} " DOMAIN || exit 130
        DOMAIN="${DOMAIN,,}"
        valid_domain "$DOMAIN" && break
        printf '%s  Укажите действительный домен без https:// и пробелов.%s\n' "$gray" "$reset"
    done
}
ask_email(){
    while true; do
        read -r -p "  ${cyan}Email:${reset} " EMAIL || exit 130
        valid_email "$EMAIL" && break
        printf '%s  Нужен настоящий адрес формата name@example.com.%s\n' "$gray" "$reset"
    done
}
ask_admin(){
    while true; do
        read -r -p "  ${cyan}Логин:${reset} " ADMIN || exit 130
        ADMIN="${ADMIN:-admin}"
        [[ ${#ADMIN} -le 64 && "$ADMIN" =~ ^[[:alnum:]_.@-]+$ ]] && break
        printf '%s  Используйте буквы, цифры, _, точку или дефис.%s\n' "$gray" "$reset"
    done
}
ask_password(){
    while true; do
        # Password is entered once, invisibly at the prompt after the colon.
        read -r -s -p "  ${cyan}Пароль (не отображается):${reset} " PASS || exit 130
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

banner
printf '\n  %sДобро пожаловать в мастер установки!%s\n' "$cyan" "$reset"

printf '  %s╭──────────────────────────────────────────────────────────────╮%s\n' "$blue" "$reset"
printf '  %s│%s  ›  ENTER — установить     %s│%s     q — выход                  %s│%s\n' "$blue" "$bold$cyan" "$blue" "$ice" "$blue" "$reset"
printf '  %s╰──────────────────────────────────────────────────────────────╯%s\n' "$blue" "$reset"
while true; do
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
    ask_email
    ask_admin
    ask_password
    CREDENTIALS="$(mktemp /run/wpo-ui-credentials.XXXXXXXX)"
    chmod 0600 "$CREDENTIALS"
    printf '%s\n%s\n' "$ADMIN" "$PASS" > "$CREDENTIALS"
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

# Display a live, accurate stage indicator: numbers come from the actual
# installer stages. The active stage stays below the bar while the timer measures elapsed time.
draw(){
    local pct="$1" label="$2" elapsed="$3"
    local cols width filled empty donebar leftbar maxlabel
    cols="$(tput cols 2>/dev/null || printf 80)"
    [[ "$cols" =~ ^[0-9]+$ ]] || cols=80
    width=$((cols-28))
    (( width > 42 )) && width=42
    (( width < 10 )) && width=10
    (( pct < 0 )) && pct=0
    (( pct > 100 )) && pct=100
    filled=$((pct*width/100)); empty=$((width-filled))
    printf -v donebar '%*s' "$filled" ''
    printf -v leftbar '%*s' "$empty" ''
    donebar="${donebar// /█}"; leftbar="${leftbar// /░}"
    maxlabel=$((cols-17)); (( maxlabel < 16 )) && maxlabel=16
    # Both status messages occupy the same row above the blue bar.
    if (( pct == 100 )); then
        printf '\r\033[2K  %s✓ Установка завершена!%s\n' "$success" "$reset"
    else
        printf '\r\033[2K  %s✓ Установка...%s\n' "$success" "$reset"
    fi
    printf '\r\033[2K  %s%s%s%s%s  %3d%%  %s◷ %02d:%02d:%02d%s\n' \
        "$cyan" "$donebar" "$blue" "$leftbar" "$reset" "$pct" \
        "$ice" "$((elapsed/3600))" "$(((elapsed%3600)/60))" "$((elapsed%60))" "$reset"
    # One blue-highlighted live stage/operation; never a separate "Операция" row.
    # At 100%, clear the stage line before showing the completed access card.
    if (( pct == 100 )); then
        printf '\r\033[2K'
    else
        printf '\r\033[2K  %s◈ %sЭтап: %s%s%s' "$cyan" "$blue" "$ice" "${label:0:maxlabel}" "$reset"
    fi
    printf '\033[2A\r'
}

# One clock for the entire installation, starting at package preparation.
started=$SECONDS
shown=1
label='Загрузка пакета'
printf '\n  %sХОД УСТАНОВКИ%s\n' "$cyan" "$reset"
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
        printf '\033[2B\r\n'; error "Не удалось загрузить GitHub. Журнал: $LOG"
    fi
    INSTALL_PID=""
    SOURCE="$WORK/source"
fi
[[ -s "$SOURCE/install-final.sh" && -s "$SOURCE/node-install.sh" ]] || {
    printf '\033[2B\r\n'; error "Неполный пакет установщика. Журнал: $LOG"
}
chmod 0700 "$SOURCE"/*.sh
printf '7\tПроверка установочного пакета\n' > "$PROGRESS"
shown=7
label='Проверка установочного пакета'
draw "$shown" "$label" "$((SECONDS-started))"

WEB_PANEL_PROXY_DOMAIN="$DOMAIN" WEB_PANEL_PROXY_ACME_EMAIL="$EMAIL" \
    WPO_UI_CREDENTIALS_FILE="$CREDENTIALS" WPO_UI_PROGRESS_FILE="$PROGRESS" \
    WPO_UI_RESULT_FILE="$RESULT" \
    bash "$SOURCE/install-final.sh" >> "$LOG" 2>&1 &
INSTALL_PID=$!
label='Проверка установочного пакета'
while kill -0 "$INSTALL_PID" 2>/dev/null; do
    if IFS=$'\t' read -r target current_label < "$PROGRESS"; then
        if [[ "$target" =~ ^[0-9]+$ ]] && (( target >= shown && target <= 100 )); then
            # Jump only to an actual milestone, never a fabricated 1%-per-tick.
            shown="$target"
            [[ -n "$current_label" ]] && label="$current_label"
        fi
    fi
    draw "$shown" "$label" "$((SECONDS-started))"
    sleep 0.2
done
code=0
wait "$INSTALL_PID" || code=$?
INSTALL_PID=""
if (( code == 0 )); then
    # Never display 100% or success if the final access card is missing.
    if [[ ! -s "$RESULT" ]]; then
        printf '\033[2B\r\n'
        error "Нет итоговой карточки доступа. Проверьте журнал: $LOG"
    fi
    draw 100 'Проверки завершены' "$((SECONDS-started))"
    printf '\033[2B\r'
    # Let the user see the real 100% completion for one second.
    sleep 1
    # Replace the wizard's fields and progress in place. Do NOT wipe the
    # whole SSH terminal: keep the WPO header and draw access details where
    # the domain/email/login/password fields were previously displayed.
    printf '\033[H'
    banner
    printf '\033[J'
    # The existing access card is now the only content below that header.
    cat -- "$RESULT"
else
    printf '\033[2B\r\n%s  ✖ Установка прервана (код %d)%s\n' "$red" "$code" "$reset"
    hint="$(grep -Ei 'too many certificates|rateLimited|invalidContact|invalid_email|^ERROR:|^Ошибка|HTTPS.*не готов|failed|ошибка' "$LOG" | tail -n 1 || true)"
    [[ -z "$hint" ]] || printf '  %s\n' "$hint"
    printf '  Подробности: %s\n' "$LOG"
    printf '  Установку можно повторить, не очищая VPS.\n'
    exit "$code"
fi
