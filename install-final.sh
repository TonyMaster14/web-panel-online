#!/usr/bin/env bash
set -Eeuo pipefail
BASE="$(cd "$(dirname "$0")" && pwd)"
umask 077

WPP_PROGRESS_TTY=0 WPP_PROGRESS_ROWS=0 WPP_PROGRESS_LAST=-1 WPP_PROGRESS_ACTIVE=0
wpp_progress_start() {
    WPP_PROGRESS_ACTIVE=1
    if [[ -t 1 && "${TERM:-dumb}" != "dumb" ]] && command -v tput >/dev/null 2>&1; then
        WPP_PROGRESS_ROWS="$(tput lines 2>/dev/null || echo 0)"
        if (( WPP_PROGRESS_ROWS >= 6 )); then
            WPP_PROGRESS_TTY=1
            # Reserve the last row and move the command cursor back inside the
            # scrolling region.  Leaving it on the reserved row makes apt/curl
            # overwrite the progress bar on many SSH terminals.
            printf '\033[1;%dr\033[%d;1H' "$((WPP_PROGRESS_ROWS-1))" "$((WPP_PROGRESS_ROWS-1))"
        fi
    fi
    wpp_progress 0 "$1"
}
wpp_progress() {
    local percent="$1" label="$2" width=28 filled empty bar
    (( percent < 0 )) && percent=0; (( percent > 100 )) && percent=100
    filled=$((percent*width/100)); empty=$((width-filled))
    printf -v bar '%*s' "$filled" ''; bar="${bar// /#}"
    printf -v empty '%*s' "$empty" ''; bar+="${empty// /-}"
    if (( WPP_PROGRESS_TTY )); then
        printf '\0337\033[%d;1H\033[2K[%s] %3d%%  %s\0338' "$WPP_PROGRESS_ROWS" "$bar" "$percent" "$label"
    elif (( percent != WPP_PROGRESS_LAST )); then
        printf '[%s] %3d%%  %s\n' "$bar" "$percent" "$label"
    fi
    WPP_PROGRESS_LAST="$percent"
    if [[ -n "${WPO_UI_PROGRESS_FILE:-}" ]]; then
        printf '%s\t%s\n' "$percent" "$label" > "$WPO_UI_PROGRESS_FILE"
    fi
}
wpp_progress_finish() {
    local code="$1"
    (( WPP_PROGRESS_ACTIVE )) || return 0
    if (( code == 0 )); then wpp_progress 100 "Установка завершена"; else wpp_progress "$WPP_PROGRESS_LAST" "Установка прервана"; fi
    if (( WPP_PROGRESS_TTY )); then
        printf '\0337\033[%d;1H\033[2K\0338\033[r\033[%d;1H' "$WPP_PROGRESS_ROWS" "$WPP_PROGRESS_ROWS"
        printf '[############################] %3d%%  %s\n' "$([[ $code == 0 ]] && echo 100 || echo "$WPP_PROGRESS_LAST")" "$([[ $code == 0 ]] && echo 'Установка завершена' || echo 'Установка прервана')"
    fi
}

die() { echo "ERROR: $*" >&2; exit 1; }
for file in install-panel.sh install-webproxy-core.sh wpo-relay-zero-profiles-patch.py uninstall-web-proxy.sh update.sh panel-logo.svg THIRD-PARTY-NOTICES.md wpp_subscriptions.py wpp_panel_extras.py wpp_ui.py wpp_metrics.py wpp_update.py wpp_nodes.py wpp_openflux.py wpp_awg.py wpp_extra_protocols.py wpp_firewall.py wpp_components.py wpp_cdn.py wpp_cdn_doctor.py wpp_connections.py wpp_backup.py wpp_routing.py wpp_reality.py node-install.sh; do
    [[ -s "$BASE/$file" ]] || die "Package is incomplete: missing $file. Extract the complete archive."
done
for file in mtproxy-download.sh assets/mtproxy-bootstrap/proxy-secret assets/mtproxy-bootstrap/proxy-multi.conf; do
    [[ -s "$BASE/$file" ]] || die "Package is incomplete: missing $file. Extract the complete archive."
