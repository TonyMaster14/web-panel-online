#!/usr/bin/env python3
"""SWEDEN ONLY: transient REALITY 443 trial on isolated WPO canary.

Preconditions: existing canary V1 on TCP 24443 is running; WPO HAProxy
443/Caddy 19443/Xray19444 are currently healthy. This script preserves
production Xray/Caddy config, changes ONLY canary configs, and pauses
HAProxy while the independent canary Xray holds TCP443.

The switch is automatically rolled back after 12 minutes unless
--confirm is called. Explicit --rollback works at any time. A persistent
rollback timer also re-arms on boot; avoid rebooting while testing.
"""
from __future__ import annotations
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

DOMAIN="swejeep.goodarielservice.xyz"
CANARY=Path("/etc/wpo-reality-remna-test")
CANARY_X=CANARY/"xray.json"
CANARY_N=CANARY/"nginx.conf"
STATE=CANARY/"switch-443-state.json"
ORIG=Path("/etc/wpp-node-vpn/xray.json")
HAPROXY=Path("/etc/web-proxy-panel/reality/haproxy.cfg")
CERT=Path("/etc/wpp-node-vpn/tls/certificate.crt")
XRAY_BIN=Path("/opt/web-panel-proxy/xray/xray")
SETTINGS=Path("/etc/wpp-node-vpn/settings.json")
SCRIPT=Path("/root/wpo-sweden-real443-switch-v1.py")
BACKUPS=Path("/var/backups/web-panel-online")
CN="wpo-reality-remna-nginx-test.service"
CX="wpo-reality-remna-xray-test.service"
ROUTER="wpo-tls-router.service"
API="wpo-node-vpn.service"
PROD="wpo-node-xray.service"
TIMEOUT="wpo-sweden-443-auto-rollback"
UNITDIR=Path("/etc/systemd/system")
CAPDIR=UNITDIR/("wpo-reality-remna-xray-test.service.d")
CAPFILE=CAPDIR/"91-wpo-sweden-443-bind.conf"
CAP_MARK="# WPO_SWEDEN_REAL443_CAPABILITY_V2"
LOCK=Path("/run/wpo-sweden-443-switch.lock")
UNIX="/run/wpo-reality-remna-test/decoy.sock"
MARK="WPO_REMNA_CANARY_V1"
ROLLBACK_MINUTES=12

def cmd(*args, timeout=25):
    try:
        return subprocess.run([str(x) for x in args], check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Превышен тайм-аут: "+str(args[:2])) from e

def need(*args, timeout=25):
    p=cmd(*args,timeout=timeout)
    if p.returncode:
        raise RuntimeError("%s (код %d): %s" % (str(args[:3]),p.returncode,(p.stderr or p.stdout)[-800:]))
    return p

def active(unit):
    return cmd("systemctl","is-active","--quiet",unit,timeout=5).returncode==0

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, content, mode=0o600):
    path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix=".wpo443-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def require_canary():
    for x in (CANARY_X,CANARY_N,ORIG,SETTINGS,HAPROXY,CERT,XRAY_BIN):
        if not x.is_file() or x.is_symlink():
            raise RuntimeError("Отсутствует ожидаемый файл Швеции: "+str(x))
    settings=json.loads(SETTINGS.read_text())
    if settings.get("domain")!=DOMAIN:raise RuntimeError("Это не Швеция: неверный домен")
    canary=json.loads(CANARY_X.read_text())
    if len(canary.get("inbounds",[]))!=1:
        raise RuntimeError("У тестового Xray должно быть ровно 1 inbound")
    inbound=canary["inbounds"][0]
    rs=inbound.get("streamSettings",{}).get("realitySettings",{})
    if (inbound.get("port") not in (443,24443)
        or inbound.get("protocol")!="vless"
        or inbound.get("streamSettings",{}).get("security")!="reality"
        or rs.get("serverNames")!=[DOMAIN]
        or rs.get("dest")!=UNIX
        or rs.get("xver")!=1
        or rs.get("minClientVer")!="1.0.0"):
        raise RuntimeError("Конфигурация тестового REALITY неожиданно отличается")
    nginx=CANARY_N.read_text()
    if MARK not in nginx or UNIX not in nginx:
        raise RuntimeError("Nginx-конфигурация не соответствует тестовой установке")
    if not re.search(r'(?m)^\s*listen\s+unix:'+re.escape(UNIX)+r'\s+ssl\s+proxy_protocol(?:\s+http2)?\s*;',nginx):
        raise RuntimeError("Unix TLS nginx listener изменён")
    return canary,nginx

