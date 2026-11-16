#!/usr/bin/env bash
# wpo-node-agent-eight-pinned-v1: eight actual engines, pinned backend source and live API readiness
# wpo-node-agent-reinstall-v23: restart agent after key rotation and explain enrollment failures
set -Eeuo pipefail
umask 077
# Never allow APT/dpkg or Ubuntu's needrestart to open an interactive
# kernel/service-restart dialog during the SSH wizard. It can otherwise wait
# indefinitely at the Caddy repository prerequisites, while the progress bar
# continues moving. The node's own systemd services are explicitly restarted
# later in the installer; an OS kernel reboot remains the operator's choice.
export DEBIAN_FRONTEND=noninteractive
export DEBIAN_PRIORITY=critical
export APT_LISTCHANGES_FRONTEND=none
export NEEDRESTART_SUSPEND=1
[[ $EUID -eq 0 ]] || { echo 'Запустите от root.'; exit 1; }
TOKEN="$1"
[[ "$TOKEN" =~ ^[A-Za-z0-9_-]{40,60}$ ]] || { echo 'Одноразовый ключ не передан.'; exit 2; }
# Reconcile interrupted installs before showing the SSH wizard or starting work.
# Full install marker is written only AFTER confirmed controller enrollment.
wpo_node_install_state() {
  python3 - "$1" <<'PY_WPO_NODE_STATE'
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

mode=sys.argv[1]
assert mode in ('check','cleanup')
agent_cfg=Path('/etc/wpp-node-agent/config.json')
units_dir=Path('/etc/systemd/system')
units={
    'wpp-node-agent.service','wpo-node-xray.service','wpo-node-vpn.service',
    'wpo-node-vpn-tls.service','wpo-node-vpn-tls.timer','wpo-node-relay.service',
    'wpo-node-awg-nat.service','wpo-node-mt-firewall.service','wpo-tls-router.service',
    'web-panel-proxy-awg@.service','web-panel-proxy-naive.service','web-panel-proxy-mieru.service',
}
owned=[Path(p) for p in (
    '/etc/wpp-node-agent','/opt/wpp-node-agent','/etc/wpp-node-vpn',
    '/var/www/wpp-node-site','/etc/tproxy-server','/etc/mtproxy',
    '/etc/web-proxy-panel/awg','/etc/web-proxy-panel/extra-protocols',
    '/etc/web-proxy-panel/reality','/opt/web-panel-proxy/xray','/opt/MTProxy',
    '/usr/local/bin/tproxy-server','/usr/local/bin/amneziawg-go',
    '/usr/local/bin/awg','/usr/local/bin/awg-quick','/usr/local/bin/caddy-naive',
    '/usr/local/bin/mita-wpp','/usr/local/sbin/web-panel-proxy-awg-run',
    '/usr/local/sbin/web-panel-proxy-awg-up','/usr/local/sbin/web-panel-proxy-awg-down',
    '/usr/local/sbin/wpo-node-awg-nat','/usr/local/sbin/wpo-node-mt-firewall',
    '/etc/sysctl.d/90-wpo-node-awg.conf',
)]

def command(*args):
    return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,check=False,timeout=30)

def active(name):
    return command('systemctl','is-active','--quiet',name).returncode==0

def refuse(reason):
    print('Очистка ноды остановлена: '+reason,file=sys.stderr)
    sys.exit(30)

# This installer is for a dedicated node; confirmation must never erase a panel.
if Path('/opt/tproxy-panel/panel.py').exists() or active('tproxy-panel.service'):
    refuse('на VPS установлена основная панель WPO.')
node_paths=[Path('/etc/wpp-node-agent'),Path('/opt/wpp-node-agent'),Path('/etc/wpp-node-vpn')]
exists=any(p.exists() or p.is_symlink() for p in node_paths)
exists=exists or any((units_dir/u).exists() for u in units) or active('wpp-node-agent.service')
if not exists:
    sys.exit(0)
if mode=='check':
    print('На VPS обнаружена установленная или незавершённая нода WPO.')
    sys.exit(20)
if os.environ.get('WPO_NODE_REINSTALL_APPROVED')!='1':
    refuse('переустановка не подтверждена ответом yes.')

# Enumerate instantiated AWG/MTProxy services, including enabled but stopped ones.
instance=re.compile(r'(?:web-panel-proxy-awg@[A-Za-z0-9_-]+|wpo-node-mtproxy-[A-Za-z0-9_-]+)\.service')
for verb in ('list-units','list-unit-files'):
    result=command('systemctl',verb,'--all','--plain','--no-legend','--no-pager')
    if result.returncode: refuse('не удалось получить список служб.')
    for line in result.stdout.splitlines():
        name=line.split()[0] if line.split() else ''
        if instance.fullmatch(name): units.add(name)
for p in units_dir.glob('wpo-node-mtproxy-*.service'):
    if instance.fullmatch(p.name):units.add(p.name)
# Guard all paths before stopping anything. Do not traverse unexpected parent links.
files=[units_dir/u for u in units]
files += [units_dir/(u+'.d') for u in units]
for p in owned+files+[Path('/etc/caddy/Caddyfile')]:
    if any(parent.is_symlink() for parent in p.parents):
        refuse('неожиданная ссылка в пути '+str(p))
    if p.is_symlink() and p in node_paths:
        refuse('неожиданная ссылка '+str(p))

print('Удаляю прежнюю ноду, пользователей, ключи и настройки...')
# Stop instances before removing the AWG helpers/configs used by ExecStopPost.
ordered=sorted(units,key=lambda u: (not bool(instance.fullmatch(u)),not u.endswith('.timer'),u))
for unit in ordered:
    if '@.service' in unit: continue
    command('systemctl','disable','--now',unit)
    if active(unit):refuse('не удалось остановить '+unit)

# Caddy/ACME packages and certificate cache are reusable system dependencies.
# Replace the node's serving configuration so old API/site routes disappear.
caddy=Path('/etc/caddy/Caddyfile')
if caddy.is_symlink():refuse('неожиданная ссылка Caddyfile.')
if caddy.exists():
    command('systemctl','stop','caddy.service')
    if active('caddy.service'):refuse('не удалось остановить Caddy.')
    caddy.write_text('{\n    admin off\n}\n',encoding='utf-8')
for family,table in (('inet','wpo_node_mt_guard'),('ip','wpo_node_awg_nat')):
    command('nft','delete','table',family,table)
for target in files+owned:
    if target.is_symlink() or target.is_file():target.unlink()
    elif target.is_dir():shutil.rmtree(target)
result=command('systemctl','daemon-reload')
if result.returncode:refuse('systemd не перечитал список служб.')
command('systemctl','reset-failed')
print('Прежняя нода удалена. Начинаю чистую установку.')
PY_WPO_NODE_STATE
}

# WPO_NODE_REINSTALL_GATE: prompt once in the foreground, before all writes.
# Only our wizard worker inherits the answer; ordinary invocations ask again.
if [[ "${WPO_NODE_WIZARD_WORKER:-0}" != 1 ]]; then
    unset WPO_NODE_REINSTALL_APPROVED