done
[[ -s "$BASE/assets/OpenFlux-linux-amd64" || -s "$BASE/OpenFlux-linux-amd64" ]] ||
    die "Package is incomplete: missing OpenFlux-linux-amd64. Extract the complete archive."
for file in amneziawg-go-linux-amd64 awg-linux-amd64 awg-quick-linux-amd64; do
    [[ -s "$BASE/assets/$file" ]] ||
        die "Package is incomplete: missing assets/$file. Extract the complete archive."
done
for file in caddy-forwardproxy-naive-v2.11.7-naive2.tar.xz mita-v3.39.0-linux-amd64.tar.gz mieru-v3.39.0-source.tar.gz; do
    [[ -s "$BASE/assets/$file" ]] || die "Package is incomplete: missing assets/$file. Extract the complete archive."
done
echo "434198ea0558bc440379e9a0a97f6904ba8dd6b213dd6fb9d578388eba7d2f12  $BASE/assets/mieru-v3.39.0-source.tar.gz" | sha256sum -c - >/dev/null ||
    die "Bundled Mieru source archive is damaged."
[[ -s "$BASE/assets/awg-routing-guide.mp4" ]] ||
    die "Package is incomplete: missing assets/awg-routing-guide.mp4. Extract the complete archive."
[[ -s "$BASE/wpp-panel/flags.tar.gz" ]] ||
    die "Package is incomplete: wpp-panel/flags.tar.gz is missing. Extract the complete archive."
command -v flock >/dev/null 2>&1 || die "flock is required (package: util-linux)."
exec 9>/run/lock/web-panel-proxy.lock
flock -n 9 || die "Another WEB PANEL ONLINE install, update or removal is already running."
cleanup_credentials() {
    if [[ -f /etc/web-proxy-panel/install-credentials ]]; then
        command -v shred >/dev/null 2>&1 && shred -u /etc/web-proxy-panel/install-credentials 2>/dev/null || \
            rm -f /etc/web-proxy-panel/install-credentials
    fi
}
# Show the panel URL LAST, after the progress bar and all node setup steps.
# Read the actual generated path from systemd; never guess the private URL.
wpp_print_final_panel_url() {
    local domain path
    domain="$(sed -n 's/^Environment=TPROXY_HOSTNAME=//p' /etc/systemd/system/caddy.service.d/tproxy.conf 2>/dev/null | head -n1 || true)"
    path="$(sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service 2>/dev/null | head -n1 || true)"
    printf '\n============================================================\n'
    printf '             WEB PANEL ONLINE 3.0 — ГОТОВО\n'
    printf '============================================================\n'
    if [[ "$domain" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && "$domain" == *.* &&
          "$path" =~ ^/panel-[a-z0-9-]{3,64}$ ]]; then
        printf 'Ссылка на панель (сохраните её):\n'
        printf 'https://%s%s/login\n' "$domain" "$path"
    else
        printf 'Не удалось прочитать адрес панели из systemd.\n'
        printf 'Выполните WPP → информация о панели для получения URL.\n'
    fi
}
finish_install() {
    local code=$?
    cleanup_credentials
    wpp_progress_finish "$code"
    # The last visible output is the full user access card, AFTER Nodes Lab
    # and progress finishing. The sensitive temporary card lives in /run.
    if (( code == 0 )); then
        if [[ -n "${WPO_UI_RESULT_FILE:-}" ]]; then
            if [[ -n "${WPO_FINAL_SUMMARY_FILE:-}" && -s "$WPO_FINAL_SUMMARY_FILE" ]]; then
                cat -- "$WPO_FINAL_SUMMARY_FILE" > "$WPO_UI_RESULT_FILE"
            else
                wpp_print_final_panel_url > "$WPO_UI_RESULT_FILE"
            fi
            chmod 0600 "$WPO_UI_RESULT_FILE"
        elif [[ -n "${WPO_FINAL_SUMMARY_FILE:-}" && -s "$WPO_FINAL_SUMMARY_FILE" ]]; then
            cat -- "$WPO_FINAL_SUMMARY_FILE" || true
        else
            wpp_print_final_panel_url
        fi
    fi
    if [[ -n "${WPO_FINAL_SUMMARY_FILE:-}" && -f "$WPO_FINAL_SUMMARY_FILE" ]]; then
        if command -v shred >/dev/null 2>&1; then
            shred -u -- "$WPO_FINAL_SUMMARY_FILE" 2>/dev/null || rm -f -- "$WPO_FINAL_SUMMARY_FILE"
        else
            rm -f -- "$WPO_FINAL_SUMMARY_FILE"
        fi
    fi
}
trap finish_install EXIT