def create_bridge_config(original):
    # Preserve all existing TLS configuration, routes etc. The isolated nginx
    # currently serves a dummy page. Replace *only* that single location.
    if "proxy_pass https://127.0.0.1:19443;" in original:
        raise RuntimeError("Тестовый Nginx уже переключён на 443")
    expected='location / { return 200 "<!doctype html><html><body><h1>Welcome</h1></body></html>"; }'
    if original.count(expected)!=1:
        raise RuntimeError("Неожиданное содержимое Nginx location; отказ от изменения")
    newloc=r"""location / {
      proxy_pass https://127.0.0.1:19443;
      proxy_ssl_server_name on;
      proxy_ssl_name DOMAIN;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $wpo_connection_upgrade;
      proxy_http_version 1.1;
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
      client_max_body_size 0;
    }""".replace("DOMAIN",DOMAIN)
    result=original.replace(expected,newloc)
    # Ubuntu 24.04 nginx v1.24 supports HTTP/2 via 'listen ... http2'.
    result=result.replace('ssl proxy_protocol;', 'ssl proxy_protocol http2;',1)
    result=result.replace('http {\n','''http {
  map $http_upgrade $wpo_connection_upgrade {
    default upgrade;
    '' close;
  }
''',1)
    return result

def create_direct_xray(old):
    new=json.loads(json.dumps(old))
    new["inbounds"][0]["port"]=443
    return new

def tls_probe(host,port,path="/"):
    with socket.create_connection((host,port),timeout=5) as base:
        ctx=ssl.create_default_context()
        with ctx.wrap_socket(base,server_hostname=DOMAIN) as tls:
            tls.settimeout(5)
            tls.sendall(("GET "+path+" HTTP/1.1\r\nHost: "+DOMAIN+
                        "\r\nConnection: close\r\n\r\n").encode())
            b=tls.recv(1024)
    found=re.match(rb'HTTP/1\.[01] ([0-9]{3})',b)
    if not found:raise RuntimeError("Не получен HTTP-ответ через TLS: "+str(port))
    return int(found.group(1))

def probe_socket():
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as plain:
        plain.settimeout(6)
        plain.connect(UNIX)
        plain.sendall(b"PROXY TCP4 127.0.0.1 127.0.0.1 12345 443\r\n")
        ctx=ssl.create_default_context()
        with ctx.wrap_socket(plain,server_hostname=DOMAIN) as tls:
            tls.sendall(("GET / HTTP/1.1\r\nHost: "+DOMAIN+
                    "\r\nConnection: close\r\n\r\n").encode())
            b=tls.recv(1024)
    found=re.match(rb'HTTP/1\.[01] ([0-9]{3})',b)
    if not found:raise RuntimeError("Nginx Unix TLS не вернул HTTP")
    return int(found.group(1))

def validate_nginx(config):
    if shutil.which("nginx"):
        nginx=shutil.which("nginx")
    else:
        nginx="/opt/wpo-reality-remna-test/nginx"
    if not Path(nginx).is_file():raise RuntimeError("Тестовый nginx бинарник не найден")
    with tempfile.TemporaryDirectory(prefix="wpo-sweden-443-") as td:
        p=Path(td)/"nginx.conf"
        p.write_text(config)
        need(nginx,"-t","-c",p,timeout=15)

def validate_xray(config):
    with tempfile.TemporaryDirectory(prefix="wpo-sweden-xray-") as td:
        p=Path(td)/"xray.json"
        p.write_text(json.dumps(config))
        need(XRAY_BIN,"run","-test","-config",p,timeout=25)

def listeners():
    # Linux ss with -p can identify process but no port mutation.
    return cmd("ss","-lntp",timeout=8).stdout

