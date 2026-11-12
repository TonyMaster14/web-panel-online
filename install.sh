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
    # EXIT traps must not turn a successful installation into exit code 1
    # just because the final optional cleanup condition was false.
    return 0
}
trap cleanup EXIT
trap 'printf "\n"; exit 130' INT TERM

blue=$'\033[38;5;75m' cyan=$'\033[38;5;51m' ice=$'\033[38;5;153m'
gray=$'\033[38;5;245m' bold=$'\033[1m' reset=$'\033[0m' red=$'\033[38;5;203m'
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
        read -r -p '  Домен: ' DOMAIN || exit 130
        DOMAIN="${DOMAIN,,}"
        valid_domain "$DOMAIN" && break
        printf '%s  Укажите действительный домен без https:// и пробелов.%s\n' "$gray" "$reset"
    done
}
ask_email(){
    while true; do
        read -r -p '  Email: ' EMAIL || exit 130
        valid_email "$EMAIL" && break
        printf '%s  Нужен настоящий адрес формата name@example.com.%s\n' "$gray" "$reset"
    done
}
ask_admin(){
    while true; do
        read -r -p '  Логин: ' ADMIN || exit 130
        ADMIN="${ADMIN:-admin}"
        [[ ${#ADMIN} -le 64 && "$ADMIN" =~ ^[[:alnum:]_.@-]+$ ]] && break
        printf '%s  Используйте буквы, цифры, _, точку или дефис.%s\n' "$gray" "$reset"
    done
}
ask_password(){
    while true; do
        # Password is entered once, invisibly at the prompt after the colon.
        read -r -s -p '  Пароль (не отображается): ' PASS || exit 130
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

printf '  %s›  ENTER — установить%s     %sq — выход%s\n' "$bold$cyan" "$reset" "$ice" "$reset"
while true; do
    read -r -p '  Ваш выбор: ' choice || exit 130
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
# installer stages. The small spinner moves while a long task is running.
draw(){
    local pct="$1" label="$2" elapsed="$3"
    local cols width filled empty donebar leftbar maxlabel
    cols="$(tput cols 2>/dev/null || printf 80)"
    [[ "$cols" =~ ^[0-9]+$ ]] || cols=80
    width=$((cols-12))
    (( width > 46 )) && width=46
    (( width < 12 )) && width=12
    (( pct < 0 )) && pct=0
    (( pct > 100 )) && pct=100
    filled=$((pct*width/100))
    empty=$((width-filled))
    printf -v donebar '%*s' "$filled" ''
    printf -v leftbar '%*s' "$empty" ''
    donebar="${donebar// /█}"
    leftbar="${leftbar// /░}"
    maxlabel=$((cols-12))
    (( maxlabel < 16 )) && maxlabel=16
    # Only completed installer milestones change the bar; real wall-clock time
    # is measured from the beginning, including package download.
    printf '\r\033[2K  %s%s%s%s%s  %3d%%\n' "$cyan" "$donebar" "$blue" "$leftbar" "$reset" "$pct"
    printf '\r\033[2K  %sЭтап: %s%s\n' "$ice" "${label:0:maxlabel}" "$reset"
    printf '\r\033[2K  %sПрошло: %02d:%02d:%02d%s' "$gray" "$((elapsed/3600))" "$(((elapsed%3600)/60))" "$((elapsed%60))" "$reset"
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
        printf '\033[3B\r\n'; error "Не удалось загрузить GitHub. Журнал: $LOG"
    fi
    INSTALL_PID=""
    SOURCE="$WORK/source"
fi
[[ -s "$SOURCE/install-final.sh" && -s "$SOURCE/node-install.sh" ]] || {
    printf '\033[3B\r\n'; error "Неполный пакет установщика. Журнал: $LOG"
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
    draw 100 'Установка завершена' "$((SECONDS-started))"
    printf '\033[3B\r\n'
    printf '\n%s  Проверки завершены. Журнал сохранён на VPS.%s\n' "$gray" "$reset"
    # The URL, login and password remain the very last content on screen.
    [[ -s "$RESULT" ]] || error "Нет итоговой карточки доступа. Проверьте журнал: $LOG"
    cat -- "$RESULT"
else
    printf '\033[3B\r\n%s  ✖ Установка прервана (код %d)%s\n' "$red" "$code" "$reset"
    hint="$(grep -Ei 'too many certificates|rateLimited|invalidContact|invalid_email|^ERROR:|^Ошибка|HTTPS.*не готов|failed|ошибка' "$LOG" | tail -n 1 || true)"
    [[ -z "$hint" ]] || printf '  %s\n' "$hint"
    printf '  Подробности: %s\n' "$LOG"
    printf '  Установку можно повторить, не очищая VPS.\n'
    exit "$code"
fi