wpp_progress_start "Проверка пакета"
WPO_INSTALL_CLOCK=$SECONDS
wpp_progress 5 "Подготовка сервера"

echo "WEB PANEL ONLINE V 3.0.0: preparing server..."

PANEL_UPDATE=0
if [[ -s /var/lib/tproxy-panel/data.json ]] &&
   [[ -f /etc/systemd/system/tproxy-panel.service ]] &&
   sed -n 's/^Environment=WEBPROXY_PANEL_PATH=//p' /etc/systemd/system/tproxy-panel.service |
       head -n1 | grep -Eq '^/panel-[a-z0-9-]{3,64}$'; then
    PANEL_UPDATE=1
    echo "Existing control panel detected; its users, password, address and site HTML will be preserved."
else
    echo "Installation/resume mode enabled. Existing compatible services will be reused and missing components installed."
fi

# Install the recovery command before making system changes so even an
# interrupted first installation can be cleaned up deterministically.
install -d -m 0700 /etc/web-proxy-panel
install -o root -g root -m 0755 \
    "$BASE/uninstall-web-proxy.sh" \
    /usr/local/sbin/web-panel-proxy-uninstall

echo "Installing proxy services..."
wpp_progress 10 "Установка прокси-служб"
WEB_PANEL_PROXY_PACKAGE_VERSION="3.0.0" bash "$BASE/install-webproxy-core.sh"
WPO_CORE_SECONDS=$((SECONDS-WPO_INSTALL_CLOCK))
echo "      ⏱ Прокси-службы: ${WPO_CORE_SECONDS} сек."
wpp_progress 55 "Прокси-службы установлены"

echo "Installing control panel..."
wpp_progress 60 "Установка панели"
# Keep the access card in root-only RAM until the whole installation succeeds.
# /run is normally tmpfs; remove it on both success and failure in EXIT trap.
WPO_FINAL_SUMMARY_FILE="$(mktemp /run/wpo-install-summary.XXXXXXXX)"
chmod 0600 "$WPO_FINAL_SUMMARY_FILE"
if [[ "$PANEL_UPDATE" == 1 ]]; then
    WEB_PANEL_PROXY_UPDATE=1 WPO_FINAL_SUMMARY_FILE="$WPO_FINAL_SUMMARY_FILE" bash "$BASE/install-panel.sh"
else
    WPO_FINAL_SUMMARY_FILE="$WPO_FINAL_SUMMARY_FILE" bash "$BASE/install-panel.sh"
fi
WPO_PANEL_SECONDS=$((SECONDS-WPO_INSTALL_CLOCK-WPO_CORE_SECONDS))
echo "      ⏱ Панель: ${WPO_PANEL_SECONDS} сек."
wpp_progress 92 "Проверка служб"

for unit in caddy.service mtproxy.service tproxy-server.service tproxy-panel.service web-proxy-panel-firewall.service; do
    systemctl is-active --quiet "$unit" || { echo "Installation failed: $unit did not start."; exit 1; }
done
systemctl is-enabled --quiet web-proxy-panel-firewall.service ||
    die "Persistent user firewall is not enabled."
nft list table inet web_proxy_panel >/dev/null 2>&1 ||
    die "Persistent user firewall table is missing."
nft list table ip web_proxy_awg >/dev/null 2>&1 ||
    die "AmneziaWG forwarding table is missing."