def check():
    if os.geteuid()!=0:raise RuntimeError("Требуется sudo")
    if not SCRIPT.is_file():
        raise RuntimeError("Сохрани скрипт на сервер: "+str(SCRIPT))
    if STATE.exists():
        raise RuntimeError("Швеция уже в тестовом режиме 443; используй --status, --confirm или --rollback")
    if CAPFILE.exists():
        raise RuntimeError("Неожиданный drop-in от прошлого теста: "+str(CAPFILE))
    old,nginx=require_canary()
    if old["inbounds"][0]["port"]!=24443:
        raise RuntimeError("Исходный тестовый Xray должен слушать 24443")
    for u in (CN,CX,ROUTER,PROD,API,"caddy.service"):
        if not active(u):raise RuntimeError("Неактивна важная служба "+u)
    listen=listeners()
    if "0.0.0.0:443" not in listen and "*:443" not in listen:
        raise RuntimeError("На 443 отсутствует HAProxy, остановимся")
    nginx2=create_bridge_config(nginx)
    xray2=create_direct_xray(old)
    validate_nginx(nginx2)
    validate_xray(xray2)
    code=tls_probe("127.0.0.1",19443)
    if code>=500:raise RuntimeError("Caddy 19443 вернул HTTP "+str(code))
    print("✓ Caddy HTTPS 19443 ответил HTTP",code)
    print("✓ Nginx TLS proxy→Caddy и Xray REALITY TCP443 прошли проверку конфигураций")
    print("✓ Существующие XHTTP/HTTPS запросы будут направляться в Caddy через Nginx")
    print("✓ Тестовый REALITY сохраняет UUID, ключи, SNI ноды, minClientVer 1.0.0")
    print("! На время теста старые ссылки REALITY с SNI www.nvidia.com не работают.")
    print("! Смена порта требует кратковременного переключения HAProxy → Xray.")
    return old,nginx,nginx2,xray2

def backup_files():
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder=BACKUPS/("sweden-real443-"+stamp)
    folder.mkdir(mode=0o700,parents=True,exist_ok=False)
    for path,key in ((CANARY_X,"canary-xray.json"),(CANARY_N,"canary-nginx.conf"),
                     (HAPROXY,"production-haproxy.cfg"),(ORIG,"production-xray.json")):
        target=folder/key
        shutil.copyfile(path,target)
        os.chmod(target,0o600)
    return folder

def install_timer():
    # Permanent systemd timer (not transient): survives a reboot during trial.
    # The local script is saved before the switch, so no GitHub access needed.
    service=UNITDIR/(TIMEOUT+".service")
    timer=UNITDIR/(TIMEOUT+".timer")
    for unit in (service,timer):
        if unit.exists():raise RuntimeError("Конфликт существующего systemd unit: "+str(unit))
    save(service,("""[Unit]
Description=WPO Sweden REALITY 443 emergency rollback
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /root/wpo-sweden-real443-switch-v1.py --rollback
""").encode(),0o644)
    save(timer,("""[Unit]
Description=WPO Sweden REALITY 443 timed automatic rollback
[Timer]
OnActiveSec=12min
AccuracySec=5s
Unit=wpo-sweden-443-auto-rollback.service
[Install]
WantedBy=timers.target
""").encode(),0o644)
    try:
        need("systemctl","daemon-reload",timeout=15)
        need("systemctl","enable","--now",TIMEOUT+".timer",timeout=15)
        if not active(TIMEOUT+".timer"):raise RuntimeError("Таймер отката не активен")
    except Exception:
        cmd("systemctl","disable","--now",TIMEOUT+".timer",timeout=12)
        service.unlink(missing_ok=True);timer.unlink(missing_ok=True)
        cmd("systemctl","daemon-reload",timeout=10)
        raise

def cancel_timer():
    cmd("systemctl","disable","--now",TIMEOUT+".timer",timeout=10)
    (UNITDIR/(TIMEOUT+".timer")).unlink(missing_ok=True)
    (UNITDIR/(TIMEOUT+".service")).unlink(missing_ok=True)
    cmd("systemctl","daemon-reload",timeout=12)

def install_bind_capability():
    # The canary service runs as User=xray. Without this *unit-specific*
    # capability it can bind 24443 but typically cannot bind privileged 443.
    # Do not modify sysctl, the executable file capabilities, or production units.
    if CAPFILE.exists():
        raise RuntimeError("Изолированный drop-in для CAP_NET_BIND_SERVICE уже существует")
    if CAPDIR.exists() and not CAPDIR.is_dir():
        raise RuntimeError("Конфликт пути systemd drop-in")
    CAPDIR.mkdir(mode=0o755,parents=False,exist_ok=True)
    save(CAPFILE, (CAP_MARK+"""
[Service]
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
""").encode(),0o644)
    need("systemctl","daemon-reload",timeout=15)
    show=need("systemctl","show",CX,"-p","AmbientCapabilities",timeout=10).stdout
    if "CAP_NET_BIND_SERVICE" not in show and "cap_net_bind_service" not in show:
        # Some versions format the capabilities as a numeric bitmask,
        # therefore expose it for diagnostics rather than assuming success.
        print("! Systemd capability view:",show.strip())
    print("✓ Только тестовый Xray получил CAP_NET_BIND_SERVICE для TCP 443")