fi
wpo_node_previous=0
wpo_node_install_state check || wpo_node_previous=$?
case "$wpo_node_previous" in
  0) ;;
  20)
    if [[ "${WPO_NODE_REINSTALL_APPROVED:-0}" != 1 ]]; then
      printf 'Переустановка удалит пользователей, ключи, настройки и службы прежней ноды.\n'
      printf 'Старую карточку ноды удалите в панели самостоятельно.\n'
      [[ -t 0 ]] || { echo 'Для подтверждения yes/no запустите команду в SSH-терминале.' >&2; exit 30; }
      while true; do
        read -r -p 'Установить новую ноду? (yes/no): ' answer || exit 130
        case "$answer" in
          yes|YES|Yes) export WPO_NODE_REINSTALL_APPROVED=1; break ;;
          no|NO|No|'') echo 'Отмена: прежняя нода сохранена без изменений.'; exit 0 ;;
          *) echo 'Введите yes или no.' ;;
        esac
      done
    fi
    ;;
  *) exit "$wpo_node_previous" ;;
esac
# WPO_NODE_REINSTALL_GATE_END
# WPO_NODE_WIZARD_START: TTY shell around the unchanged Node Agent installer.
if [[ "${WPO_NODE_WIZARD_WORKER:-0}" != 1 && "${WPO_NODE_CLASSIC:-0}" != 1 && -t 0 && -t 1 ]]; then
  node_pid="" node_progress="" node_log=""
  node_tty_original=""
  node_cleanup(){
    if [[ -n "$node_pid" ]] && kill -0 "$node_pid" 2>/dev/null; then
      kill "$node_pid" 2>/dev/null || true
      wait "$node_pid" 2>/dev/null || true
    fi
    [[ -z "$node_progress" ]] || rm -f -- "$node_progress"
    # Restore the user's SSH terminal exactly as it was before the progress UI,
    # including input echo. Also runs after Ctrl+C and failure exits.
    if [[ -n "$node_tty_original" ]]; then
      stty "$node_tty_original" < /dev/tty 2>/dev/null || true
    fi
    printf '\033[0m\033[?25h'
    return 0
  }
  trap node_cleanup EXIT
  trap 'exit 130' INT TERM
  nblue=$'\033[38;5;75m'; ncyan=$'\033[38;5;51m'
  nice=$'\033[38;5;153m'; ngray=$'\033[38;5;245m'
  ngreen=$'\033[38;5;83m'; nred=$'\033[38;5;203m'
  nyellow=$'\033[1;38;5;226m'; nbold=$'\033[1m'; nreset=$'\033[0m'
  node_size(){
    local rows="" cols=""
    read -r rows cols < <(stty size </dev/tty 2>/dev/null) || true
    [[ "$cols" =~ ^[0-9]+$ ]] || cols=80
    (( cols >= 40 )) || cols=80
    ncols="$cols"
    nwidth=$((ncols-3))
    (( nwidth > 62 )) && nwidth=62
    printf -v nrule '%*s' "$nwidth" ''
    nrule="${nrule// /─}"
  }
  node_box(){
    local content="$1" color="$2" left right a b
    left=$(((nwidth-${#content})/2))
    right=$((nwidth-${#content}-left))
    printf -v a '%*s' "$left" ''
    printf -v b '%*s' "$right" ''
    printf '%s│%s%s%s%s%s│%s\n' "$nblue" "$color" "$a" "$content" "$b" "$nblue" "$nreset"
  }
  node_banner(){
    node_size
    printf '\n%s╭%s╮%s\n' "$nblue" "$nrule" "$nreset"
    node_box 'WEB PANEL ONLINE 3.0' "$nbold$nice"
    node_box 'УСТАНОВКА НОДЫ' "$nbold$ncyan"
    printf '%s╰%s╯%s\n' "$nblue" "$nrule" "$nreset"
  }
  node_commands(){
    # Give Enter and q equal visual weight on either side of the divider.
    local ltext='ENTER — установить' rtext='q — выход'
    local lw rw
    lw=$(((nwidth-1)/2))
    rw=$((nwidth-1-lw))
    local la=$(((lw-${#ltext})/2)) lb ra rb
    lb=$((lw-${#ltext}-la))
    ra=$(((rw-${#rtext})/2))
    rb=$((rw-${#rtext}-ra))
    local lp le rp re
    printf -v lp '%*s' "$la" ''
    printf -v le '%*s' "$lb" ''
    printf -v rp '%*s' "$ra" ''
    printf -v re '%*s' "$rb" ''
    printf '%s│%s%s%s%s%s│%s%s%s%s%s│%s\n' \
      "$nblue" "$nbold$ncyan" "$lp" "$ltext" "$le" "$nblue" \
      "$nbold$ncyan" "$rp" "$rtext" "$re" "$nblue" "$nreset"
  }
  printf '\033[2J\033[H'
  node_banner
  # Center the welcome line against the same 62-column frame.
  node_welcome='Добро пожаловать в установку ноды!'
  printf -v node_welcome_pad '%*s' "$(((nwidth+2-${#node_welcome})/2))" ''
  printf '\n%s%s%s%s\n' "$node_welcome_pad" "$ncyan" "$node_welcome" "$nreset"
  printf '%s╭%s╮%s\n' "$nblue" "$nrule" "$nreset"
  node_commands
  printf '%s╰%s╯%s\n' "$nblue" "$nrule" "$nreset"
  while true; do
    printf '  '
    read -r choice || exit 130
    [[ "$choice" != q && "$choice" != Q ]] || exit 0
    [[ -z "$choice" ]] && break
    printf '%s  Нажмите Enter или q для выхода.%s\n' "$ngray" "$nreset"
  done
  while true; do
    printf '\n  %sДомен ноды:%s ' "$ncyan" "$nreset"
    read -r DOMAIN || exit 130
    DOMAIN="$(printf '%s' "$DOMAIN" | sed -E 's#^https?://##; s#/.*$##' | tr '[:upper:]' '[:lower:]')"
    [[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] && break
    printf '%s  Укажите действительный домен.%s\n' "$ngray" "$nreset"
  done
  while true; do
    printf '\n  %sEmail для HTTPS:%s ' "$ncyan" "$nreset"
    IFS= read -r EMAIL || exit 130
    [[ "$EMAIL" =~ ^[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$ ]] && break
    printf '%s  Укажите email латиницей.%s\n' "$ngray" "$nreset"
  done
  install -d -m 0700 /var/log/web-panel-online
  node_log="/var/log/web-panel-online/node-install-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
  (umask 077; : > "$node_log")
  node_progress="$(mktemp /run/wpo-node-progress.XXXXXXXX)"
  chmod 0600 "$node_progress"
  printf '1\tПодготовка\n' > "$node_progress"
  node_confirmed=1 node_percent=1 node_started=$SECONDS
  node_last_move_us="${EPOCHREALTIME/./}"
  node_last_drawn=''
  node_draw(){
    local percent="$1" elapsed="$2" width full rest a b current
    # A 0.2-second poll should not repaint the same timer/progress frame 5x.
    current="$percent:$elapsed"
    [[ "$current" != "$node_last_drawn" ]] || return 0
    node_last_drawn="$current"
    node_size
    width=$((ncols-24))
    (( width > 40 )) && width=40
    (( width < 8 )) && width=8
    full=$((percent*width/100))
    rest=$((width-full))
    printf -v a '%*s' "$full" ''
    printf -v b '%*s' "$rest" ''
    a="${a// /█}"; b="${b// /░}"
    printf '\r\033[2K  %s%s%s%s%s  %3d%%  %s%02d:%02d:%02d%s' \
      "$ncyan" "$a" "$nblue" "$b" "$nreset" "$percent" \
      "$nice" "$((elapsed/3600))" "$(((elapsed%3600)/60))" "$((elapsed%60))" "$nreset"
  }
  node_tick(){
    local elapsed="$((SECONDS-node_started))" milestone="" detail=""
    local ceiling interval now_us
    if IFS=$'\t' read -r milestone detail < "$node_progress"; then
      if [[ "$milestone" =~ ^[0-9]+$ ]] &&
         (( milestone > node_confirmed && milestone <= 98 )); then
        node_confirmed="$milestone"
        printf '[WPO node timing] +%ds milestone=%d %s\n' \
          "$elapsed" "$node_confirmed" "$detail" >> "$node_log"
      fi
    fi
    # Never jump to a backend milestone in one frame. A stage may only fill
    # the band BEFORE the next stage; 100% means real enrollment success.
    # The 0.2s terminal poll shows at most one additional percent per frame.
    case "$node_confirmed" in
      1) ceiling=3 ;;
      4) ceiling=15 ;;
      16) ceiling=37 ;;
      38) ceiling=51 ;;
      52) ceiling=67 ;;
      68) ceiling=83 ;;
      84) ceiling=93 ;;
      94) ceiling=97 ;;
      98) ceiling=99 ;;
      *) ceiling="$node_confirmed" ;;
    esac
    now_us="${EPOCHREALTIME/./}"
    # Catch up gently if work completed faster than the display; otherwise
    # move at around 1.5% per second while the current stage is running.
    if (( node_percent < node_confirmed )); then
      interval=180000
    else
      interval=650000
    fi
    if (( node_percent < ceiling &&
          now_us - node_last_move_us >= interval )); then
      node_percent=$((node_percent+1))
      node_last_move_us="$now_us"
    fi
    node_draw "$node_percent" "$elapsed"
  }
  # Domain and email were already entered above; don't duplicate them.
  # Keep one empty line between the email prompt and installation status.
  printf '\n  %sУСТАНОВКА НОДЫ …%s\n\n' "$nbold$ngreen" "$nreset"
  # Pressing Enter while the installer runs is NOT another command. Disable
  # terminal echo during the progress bar so CR/LF cannot push it down and
  # leave a duplicate line on screen. Keep normal Ctrl+C signal handling.
  node_tty_original="$(stty -g < /dev/tty 2>/dev/null || true)"
  [[ -z "$node_tty_original" ]] || stty -echo < /dev/tty
  printf '\033[?25l'
  # Feed the original noninteractive worker the exact inputs entered above.
  # Enrollment/token/API and all protocol installation paths are unchanged.
  ( printf '%s\n%s\n' "$DOMAIN" "$EMAIL" |
      WPO_NODE_WIZARD_WORKER=1 WPO_NODE_PROGRESS_FILE="$node_progress" \
      bash "${BASH_SOURCE[0]}" "$TOKEN" ) >> "$node_log" 2>&1 &
  node_pid=$!
  while kill -0 "$node_pid" 2>/dev/null; do
    node_tick
    sleep 0.2
  done
  status=0
  wait "$node_pid" || status=$?
  node_pid=""
  node_tick
  if (( status != 0 )); then
    printf '\n%s  ✖ Установка ноды прервана (код %d)%s\n' "$nred" "$status" "$nreset"
    # Show the actual cause for common APT/DNS/curl/certificate failures.
    # Never print the full installer log here (it can contain sensitive data).
    hint="$(grep -E '^(ERROR:|Ошибка|E: |Err:|curl: \(|HTTPS не готов|Node Agent не готов|Регистрация:|DNS A-запись|Некорректный домен|Email не введён|Проверьте email|Не удалось|Требуется Ubuntu|Требуется Debian)' "$node_log" | tail -n 1 || true)"
    if [[ -n "$hint" ]]; then
      printf '  %s\n' "$hint"
    else
      printf '  Причина записана в журнале. Посмотрите последние строки.\n'
    fi
    printf '  Подробности: %s\n' "$node_log"
    exit "$status"
  fi
  # Worker has exited with code 0: only now may the bar reach 100%.
  # Smooth the last few frames without adding an artificial two-second hold.
  while (( node_percent < 100 )); do
    node_percent=$((node_percent+1))
    node_draw "$node_percent" "$((SECONDS-node_started))"
    (( node_percent == 100 )) || sleep 0.012
  done
  printf '\033[2J\033[H'
  node_banner
  printf '\n%s╭%s╮%s\n' "$nblue" "$nrule" "$nreset"
  node_box 'НОДА УСТАНОВЛЕНА' "$nyellow"
  printf '%s╰%s╯%s\n' "$nblue" "$nrule" "$nreset"
  printf '\n  %sДомен: %s%s\n' "$ncyan" "$DOMAIN" "$nreset"
  printf '  %sНода успешно зарегистрирована в WPO.%s\n' "$ngreen" "$nreset"
  printf '  %sВремя: %02d:%02d:%02d%s\n' "$nice" \
    "$(((SECONDS-node_started)/3600))" "$((((SECONDS-node_started)%3600)/60))" \
    "$(((SECONDS-node_started)%60))" "$nreset"
  exit 0
fi
# WPO_NODE_WIZARD_END
ENROLL_URL="__WPO_CONTROLLER_ENROLL_URL__"
STATUS_URL="__WPO_CONTROLLER_STATUS_URL__"
DOMAIN=""
EMAIL=""
report() {
  local current_domain="$DOMAIN"
  if [[ -n "${WPO_NODE_PROGRESS_FILE:-}" && -f "$WPO_NODE_PROGRESS_FILE" ]]; then
    local milestone=0
    case "$1:$2" in
      "installing:Проверка VPS"*) milestone=4 ;;
      "installing:Установка Caddy"*) milestone=16 ;;
      "installing:Ожидание HTTPS"*) milestone=38 ;;
      "installing:Активация VPN"*) milestone=52 ;;
      "installing:Установка всех 8"*) milestone=68 ;;
      "installing:Проверка создания"*) milestone=84 ;;
      "registration:"*) milestone=94 ;;
    esac
    (( milestone == 0 )) || printf '%s\t%s\n' "$milestone" "$2" > "$WPO_NODE_PROGRESS_FILE"
  fi
  if [[ $# -ge 3 && -n "$3" ]]; then current_domain="$3"; fi
  python3 - "$TOKEN" "$1" "$2" "$current_domain" <<'PY_STATUS' | curl -fsS --connect-timeout 2 --max-time 4 -H 'Content-Type: application/json' --data-binary @- "$STATUS_URL" >/dev/null 2>&1 || true
import json,sys
print(json.dumps({'token':sys.argv[1],'status':sys.argv[2],'detail':sys.argv[3],'domain':sys.argv[4]}))
PY_STATUS
}
fail() {
  rc=$?
  trap - ERR
  report error "Установщик завершился с ошибкой (код $rc)."
  echo "Установка завершилась с ошибкой ($rc)."
  exit "$rc"
}
trap fail ERR
# Do not enter provisioning while Ubuntu is already unpacking its own
# security updates. fuser checks real file users; pgrep covers minimal
# images where psmisc/fuser has not been installed.
if { command -v fuser >/dev/null 2>&1 && fuser -s /var/lib/dpkg/lock-frontend; } ||
   { command -v pgrep >/dev/null 2>&1 && pgrep -x 'apt-get|dpkg' >/dev/null 2>&1; }; then
  echo 'Ubuntu сейчас обновляет системные пакеты (apt/dpkg занят).' >&2
  echo 'Не удаляйте блокировку и не запускайте установщик параллельно.' >&2
  echo 'Проверьте завершение обновления и повторно создайте установщик в WPO.' >&2
  report error 'Менеджер пакетов занят обновлением Ubuntu; установка не начиналась.'
  exit 75
fi
report installing 'Проверка VPS и домена.'
echo '=== WEB PANEL ONLINE — Node Agent 0.4 · 8 протоколов ==='
read -r -p 'Домен ноды (например, de.example.com): ' DOMAIN
DOMAIN=$(printf '%s' "$DOMAIN" | sed -E 's#^https?://##; s#/.*$##' | tr '[:upper:]' '[:lower:]')
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || { report error 'Некорректный домен.'; echo 'Некорректный домен.'; exit 2; }
# Email is required for Let's Encrypt. Fix accidental non-ASCII paste
# characters at the edges, but never silently modify the middle of an address.
for EMAIL_ATTEMPT in 1 2 3; do
  if ! IFS= read -r -p "Email для Let's Encrypt (латиница, EN): " EMAIL; then
    report error 'Email не введён.'
    echo 'Email не введён. Установка остановлена.'
    exit 2
  fi
  if VALIDATED_EMAIL="$(python3 - "$EMAIL" <<'PY_VALIDATE_EMAIL'
import re
import sys

original = sys.argv[1]
value = original.strip(" \t\r\n\ufeff\u200b\u2060")
while value and not value[0].isascii():
    value = value[1:]
while value and not value[-1].isascii():
    value = value[:-1]
local, sep, host = value.partition("@")
local_ok = (
    1 <= len(local) <= 64
    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*", local) is not None
    and not local.endswith(".")
    and ".." not in local
)
host_ok = re.fullmatch(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}",
    host,
) is not None
if value.isascii() and len(value) <= 254 and sep and local_ok and host_ok:
    if value != original:
        print("Убраны случайные символы по краям email.", file=sys.stderr)
    print(value)
else:
    print("Проверьте email: только латинские буквы, без лишних символов.", file=sys.stderr)
    sys.exit(1)
PY_VALIDATE_EMAIL
)"; then
    EMAIL="$VALIDATED_EMAIL"
    break
  fi
  if [[ "$EMAIL_ATTEMPT" == "3" ]]; then
    report error 'Email указан некорректно после трёх попыток.'
    echo 'Установка остановлена: неверный email.'
    exit 2
  fi
  echo 'Повторите ввод email в английской раскладке.'
done
. /etc/os-release
case "$ID" in
  ubuntu) dpkg --compare-versions "$VERSION_ID" ge 22.04 || { echo 'Требуется Ubuntu 22.04+.'; exit 2; } ;;
  debian) dpkg --compare-versions "$VERSION_ID" ge 12 || { echo 'Требуется Debian 12+.'; exit 2; } ;;
  *) echo 'Поддерживаются Ubuntu 22.04+ и Debian 12+.'; exit 2 ;;
esac
# Clean the confirmed previous node only after domain/email and OS validation.
wpo_node_install_state cleanup
report installing 'Установка Caddy и подготовка сайта ноды.'
# On some fresh Ubuntu images unattended upgrades have ALREADY refreshed APT.
# Repeating apt-get update may consume most of a one-minute installation.
# Only trust a recent, complete distro index; a failed cached install retries
# after a fresh update. APT signature validation and package checks stay intact.
wpo_node_apt_cache_recent(){
  local lists=/var/lib/apt/lists
  [[ "${WPO_NODE_FORCE_APT_UPDATE:-0}" != 1 ]] || return 1
  [[ -d "$lists" ]] || return 1
  [[ -n "$(find "$lists" -maxdepth 1 -type f -name '*_InRelease' -mmin -180 -print -quit)" ]] || return 1
  [[ -n "$(find "$lists" -maxdepth 1 -type f -name '*_Packages*' -print -quit)" ]] || return 1
  apt-cache show curl >/dev/null 2>&1 &&
  apt-cache show python3 >/dev/null 2>&1 &&
  apt-cache show wireguard-tools >/dev/null 2>&1
}
wpo_node_prep_started=$SECONDS
wpo_node_cached_apt=0
if wpo_node_apt_cache_recent; then
  wpo_node_cached_apt=1
  echo '[WPO node timing] apt-index: reused validated recent metadata'
else
  apt-get update
  echo "[WPO node timing] apt-index: refreshed in $((SECONDS-wpo_node_prep_started))s"
fi
# One transaction: common prerequisites + distro Caddy (when available).
# This avoids two dpkg/needrestart transactions on Ubuntu 24.04.
wpo_node_packages=(
  curl ca-certificates gnupg python3 unzip openssl util-linux xz-utils tar
  nftables iproute2 wireguard-tools procps
)
wpo_node_caddy_distro=0
if ! command -v caddy >/dev/null 2>&1 &&
   apt-cache show caddy >/dev/null 2>&1; then
  wpo_node_packages+=(caddy)
  wpo_node_caddy_distro=1
fi
wpo_node_apt_started=$SECONDS
if ! apt-get install -y --no-install-recommends "${wpo_node_packages[@]}"; then
  if (( wpo_node_cached_apt != 1 )); then
    echo 'APT install failed after fresh update.' >&2
    exit 4
  fi
  # The mirror may have rotated .deb files since the cached index was made.
  echo 'APT cache was stale; refreshing index and retrying packages.' >&2
  apt-get update
  apt-get install -y --no-install-recommends "${wpo_node_packages[@]}"
fi
echo "[WPO node timing] packages: $((SECONDS-wpo_node_apt_started))s (distro-caddy=$wpo_node_caddy_distro)"
if ! command -v caddy >/dev/null 2>&1; then
  # Cloudsmith fallback is needed only where the distro has no Caddy.
  wpo_node_caddy_started=$SECONDS
  if [[ "$ID" == debian ]]; then
    apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https
  fi
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y --no-install-recommends caddy
  echo "[WPO node timing] caddy-external: $((SECONDS-wpo_node_caddy_started))s"
fi
echo "[WPO node timing] preparation-total: $((SECONDS-wpo_node_prep_started))s"
PUBLIC_IP="$(curl -4fsS --max-time 10 https://api.ipify.org)"
getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | grep -Fxq "$PUBLIC_IP" || { report error "DNS A-запись должна указывать на $PUBLIC_IP."; echo "DNS A-запись $DOMAIN должна указывать на $PUBLIC_IP."; exit 3; }
install -d -m 0755 /opt/wpp-node-agent /var/www/wpp-node-site
install -d -m 0700 /etc/wpp-node-agent
API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 - "$DOMAIN" "$EMAIL" "$API_KEY" <<'PY_CFG'
import json,os,sys,tempfile
p='/etc/wpp-node-agent/config.json'
d={'domain':sys.argv[1],'email':sys.argv[2],'api_key':sys.argv[3],'version':'0.2.0'}
fd,t=tempfile.mkstemp(dir=os.path.dirname(p))
with os.fdopen(fd,'w',encoding='utf-8') as f:
    json.dump(d,f); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.chmod(t,0o600); os.replace(t,p)
PY_CFG
cat > /opt/wpp-node-agent/agent.py <<'PY_AGENT'
#!/usr/bin/env python3
import base64
import binascii
import hmac
import json
import os
import re
import tempfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
CONFIG='/etc/wpp-node-agent/config.json'
SITE='/var/www/wpp-node-site'
C=json.load(open(CONFIG,encoding='utf-8'))
KEY=C['api_key']
DOMAIN=C['domain']
DEFAULT_HTML='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0c111b"><title>Сервер работает</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 80% 10%,#24304b,#0c111b 52%);color:#eef3ff;font:15px system-ui,sans-serif}.box{width:min(520px,calc(100% - 36px));padding:36px;border:1px solid #ffffff1c;border-radius:24px;background:#111a2bcc;box-shadow:0 25px 80px #0007}.dot{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:50%;background:#36d399;box-shadow:0 0 18px #36d399}h1{margin:18px 0 8px;font-size:30px}p{margin:0;color:#aab7ce;line-height:1.65}.tag{color:#8fa4c6;font-size:11px;letter-spacing:.14em;text-transform:uppercase}</style></head><body><main class="box"><span class="dot"></span><span class="tag">Node Agent online</span><h1>Сервер работает</h1><p>Подключение ноды активно. Владелец панели может назначить этой ноде шаблон сайта.</p></main></body></html>'''
ASSET_RE=re.compile(r'^preset-[A-Za-z0-9_.-]{1,110}\.webp$',re.I)
def location():
    try:
        import urllib.request
        with urllib.request.urlopen('https://ipapi.co/json/',timeout=4) as r:
            d=json.loads(r.read(65536))
        code=str(d.get('country_code','UN')).upper()
        if not re.fullmatch(r'[A-Z]{2}',code): code='UN'
        return {'country_code':code,'country_name':str(d.get('country_name') or 'Сервер')[:80],'name':str(d.get('country_name') or 'Сервер')[:80]}
    except Exception:
        return {'country_code':'UN','country_name':'Сервер','name':'Сервер'}
def atomic_write(path,data,mode=0o644):
    fd,tmp=tempfile.mkstemp(prefix='.wpo-site-',dir=os.path.dirname(path))
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(tmp,mode); os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
def save_config():
    tmp=CONFIG+'.tmp'
    with open(tmp,'w',encoding='utf-8') as stream:
        json.dump(C,stream,ensure_ascii=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    os.chmod(tmp,0o600); os.replace(tmp,CONFIG)
class H(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def out(self,data,code=200):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def auth(self):
        h=self.headers.get('Authorization','')
        return h.startswith('Bearer ') and hmac.compare_digest(h[7:].strip(),KEY)
    def do_GET(self):
        if self.path=='/healthz':
            self.out({'ok':True}); return
        if not self.auth():
            self.out({'ok':False,'message':'Unauthorized'},401); return
        if self.path=='/wpp-api/v1/status':
            self.out({'ok':True,'api_version':1,'version':C['version'],'domain':DOMAIN,
                      'location':location(),'name':DOMAIN.split('.')[0],
                      'capabilities':['node-agent','site-template']}); return
        if self.path=='/wpp-api/v1/profiles':
            self.out({'ok':True,'profiles':[]}); return
        self.out({'ok':False,'message':'Not found'},404)
    def do_POST(self):
        if not self.auth():
            self.out({'ok':False,'message':'Unauthorized'},401); return
        if self.path=='/wpp-api/v1/site-template':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>12000000:
                    self.out({'ok':False,'message':'Размер шаблона превышает лимит 12 МБ.'},413); return
                data=json.loads(self.rfile.read(length).decode('utf-8'))
                template_id=str(data.get('template_id',''))
                if template_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',template_id):
                    self.out({'ok':False,'message':'Некорректный ID шаблона.'},400); return
                page=data.get('html','')
                if not isinstance(page,str) or len(page.encode('utf-8'))>2100000:
                    self.out({'ok':False,'message':'HTML шаблона слишком большой или некорректный.'},413); return
                assets=data.get('assets',[])
                if not isinstance(assets,list) or len(assets)>20:
                    self.out({'ok':False,'message':'Некорректный список ресурсов.'},400); return
                written=[]
                total=0
                for item in assets:
                    if not isinstance(item,dict): continue
                    name=str(item.get('name',''))
                    encoded=str(item.get('data',''))
                    if not ASSET_RE.fullmatch(name): continue
                    try: raw=base64.b64decode(encoded,validate=True)
                    except (binascii.Error,ValueError): continue
                    if len(raw)>2000000 or total+len(raw)>6500000:
                        self.out({'ok':False,'message':'Ресурсы шаблона превышают лимит 6.5 МБ.'},413); return
                    atomic_write(os.path.join(SITE,name),raw)
                    total+=len(raw); written.append(name)
                for name in os.listdir(SITE):
                    if name.startswith('preset-') and ASSET_RE.fullmatch(name) and name not in written:
                        try: os.unlink(os.path.join(SITE,name))
                        except OSError: pass
                if page:
                    atomic_write(os.path.join(SITE,'index.html'),page.encode('utf-8'))
                    C['site_template_id']=template_id
                else:
                    atomic_write(os.path.join(SITE,'index.html'),DEFAULT_HTML.encode('utf-8'))
                    C.pop('site_template_id',None)
                save_config()
                self.out({'ok':True,'template_id':template_id,'assets':len(written)})
            except (ValueError,TypeError,UnicodeError,OSError,json.JSONDecodeError):
                self.out({'ok':False,'message':'Не удалось сохранить шаблон сайта на ноде.'},400)
            return
        if self.path.endswith('/federation/purge'):
            self.out({'ok':True,'deleted':0}); return
        if self.path.endswith('/federation/delete'):
            self.out({'ok':True,'deleted':False}); return
        if self.path.endswith('/federation/sync'):
            self.out({'ok':False,'message':'VPN services are not installed in Node Agent Lab.'},501); return
        self.out({'ok':False,'message':'Not found'},404)
os.makedirs(SITE,mode=0o755,exist_ok=True)
if not os.path.exists(os.path.join(SITE,'index.html')):
    atomic_write(os.path.join(SITE,'index.html'),DEFAULT_HTML.encode('utf-8'))
ThreadingHTTPServer(('127.0.0.1',9088),H).serve_forever()
PY_AGENT
chmod 0755 /opt/wpp-node-agent/agent.py
cat > /etc/systemd/system/wpp-node-agent.service <<'UNIT'
[Unit]
Description=WPO lightweight Node Agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
Group=root
UMask=0077
ExecStart=/usr/bin/python3 /opt/wpp-node-agent/agent.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/log /var/www/wpp-node-site /etc/wpp-node-agent
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    tls $EMAIL
    encode zstd gzip
    handle /wpp-api/* {
        reverse_proxy 127.0.0.1:9088
    }
    handle /healthz {
        reverse_proxy 127.0.0.1:9088
    }
    handle {
        root * /var/www/wpp-node-site
        try_files {path} /index.html
        file_server
    }
}
CADDY
if systemctl is-active --quiet wpo-tls-router && [[ -s /opt/wpp-node-agent/wpo_reality.py ]]; then
    PYTHONPATH=/opt/wpp-node-agent python3 - <<'PY_KEEP_REALITY'
from pathlib import Path
import wpo_reality
p=Path('/etc/caddy/Caddyfile')
p.write_text(wpo_reality.caddy_internal(p.read_text()))
PY_KEEP_REALITY
fi
chmod 0644 /etc/caddy/Caddyfile
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then
  ufw allow 80/tcp >/dev/null || true
  ufw allow 443/tcp >/dev/null || true
fi
systemctl daemon-reload
# A reinstall rotates the API key. --now alone leaves an already running agent
# with the OLD key in memory; restart ensures the current config is loaded.
systemctl enable wpp-node-agent.service
systemctl restart wpp-node-agent.service
systemctl is-active --quiet wpp-node-agent.service || { echo 'Не удалось перезапустить Node Agent.'; exit 4; }
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy
report installing 'Ожидание HTTPS-сертификата.'
TLS_OK=0
for i in $(seq 1 180); do
  if curl -fsS --connect-timeout 2 --max-time 4 "https://$DOMAIN/healthz" >/dev/null 2>&1; then TLS_OK=1; break; fi
  sleep 1
done
[[ "$TLS_OK" == "1" ]] || { report error 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; echo 'HTTPS не готов. Проверьте DNS и доступность TCP 80/443.'; exit 4; }
# Check the AUTHENTICATED agent status, not just public /healthz.
# This catches a stale agent key before controller registration.
if ! curl -4fsS --connect-timeout 4 --max-time 12 \
    -H "Authorization: Bearer $API_KEY" \
    "https://$DOMAIN/wpp-api/v1/status" >/dev/null; then
  report error 'Node Agent не принимает новый ключ API. Проверьте перезапуск службы.'
  echo 'Node Agent не принимает новый ключ API (проверьте systemctl status wpp-node-agent.service).'
  exit 4
fi
# Recover only an orphaned VPN configuration from an interrupted install.
# Never overwrite an active node or one containing real subscriber profiles.
# The pinned VPN bootstrap rejects settings.json with another domain; it
# cannot distinguish a half-installed VPS from an operating server by itself.
python3 - "$DOMAIN" <<'PY_NODE_STALE_DOMAIN'
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

domain=sys.argv[1]
root=Path('/etc/wpp-node-vpn')
settings=root/'settings.json'
if settings.exists():
    try:
        saved=json.loads(settings.read_text(encoding='utf-8'))
        previous=saved['domain']
        if not isinstance(previous,str) or not previous:
            raise ValueError('empty prior domain')
    except (OSError,ValueError,TypeError,KeyError) as exc:
        raise SystemExit('Previous node VPN settings are unreadable; refusing to overwrite them.') from exc
    if previous != domain:
        def running(unit):
            return subprocess.run(
                ['systemctl','is-active','--quiet',unit],check=False,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            ).returncode == 0
        if any(running(u) for u in ('wpo-node-xray.service','wpo-node-vpn.service')):
            raise SystemExit(
                'Node VPN domain mismatch: active VPN service belongs to '+previous+
                '. Keep that node intact; use a separate VPS for '+domain+'.'
            )
        profiles=root/'profiles.json'
        if profiles.exists():
            try:
                state=json.loads(profiles.read_text(encoding='utf-8'))
                entries=state['profiles']
                if not isinstance(entries,dict) or entries:
                    raise ValueError('profiles are present or malformed')
            except (OSError,ValueError,TypeError,KeyError) as exc:
                raise SystemExit(
                    'Node VPN domain mismatch: existing profile data must be preserved; '
                    'refusing automatic recovery.'
                ) from exc
        suffix=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        archive=root/('orphaned-domain-backup-'+suffix+'-'+str(os.getpid()))
        archive.mkdir(mode=0o700)
        shutil.copy2(settings,archive/'settings.json')
        os.chmod(archive/'settings.json',0o600)
        # The pinned VPN bootstrap will create a new XHTTP path for the
        # current domain. No client profiles or running services are touched.
        settings.unlink()
        print('Old incomplete VPN domain',previous,
              'archived to',str(archive)+'. New domain:',domain)
PY_NODE_STALE_DOMAIN

# Pin backend scripts and their imported modules to one reviewed Git commit.
# Avoid moving branch references during long multi-engine installation.
# Includes native_changed, writable backend paths, and readable Xray rollback.
ENGINE_REV=007c4c1cddc86c900b841c1c0360127eb94c03d7
# Test-only VPN capability is installed before enrollment. Registration
# is blocked on failure: controller must never see a "ready" VPN node without
# working local Xray and authenticated federation API.
report installing 'Активация VPN ноды: VLESS XHTTP и Hysteria2.'
VPN_SETUP="$(mktemp /tmp/wpo-node-vpn-enable.XXXXXXXX.sh)"
trap fail ERR
trap 'rm -f -- "$VPN_SETUP"' EXIT
curl -4fsSL --proto '=https' --proto-redir '=https' \
    --retry 3 --connect-timeout 15 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/${ENGINE_REV}/wpo-node-vpn-enable.sh" \
    -o "$VPN_SETUP"
bash -n "$VPN_SETUP"
# This pinned VPN setup makes only six one-second checks for the localhost
# federation API after systemd starts it. A service may need longer to bind
# 127.0.0.1:9089; if it crashes, emit systemd logs instead of bare curl (7).
python3 - "$VPN_SETUP" <<'PY_WPO_VPN_9089_READY'
from pathlib import Path
import sys

path=Path(sys.argv[1])
source=path.read_text(encoding='utf-8')
old="""ok=0
for _ in 1 2 3 4 5 6; do
    if curl -4fsS --max-time 3 http://127.0.0.1:9089/healthz |
        grep -q '"ok": true'; then ok=1; break; fi
    sleep 1
done
(( ok == 1 )) || { echo 'VPN health check failed' >&2; exit 3; }"""
new="""ok=0
for attempt in $(seq 1 30); do
    if systemctl is-active --quiet wpo-node-vpn.service &&
       curl -4fs --noproxy '*' --connect-timeout 1 --max-time 3 \
           http://127.0.0.1:9089/healthz 2>/dev/null |
           grep -q '"ok": true'; then
        ok=1
        break
    fi
    sleep 1
done
if (( ok != 1 )); then
    echo 'VPN API 127.0.0.1:9089 did not become ready. Service diagnostics:' >&2
    systemctl status wpo-node-vpn.service --no-pager -l >&2 || true
    journalctl -u wpo-node-vpn.service --no-pager -n 40 >&2 || true
    exit 4
fi"""
if source.count(old)!=1:
    raise SystemExit('Pinned VPN readiness code changed; refusing unverified patch.')
path.write_text(source.replace(old,new,1),encoding='utf-8')
PY_WPO_VPN_9089_READY
bash -n "$VPN_SETUP"
WPO_NODE_VPN_REF="$ENGINE_REV" bash "$VPN_SETUP"
rm -f -- "$VPN_SETUP"
trap fail ERR
# All eight server engines are mandatory: do NOT enroll a partly provisioned
# node. Install MTProxy/WEB relay, AWG 2/3, Naive and Mieru automatically.
report installing 'Установка всех 8 VPN-протоколов на ноду.'
EIGHT_SETUP="$(mktemp /tmp/wpo-node-eight.XXXXXXXX.sh)"
trap 'rm -f -- "${EIGHT_SETUP:-}" "${VPN_SETUP:-}"' EXIT
curl -4fsSL --proto '=https' --proto-redir '=https' \
    --retry 3 --connect-timeout 15 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/${ENGINE_REV}/wpo-node-eight-enable.sh" \
    -o "$EIGHT_SETUP"
bash -n "$EIGHT_SETUP"
# The pinned Node Agent 0.4 engine has two 2-second relay readiness loops:
# one during service startup and another after the Caddy site-bridge restart.
# On a small VPS, systemd can still be restarting the healthy relay during
# those loops. Adapt only retry/wait logic in the *downloaded temporary copy*,
# leaving the pinned engine, binary, site behavior and registration untouched.
python3 - "$EIGHT_SETUP" <<'PY_WPO_RELAY_READY_RETRY'
import sys
from pathlib import Path

path=Path(sys.argv[1])
source=path.read_text(encoding='utf-8')
startup='for attempt in 1 2 3 4 5 6 7 8 9 10; do'
site_anchor='bash -n "$TEMP/site-template-fix.sh"\nbash "$TEMP/site-template-fix.sh"'
if source.count(startup)!=1 or source.count(site_anchor)!=1:
    raise SystemExit('Pinned relay startup layout changed; refusing unverified patch.')

source=source.replace(startup,'for attempt in $(seq 1 60); do',1)
# The original script restarts WEB relay again after the private Caddy site
# bridge is prepared. Patch its two 2-second loops in the downloaded script.
bridge_patch="""bash -n "$TEMP/site-template-fix.sh"
python3 - "$TEMP/site-template-fix.sh" <<'PY_WPO_SITE_READY_RETRY'
import sys
from pathlib import Path
path=Path(sys.argv[1])
source=path.read_text(encoding='utf-8')
old_loop='for _ in 1 2 3 4 5 6 7 8 9 10; do'
if source.count(old_loop)!=2 or source.count('sleep 0.2')!=2:
    raise SystemExit('Pinned site-bridge readiness check changed.')
source=source.replace(old_loop,'for _ in $(seq 1 60); do')
source=source.replace('sleep 0.2','sleep 0.5')
# Transient connection refusals are normal during restart; show the journal
# only if all checks fail, not 10 low-level curl errors on the wizard screen.
source=source.replace('curl -4fsS --noproxy', 'curl -4fs --noproxy')
path.write_text(source,encoding='utf-8')
PY_WPO_SITE_READY_RETRY
bash -n "$TEMP/site-template-fix.sh"
bash "$TEMP/site-template-fix.sh" """
source=source.replace(site_anchor,bridge_patch.strip(),1)
# Avoid prematurely failing the initial relay listener while systemd settles.
source=source.replace('    sleep 0.2\n', '    sleep 0.5\n',1)
path.write_text(source,encoding='utf-8')
PY_WPO_RELAY_READY_RETRY
# The pinned eight-engine bootstrap was downloading the original
# wpo_node_eight.py, where _native_connections returned an envelope dict and
# VLESS-only remove() restarted every unrelated native service. Pull just the
# reviewed fixed Python module from an immutable commit: the remaining
# binaries, bootstrap scripts, AWG, Naive and Mieru modules stay pinned.
python3 - "$EIGHT_SETUP" <<'PY_WPO_NODE_NATIVE_FIX'
from pathlib import Path
import sys
script=Path(sys.argv[1])
source=script.read_text(encoding='utf-8')
loop='for module in wpp_awg.py wpp_extra_protocols.py wpo_node_eight.py; do'
url='"$BASE/$module" -o "$TEMP/$module"'
compile_line='    python3 -m py_compile "$TEMP/$module"'
if source.count(loop)!=1 or source.count(url)!=1 or source.count(compile_line)!=1:
    raise SystemExit('Pinned native engine layout changed: refusing unsafe installation.')
new_loop='''for module in wpp_awg.py wpp_extra_protocols.py wpo_node_eight.py; do
    module_url="$BASE/$module"
    if [[ "$module" == wpo_node_eight.py ]]; then
        module_url="https://raw.githubusercontent.com/TonyMaster14/web-panel-online/b424110fedc4940854e3d93eaa4f026df544bf8a/src/wpo_node_eight.py"
    fi'''
source=source.replace(loop,new_loop,1).replace(url,'"$module_url" -o "$TEMP/$module"',1)
source=source.replace(compile_line,'''    if [[ "$module" == wpo_node_eight.py ]]; then
        grep -Fq 'return list(GROUPED_CONNECTIONS.values())' "$TEMP/$module" &&
        grep -Fq 'native_changed = assemble(old) != assemble(new)' "$TEMP/$module" || {
            echo 'Node federation module is missing connection and removal fixes' >&2
            exit 4
        }
    fi
'''+compile_line,1)
script.write_text(source,encoding='utf-8')
PY_WPO_NODE_NATIVE_FIX
bash -n "$EIGHT_SETUP"
WPO_NODE_VPN_REF="$ENGINE_REV" bash "$EIGHT_SETUP"
rm -f -- "$EIGHT_SETUP"
# REALITY uses the same external TCP/443; keep sources immutable during install.
REALITY_REV=27ba7d2b9433faef0c47c6cf3912c5c0b367ac4d
REALITY_SETUP="$(mktemp /tmp/wpo-node-reality.XXXXXXXX.sh)"
curl -4fsSL --retry 3 --connect-timeout 15 --max-time 90 \
    "https://raw.githubusercontent.com/TonyMaster14/web-panel-online/${REALITY_REV}/nodes/wpo-node-reality-enable.sh" \
    -o "$REALITY_SETUP"
bash -n "$REALITY_SETUP"
WPO_NODE_VPN_REF="$REALITY_REV" bash "$REALITY_SETUP"
rm -f -- "$REALITY_SETUP"
# Refuse to enroll unless the AUTHENTICATED agent reports the exact expected
# set; component files alone do not prove that the serving API is ready.
# wpo-eight-agent-ready-retry-v1: systemd Type=simple may report active
# before Python binds port 9088. Caddy then briefly emits HTTP 502. Verify
# local agent readiness first, then authenticated public HTTPS, allowing
# systemd restarts and Caddy reload to settle without reinstalling anything.
NODE_STATUS=""
NODE_API_READY=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if systemctl is-active --quiet wpp-node-agent.service &&
     curl -4fsS --noproxy '*' --connect-timeout 1 --max-time 3 \
       http://127.0.0.1:9088/healthz >/dev/null 2>&1 &&
     NODE_STATUS="$(curl -4fsS --connect-timeout 5 --max-time 12 \
       -H "Authorization: Bearer $API_KEY" \
       "https://$DOMAIN/wpp-api/v1/status" 2>/dev/null)"; then
    NODE_API_READY=1
    break
  fi
  sleep 1
done
if [[ "$NODE_API_READY" != 1 ]]; then
  echo 'Node Agent не готов после запуска протоколов. Диагностика:' >&2
  systemctl is-active wpp-node-agent.service caddy.service 2>&1 || true
  echo 'Локальная проверка API (9088):' >&2
  curl -4sS --noproxy '*' -o /dev/null -w 'HTTP %{http_code}\\n' \
    --connect-timeout 2 --max-time 3 http://127.0.0.1:9088/healthz >&2 || true
  echo 'Публичная проверка API через Caddy (без раскрытия токена):' >&2
  curl -4sS -o /dev/null -w 'HTTP %{http_code}\\n' \
    --connect-timeout 3 --max-time 8 \
    -H "Authorization: Bearer $API_KEY" \
    "https://$DOMAIN/wpp-api/v1/status" >&2 || true
  journalctl -u wpp-node-agent.service --no-pager -n 20 >&2 || true
  report error 'Node Agent не отвечает после установки восьми протоколов.'
  echo 'Не удалось проверить Node Agent: нода не будет зарегистрирована.' >&2
  exit 4
fi
if ! NODE_STATUS="$NODE_STATUS" python3 - <<'PY_EIGHT_STATUS'
import json,os
data=json.loads(os.environ.get("NODE_STATUS","{}"))
expected={"federation","vless","reality","hysteria","web","mtproto","awg20","awg31","naive","mieru"}
actual=set(data.get("capabilities",[]))
missing=sorted(expected-actual)
if not data.get("ok") or missing:
    raise SystemExit("Node API lacks live engines: "+", ".join(missing))
print("✓ Девять протоколов и Federation подтверждены живым API Node Agent.")
PY_EIGHT_STATUS
then
  report error 'API ноды не подтвердил доступность всех восьми протоколов.'
  exit 4
fi
# wpo-node-provision-check-v1: GET readiness alone missed broken POST writes.
# Create and delete an isolated random VPN identity before publishing the node.
report installing 'Проверка создания VLESS/Hysteria2 профилей.'
if ! python3 - <<'PY_PROVISION_CHECK'
import json, secrets, urllib.request
from pathlib import Path
from urllib.parse import urlsplit
config=json.loads(Path('/etc/wpp-node-agent/config.json').read_text())
identifier=secrets.token_hex(32)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(operation, data):
    req=urllib.request.Request('http://127.0.0.1:9089/wpp-api/v1/federation/'+operation,
        data=json.dumps(data).encode(), method='POST', headers={
            'Authorization':'Bearer '+config['api_key'], 'Content-Type':'application/json'})
    with opener.open(req,timeout=90) as response:
        value=json.loads(response.read(32768))
    if not isinstance(value,dict) or value.get('ok') is not True:
        raise RuntimeError('Federation rejected install check')
    return value
try:
    try:
        data=request('sync',{'external_id':identifier,'name':'WPO install check',
                             'protocols':['vless','hysteria']})
        records=data.get('profiles',[])
        if not isinstance(records,list) or len(records)!=2:
            raise RuntimeError('Incomplete protocol response')
        if {p.get('protocol') for p in records}!={'vless','hysteria'}:
            raise RuntimeError('Incomplete protocol response')
        for p in records:
            link=urlsplit(p.get('link',''))
            expected='vless' if p['protocol']=='vless' else 'hysteria2'
            if link.scheme!=expected or link.hostname!=config['domain']:
                raise RuntimeError('Invalid protocol link')
    finally:
        request('delete',{'external_id':identifier})
except Exception as exc:
    # Never print API keys, generated links, or raw service errors.
    raise SystemExit('Federation POST check failed: '+type(exc).__name__)
print('✓ Создание и удаление VLESS/Hysteria2 профилей проверено.')
PY_PROVISION_CHECK
then
  report error 'Не прошла проверка создания VPN-профилей. Нода не зарегистрирована.'
  exit 4
fi
report registration 'Все 8 протоколов и HTTPS готовы. Регистрация ноды в панели.'
if ENROLL_RESULT="$(python3 - "$ENROLL_URL" "$TOKEN" "$DOMAIN" "$API_KEY" <<'PY_ENROLL'
import json,sys,urllib.request,urllib.error
url,token,domain,key=sys.argv[1:]
body=json.dumps({'token':token,'url':'https://'+domain,'api_key':key,'name':domain.split('.')[0]}).encode()
request=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'},method='POST')
try:
    with urllib.request.urlopen(request,timeout=20) as response:
        result=json.loads(response.read(32768))
except urllib.error.HTTPError as exc:
    raw=exc.read(8192)
    try:
        details=json.loads(raw.decode('utf-8','replace'))
        message=str(details.get('message') or 'Неизвестная ошибка')
    except (ValueError,AttributeError):
        message='Панель отклонила регистрацию'
    raise SystemExit('Регистрация: HTTP %d — %s' % (exc.code,message[:180]))
except (urllib.error.URLError,TimeoutError,OSError) as exc:
    raise SystemExit('Связь с панелью при регистрации недоступна: '+str(exc.reason if hasattr(exc,'reason') else exc)[:140])
except (ValueError,TypeError,UnicodeError):
    raise SystemExit('Панель вернула некорректный ответ при регистрации.')
if not isinstance(result,dict) or not result.get('ok'):
    raise SystemExit(str(result.get('message','Registration failed')) if isinstance(result,dict) else 'Registration failed')
print('Нода зарегистрирована:',result.get('node_id',''))
PY_ENROLL
)"; then
  printf '%s\n' "$ENROLL_RESULT"
else
  echo "$ENROLL_RESULT" >&2
  report error "$(printf '%s' "$ENROLL_RESULT" | head -c 160)"
  echo 'Ошибка регистрации. Если ключ установки истёк, удалите незавершённую установку в панели и создайте новый ключ.'
  exit 5
fi
# A successful controller enrollment is the only completion condition.
# Subsequent installer runs must ask before replacing this registered node.
python3 - "$DOMAIN" <<'PY_WPO_NODE_REGISTERED'
import datetime,json,os,sys,tempfile
from pathlib import Path
domain=sys.argv[1]
directory=Path('/etc/wpp-node-agent')
directory.mkdir(mode=0o700,parents=True,exist_ok=True)
target=directory/'registered.json'
fd,tmp=tempfile.mkstemp(dir=str(directory),prefix='.registration-')
try:
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        json.dump({'domain':domain,'registered':True,
                   'registered_at':datetime.datetime.now(
                       datetime.timezone.utc).isoformat()},stream)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(tmp,0o600)
    os.replace(tmp,target)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
PY_WPO_NODE_REGISTERED
trap - ERR
echo "Готово: Node Agent зарегистрирован на https://$DOMAIN"
if [[ -n "${WPO_NODE_PROGRESS_FILE:-}" && -f "$WPO_NODE_PROGRESS_FILE" ]]; then printf '98\tРегистрация подтверждена\n' > "$WPO_NODE_PROGRESS_FILE"; fi