for file in /usr/local/bin/amneziawg-go /usr/local/bin/awg /usr/local/bin/awg-quick; do
    [[ -x "$file" ]] || die "AmneziaWG component was not installed: $file"
done
for file in /usr/local/bin/caddy-naive /usr/local/bin/mita-wpp; do
    [[ -x "$file" ]] || die "Additional proxy component was not installed: $file"
done
for file in /etc/systemd/system/web-panel-proxy-naive.service /etc/systemd/system/web-panel-proxy-mieru.service; do
    [[ -s "$file" ]] || die "Additional proxy service was not installed: $file"
done
[[ -s /etc/systemd/system/web-panel-proxy-awg@.service ]] ||
    die "AmneziaWG service template was not installed."
[[ -x /opt/web-panel-proxy/xray/xray ]] || die "Xray binary was not installed."
[[ -s /etc/web-panel-proxy-xray/config.json ]] || die "Xray configuration was not created."
[[ -x /usr/local/sbin/WPP ]] || die "WPP console menu was not installed."
systemctl is-active --quiet web-panel-proxy-sync-tls.timer ||
    die "The Xray TLS synchronization timer did not start."
echo "Checking the latest Xray and OpenFlux releases..."
wpp_progress 96 "Обновление Xray и OpenFlux"
flock -u 9
# Queue the component release check without waiting for every remote API.
# systemd's auto-update timer handles subsequent retry independently.
if ! systemctl start --no-block web-panel-proxy-component-auto-update.service; then
    echo "WARNING: Xray/OpenFlux update check could not be queued; the timer will retry." >&2
fi
# Consolidated node-install.sh contains the verified v1–v26 node feature set.
# Runs after base WPO 3.0 is healthy. This activates "Ноды → Добавить ноду"
# with the current Node Agent installer, auto-geolocation, status checks,
# random site templates and the final compact node cards, including pending installs.
wpp_progress 98 "Настройка раздела Ноды"
echo "Configuring node management..."
# Keep detailed patch output for diagnosis, but don't flood the console
# with internal v1..v26 patch names. The log is root-only.
NODES_SETUP_LOG="/var/log/web-panel-online/nodes-setup.log"
install -d -o root -g root -m 0700 /var/log/web-panel-online
: > "$NODES_SETUP_LOG"
chmod 0600 "$NODES_SETUP_LOG"
# Clean installs use predownloaded sources and one final restart.
# Updates retain conservative per-step checks and restarts.
if [[ "$PANEL_UPDATE" == 0 ]]; then
    if ! WPO_NODES_LOCAL_SOURCE=1 WPO_NODES_BATCH_RESTART=1 bash "$BASE/node-install.sh" >"$NODES_SETUP_LOG" 2>&1; then
        tail -n 80 "$NODES_SETUP_LOG" >&2 || true
        die "Ошибка настройки нод. Подробный журнал: $NODES_SETUP_LOG"
    fi
else
    if ! WPO_NODES_LOCAL_SOURCE=1 bash "$BASE/node-install.sh" >"$NODES_SETUP_LOG" 2>&1; then
        tail -n 80 "$NODES_SETUP_LOG" >&2 || true
        die "Ошибка обновления нод. Подробный журнал: $NODES_SETUP_LOG"
    fi
fi
echo "      ✓ Управление нодами настроено."

WPO_TOTAL_SECONDS=$((SECONDS-WPO_INSTALL_CLOCK))
WPO_NODES_SECONDS=$((WPO_TOTAL_SECONDS-WPO_CORE_SECONDS-WPO_PANEL_SECONDS))
echo "      ⏱ Ноды и финальные проверки: ${WPO_NODES_SECONDS} сек."
echo "      ⏱ Всего: ${WPO_TOTAL_SECONDS} сек. (без скачивания самого пакета GitHub)"
echo "WEB PANEL ONLINE 3.0: all services and node management are ready."
wpp_progress 100 "Установка завершена"
printf '%s\n' '3.0.0' > /etc/web-proxy-panel/version
chmod 0600 /etc/web-proxy-panel/version