def remove_bind_capability():
    if not CAPFILE.exists():return
    content=CAPFILE.read_text(encoding="utf-8")
    if CAP_MARK not in content:
        raise RuntimeError("Неизвестный systemd drop-in — не удаляю")
    CAPFILE.unlink()
    try:CAPDIR.rmdir()
    except OSError:pass
    need("systemctl","daemon-reload",timeout=15)

def recent_canary_logs():
    result=cmd("journalctl","-u",CX,"--no-pager","-n","22","-o","cat",timeout=8)
    if result.returncode:return "журнал недоступен"
    text=result.stdout
    # Avoid printing UUIDs and other client identifiers in user terminal.
    text=re.sub(r"(?i)\\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\\b","[UUID]",text)
    return text[-2000:]

def restore():
    if not STATE.exists():
        print("Нет активного переключения 443. Нечего откатывать.")
        return
    data=json.loads(STATE.read_text())
    folder=Path(data["backup"])
    if not folder.is_dir() or BACKUPS not in folder.parents:
        raise RuntimeError("Некорректная директория резервной копии")
    if not (folder/"canary-xray.json").is_file() or not (folder/"canary-nginx.conf").is_file():
        raise RuntimeError("Резервные копии тестовых конфигураций не найдены")
    print("Возвращаю маршрутизацию WPO на порт 443 ...")
    # Stop direct 443 before starting HAProxy; never continue if it still holds 443.
    need("systemctl","stop",CX,timeout=20)
    # Restore only isolated canary config; production configs were never edited.
    oldx=(folder/"canary-xray.json").read_bytes()
    oldn=(folder/"canary-nginx.conf").read_bytes()
    save(CANARY_X,oldx,0o640)
    os.chown(CANARY_X,0,__import__("grp").getgrnam("xray").gr_gid)
    save(CANARY_N,oldn,0o640)
    os.chown(CANARY_N,0,__import__("grp").getgrnam("xray").gr_gid)
    need("systemctl","restart",CN,timeout=20)
    # Keep 24443 optional: restart canary if it was active originally.
    if data.get("canary_x_running",True):
        need("systemctl","start",CX,timeout=20)
    need("systemctl","start",ROUTER,timeout=20)
    if data.get("router_was_enabled"):
        need("systemctl","enable",ROUTER,timeout=15)
    if not active(ROUTER):raise RuntimeError("HAProxy не восстановился")
    if not active(PROD) or not active(API):
        raise RuntimeError("Одна из рабочих служб WPO неактивна")
    # Restore exactly the pre-trial privilege state after port 443 is back.
    remove_bind_capability()
    if data.get("canary_x_running",True):
        # Drop the temporary privileged-port capability from the running
        # canary process as well, not just from its on-disk systemd unit.
        need("systemctl","restart",CX,timeout=20)
        if not active(CX):
            raise RuntimeError("Тестовый Xray не восстановился на 24443 без повышенных прав")
    STATE.unlink(missing_ok=True)
    Path("/root/wpo-sweden-real443-happ-link.txt").unlink(missing_ok=True)
    cancel_timer()
    print("✓ HAProxy вернулся на 443, Xray старого WPO не изменён")
    print("✓ Тестовый Xray вернулся на TCP 24443")
    print("✓ Резервная копия сохранена в",folder)

def switch():
    old,nginx,nginx2,xray2=check()
    backup=backup_files()
    enabled=cmd("systemctl","is-enabled",ROUTER,timeout=7).stdout.strip()
    state={"backup":str(backup),"canary_x_running":True,
           "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "original_router_running":True,
           "router_was_enabled":enabled=="enabled"}
    save(STATE,json.dumps(state).encode(),0o600)
    # Arm a persistent rollback timer BEFORE stopping HAProxy.
    # This timer is re-armed on reboot and needs no internet connection.
    try:
        install_timer()
    except Exception:
        STATE.unlink(missing_ok=True)
        raise
    try:
        need("systemctl","disable","--now",ROUTER,timeout=20)
        need("systemctl","stop",CX,timeout=20)
        install_bind_capability()
        save(CANARY_N,nginx2.encode(),0o640)
        os.chown(CANARY_N,0,__import__("grp").getgrnam("xray").gr_gid)
        save(CANARY_X,(json.dumps(xray2,indent=2)+"\n").encode(),0o640)
        os.chown(CANARY_X,0,__import__("grp").getgrnam("xray").gr_gid)
        need("systemctl","restart",CN,timeout=20)
        for _ in range(25):
            if active(CN) and Path(UNIX).is_socket():break
            time.sleep(.2)
        else:raise RuntimeError("Nginx не запустился")
        status=probe_socket()
        if status>=500:
            raise RuntimeError("Сокет Nginx→Caddy вернул HTTP "+str(status))
        print("✓ Unix PROXY v1 → TLS nginx → Caddy: HTTP",status)
        need("systemctl","start",CX,timeout=20)
        for _ in range(20):
            if active(CX):
                try:
                    with socket.create_connection(("127.0.0.1",443),timeout=1):
                        break
                except OSError:pass
            time.sleep(.25)
        else:
            logs=recent_canary_logs()
            raise RuntimeError("Новый Xray не открыл TCP 443. Журнал Xray:\\n"+logs)
        # An unauthenticated TLS client must reach Nginx fallback over 443.
        code=tls_probe("127.0.0.1",443)
        if code>=500:raise RuntimeError("Новый внешний 443 вернул HTTP "+str(code))
        if not all(active(u) for u in (CN,CX,PROD,API,"caddy.service")):
            raise RuntimeError("Исходная VPN инфраструктура остановилась")
        print("✓ REALITY Xray напрямую на TCP 443; HTTPS→Caddy через Unix TLS работает")
        print("✓ Временная ссылка HAPP будет создана из уже установленной ссылки тестового порта")
        p=Path("/root/wpo-reality-remna-sweden-test-link.txt")
        if not p.is_file():raise RuntimeError("Отсутствует ссылка из тестового установщика")
        u=p.read_text().strip()
        if ":24443?" not in u:raise RuntimeError("Неожиданный формат тестовой ссылки")
        new=u.replace(":24443?",":443?",1).replace("24443","443")
        link=Path("/root/wpo-sweden-real443-happ-link.txt")
        save(link,(new+"\n").encode(),0o600)
        print("✓ TEST LIVE. Тестовая ссылка только локально: sudo cat "+str(link))
        print("✓ АВТОМАТИЧЕСКИЙ ОТКАТ ЧЕРЕЗ",ROLLBACK_MINUTES,"МИНУТ, если не подтвердить.")
        print("Если HAPP заработает: sudo python3 "+str(SCRIPT)+" --confirm")
        print("Если не заработает: sudo python3 "+str(SCRIPT)+" --rollback")
        print("Не перезагружай VPS во время проверки HAPP.")
    except Exception as exc:
        print("! Ошибка переключения, восстанавливаю прежний TCP443: "+str(exc)[:1400])
        try:
            restore()
        except Exception as rexc:
            print("! АВАРИЙНЫЙ ОТКАТ ТРЕБУЕТ ПРОВЕРКИ:",str(rexc)[:500],file=sys.stderr)
            print("! Таймер резервного отката оставлен активным.",file=sys.stderr)
        raise

def status():
    if not STATE.exists():
        print("Тест 443 не активен; смотри старую схему HAProxy.")
        return
    print("Тест 443 активен:", "Xray="+str(active(CX)), "Nginx="+str(active(CN)),
          "HAProxy="+str(active(ROUTER)),
          "автооткат="+str(active(TIMEOUT+".timer")))
    if not active(TIMEOUT+".timer"):
        print("ВНИМАНИЕ: таймер отката не активен.")

def confirm():
    if not STATE.exists():raise RuntimeError("Нет активного теста")
    if not active(CX) or active(ROUTER):
        raise RuntimeError("Новые службы 443 не в ожидаемом состоянии; подтверждение запрещено")
    if not active(TIMEOUT+".timer"):
        raise RuntimeError("Таймер отката не активен; проверь --status и --rollback")
    code=tls_probe("127.0.0.1",443)
    if code>=500:
        raise RuntimeError("HTTPS после REALITY вернул HTTP "+str(code))
    cancel_timer()
    print("✓ Автоматический откат отменён. Это ВРЕМЕННЫЙ тестовый режим Швеции.")
    print("! Новые клиенты WPO пока НЕ синхронизируются автоматически с тестовым Xray.")
    print("! Для возвращения исходного режима: sudo python3 "+str(SCRIPT)+" --rollback")

def main():
    p=argparse.ArgumentParser()
    opt=p.add_mutually_exclusive_group(required=True)
    for a in ("check","apply","status","confirm","rollback"):
        opt.add_argument("--"+a,action="store_true")
    a=p.parse_args()
    if os.geteuid()!=0:raise RuntimeError("Требуется sudo")
    with open(LOCK,"a+") as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        if a.check:check()
        elif a.apply:switch()
        elif a.status:status()
        elif a.confirm:confirm()
        else:restore()

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError,ssl.SSLError) as exc:
        print("ОШИБКА:",str(exc)[:1100],file=sys.stderr)
        raise SystemExit(1)
