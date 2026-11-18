#!/usr/bin/env python3
"""WPO Remna-style REALITY SWEDEN CANARY v1, TEST BRANCH ONLY.

Starts a SEPARATE Xray at TCP 24443, a separate nginx TLS camouflage on
a local Unix socket (PROXY protocol v1), using existing REALITY identities.
Production WPO (HAProxy 443, Caddy, Node Agent and Xray) is not changed.
--check: strictly read-only preflight. --apply: installs only isolated units,
backs up production config read-only, validates/reverts own changes on failure.

Never paste the generated private HAPP link into chats or public logs.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import fcntl
import grp
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlencode

PORT = 24443
RUN = Path("/run/wpo-reality-remna-test")
SOCKET = RUN / "decoy.sock"
ROOT = Path("/etc/wpo-reality-remna-test")
LOCAL_BIN = Path("/opt/wpo-reality-remna-test")
LINK = Path("/root/wpo-reality-remna-sweden-test-link.txt")
XRAY = Path("/etc/wpp-node-vpn/xray.json")
SETTINGS = Path("/etc/wpp-node-vpn/settings.json")
PROFILE = Path("/etc/web-proxy-panel/reality/profile.json")
HAPROXY = Path("/etc/web-proxy-panel/reality/haproxy.cfg")
CERT = Path("/etc/wpp-node-vpn/tls/certificate.crt")
KEY = Path("/etc/wpp-node-vpn/tls/private.key")
XRAY_BIN = Path("/opt/web-panel-proxy/xray/xray")
UNIT_N = "wpo-reality-remna-nginx-test.service"
UNIT_X = "wpo-reality-remna-xray-test.service"
UNITDIR = Path("/etc/systemd/system")
BACKUP = Path("/var/backups/web-panel-online")
MARK = "WPO_REMNA_CANARY_V1"
LOCK = Path("/run/wpo-reality-remna-install.lock")

def command(*args, timeout=25, cwd=None):
    try:
        r = subprocess.run(list(map(str,args)), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout, check=False, cwd=cwd,
            stdin=subprocess.DEVNULL)
        return r
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Команда превысила тайм-аут: "+str(args[:2])) from exc

def ok_command(*args, timeout=25, cwd=None):
    r=command(*args,timeout=timeout,cwd=cwd)
    if r.returncode:
        raise RuntimeError("%s (exit %s): %s" % (str(args[:2]),r.returncode, (r.stderr or r.stdout)[-1100:]))
    return r

def active(unit):
    return command("systemctl","is-active","--quiet",unit,timeout=7).returncode==0

def json_file(path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Отсутствует или symlink: "+str(path))
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):raise RuntimeError("Некорректный JSON: "+str(path))
    return value

def is_reality(i):
    return (isinstance(i,dict) and i.get("protocol")=="vless"
            and (i.get("streamSettings") or {}).get("security")=="reality")

def strict_domain(raw):
    domain=str(raw or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",domain):
        raise RuntimeError("Некорректный домен ноды")
    return domain

def read_state():
    if Path("/opt/tproxy-panel/panel.py").exists():
        raise RuntimeError("Это основная панель! Скрипт только для ДОПОЛНИТЕЛЬНОЙ ноды Швеции.")
    if not all(active(x) for x in ("wpo-node-xray.service","wpo-tls-router.service","wpo-node-vpn.service")):
        raise RuntimeError("Действующие службы WPO не все активны. Ничего не меняем.")
    for path in (XRAY,SETTINGS,PROFILE,HAPROXY,CERT,KEY,XRAY_BIN):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Не найден необходимый обычный файл: "+str(path))
    settings=json_file(SETTINGS)
    profile=json_file(PROFILE)
    existing=json_file(XRAY)
    domain=strict_domain(settings.get("domain"))
    # Swedish node specifically; don't allow accidental use on Poland / another node.
    if domain != "swejeep.goodarielservice.xyz":
        raise RuntimeError("Это не тестовая Швеция: домен настроек "+domain)
    reality=[i for i in existing.get("inbounds",[]) if is_reality(i)]
    if len(reality)!=1:
        raise RuntimeError("Для безопасного теста нужен ровно 1 действующий REALITY inbound; найдено "+str(len(reality)))
    current=reality[0]
    rs=current["streamSettings"].get("realitySettings") or {}
    if rs.get("minClientVer")!="1.0.0":
        raise RuntimeError("Исходная Швеция не соответствует последнему тесту: minClientVer != 1.0.0")
    clients=(current.get("settings") or {}).get("clients")
    if not isinstance(clients,list) or not clients:
        raise RuntimeError("У Швеции нет REALITY клиентов для безопасного канареечного теста")
    if not isinstance(rs.get("privateKey"),str) or len(rs["privateKey"])<30:
        raise RuntimeError("Текущий REALITY privateKey недоступен")
    if not isinstance(rs.get("shortIds"),list) or not rs["shortIds"]:
        raise RuntimeError("Не найден Short ID")
    if not isinstance(profile.get("public_key"),str) or len(profile["public_key"])<30:
        raise RuntimeError("Не найден публичный ключ REALITY")
    expected_uuid="7f36b746-8567-4c88-b15c-dcb2a1612ce9"
    selected=next((c for c in clients if c.get("id")==expected_uuid),None)
    if selected is None:
        selected=next((c for c in clients if re.fullmatch(
            r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",
            str(c.get("id","")))),None)
    if selected is None: raise RuntimeError("Нет корректного REALITY UUID")
    # Validate the exact existing Caddy-issued TLS certificate against the node domain.
    cert=ok_command("openssl","x509","-in",CERT,"-noout","-checkhost",domain,timeout=8).stdout
    if "does match certificate" not in cert:
        raise RuntimeError("Сертификат TLS не соответствует домену "+domain+": "+cert.strip())
    ok_command("openssl","x509","-in",CERT,"-noout","-checkend","7200",timeout=8)
    # Do not assume the certificate and private key match: actually try loading both.
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(CERT),keyfile=str(KEY))
    return domain,profile,current,selected

def build(domain,profile,current,selected):
    inbound=copy.deepcopy(current)
    inbound["tag"]="wpo-remna-canary-reality"
    inbound["listen"]="0.0.0.0"
    inbound["port"]=PORT
    rs=inbound["streamSettings"]["realitySettings"]
    rs.pop("target",None)
    rs["dest"]=str(SOCKET)
    rs["xver"]=1
    rs["serverNames"]=[domain]
    rs["minClientVer"]="1.0.0"
    # Same UUIDs, private key, Short IDs and flow as original. Only the
    # TEST listener/decoy/SNI differ. This Xray is a separate process.
    config={
        "log":{"loglevel":"warning"},
        "inbounds":[inbound],
        "outbounds":[{"tag":"direct","protocol":"freedom"}]
    }
    # Quote is required for fragment/title, never output user UUID to stdout.
    q=urlencode({"encryption":"none","security":"reality","type":"tcp",
        "flow":selected.get("flow") or "xtls-rprx-vision","sni":domain,
        "fp":profile.get("fingerprint") or "firefox",
        "pbk":profile["public_key"],"sid":rs["shortIds"][0]})
    uri=("vless://"+quote(selected["id"],safe="-")+"@"+domain+":"+str(PORT)
         +"?"+q+"#"+quote("Sweden REMNA TEST 24443",safe=""))
    return config,uri

def nginx_config(domain):
    # Standalone nginx master, no port 80/443 and no production web config.
    return ("""
# WPO_REMNA_CANARY_V1 -- isolated test camouflage
user xray;
worker_processes 1;
pid /run/wpo-reality-remna-test/nginx.pid;
error_log stderr warn;
events { worker_connections 128; }
http {
  access_log off;
  server {
    listen unix:/run/wpo-reality-remna-test/decoy.sock ssl proxy_protocol;
    server_name DOMAIN;
    ssl_certificate /etc/wpp-node-vpn/tls/certificate.crt;
    ssl_certificate_key /etc/wpp-node-vpn/tls/private.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    default_type text/html;
    location / { return 200 "<!doctype html><html><body><h1>Welcome</h1></body></html>"; }
  }
}
""".replace("DOMAIN",domain).lstrip())

def acquire_nginx():
    binary=shutil.which("nginx")
    if binary:
        print("✓ Использую установленный nginx (только отдельный конфиг)")
        return Path(binary),False
    print("✓ nginx не установлен: извлекаю только бинарник из официального Ubuntu .deb")
    # Do NOT apt install: package post-install scripts might start nginx on 80
    # and interrupt WPO's Caddy. We only unpack into isolated /opt.
    with tempfile.TemporaryDirectory(prefix=".wpo-nginx-",dir="/opt") as td:
        downloaded=ok_command("apt-get","download","nginx",cwd=td,timeout=110)
        candidates=list(Path(td).glob("*.deb"))
        if len(candidates)!=1:
            raise RuntimeError("Не удалось скачать один пакет nginx из Ubuntu apt")
        target=Path(td)/"extracted"
        target.mkdir()
        ok_command("dpkg-deb","-x",candidates[0],target,timeout=45)
        nginx=target/"usr/sbin/nginx"
        if not nginx.is_file():raise RuntimeError("В загруженном пакете нет бинарника nginx")
        LOCAL_BIN.mkdir(mode=0o750,parents=False,exist_ok=False)
        final=LOCAL_BIN/"nginx"
        shutil.copy2(nginx,final)
        os.chmod(final,0o755)
        # test executable before proceeding with installation
        ok_command(final,"-v",timeout=8)
        return final,True

def atomic_bytes(path,value,mode=0o640,gid=0):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".wpo-remna-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(value);f.flush();os.fsync(f.fileno())
        os.chown(tmp,0,gid)
        os.chmod(tmp,mode)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def unit_files(nginx):
    n=("""
[Unit]
Description=WPO isolated RemnaWave-style nginx test (TCP 24443 only)
After=network.target
[Service]
Type=simple
User=root
Group=xray
UMask=0000
RuntimeDirectory=wpo-reality-remna-test
RuntimeDirectoryMode=0750
ExecStart=NGINX -c /etc/wpo-reality-remna-test/nginx.conf -g 'daemon off;'
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
[Install]
WantedBy=multi-user.target
""".replace("NGINX",str(nginx)).lstrip())
    x=("""
[Unit]
Description=WPO isolated RemnaWave-style Xray test TCP 24443
After=network.target wpo-reality-remna-nginx-test.service
Requires=wpo-reality-remna-nginx-test.service
[Service]
Type=simple
User=xray
Group=xray
ExecStart=/opt/web-panel-proxy/xray/xray run -config /etc/wpo-reality-remna-test/xray.json
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
[Install]
WantedBy=multi-user.target
""".lstrip())
    return n,x

def test_port():
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,0)
        sock.bind(("0.0.0.0",PORT))
    except OSError as exc:
        raise RuntimeError("Тестовый TCP 24443 уже занят: "+str(exc)) from exc
    finally:sock.close()

def preflight():
    if not os.geteuid()==0:raise RuntimeError("Требуется sudo")
    domain,profile,current,selected=read_state()
    if any(x.exists() for x in [ROOT,LOCAL_BIN,UNITDIR/UNIT_N,UNITDIR/UNIT_X,LINK]):
        raise RuntimeError("Тест уже установлен или остались файлы прошлого запуска; не перезаписываю. "+
            "Проверь /etc/wpo-reality-remna-test и systemctl status wpo-reality-remna-xray-test")
    if not grp.getgrnam("xray"):raise RuntimeError("Нет системной группы xray")
    test_port()
    config,uri=build(domain,profile,current,selected)
    # Verify candidate before touching service definitions.
    with tempfile.TemporaryDirectory(prefix=".wpo-remna-preflight-",dir="/tmp") as tmp:
        config_file=Path(tmp)/"xray.json"
        config_file.write_text(json.dumps(config),encoding="utf-8")
        check=command(XRAY_BIN,"run","-test","-config",config_file,timeout=25)
        if check.returncode:
            raise RuntimeError("Xray отказался принять новый REALITY: "+check.stderr[-1100:])
    print("✓ Швеция, действующие службы WPO активны")
    print("✓ Сертификат "+domain+" действителен и подходит к приватному ключу")
    print("✓ Новая схема: Xray TCP 24443 → Unix TLS nginx (PROXY v1)")
    print("✓ Новый SNI:",domain)
    print("✓ minClientVer: 1.0.0; клиенты:",len((current.get("settings") or {}).get("clients") or []))
    print("✓ Xray: candidate Configuration OK")
    print("✓ Старые REALITY 443, Caddy, XHTTP, Hysteria2 не меняются")
    return domain,config,uri

def apply():
    domain,config,uri=preflight()
    print("=== УСТАНОВКА ИЗОЛИРОВАННОГО ТЕСТА ===")
    files_created=[]
    units_created=[]
    nginx_installed=False
    start_time=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=BACKUP/("remna-sweden-canary-"+start_time)
    try:
        # Backups are root-only; no secret content printed.
        backup.mkdir(parents=True,mode=0o700,exist_ok=False)
        for p in (XRAY,SETTINGS,PROFILE,HAPROXY):
            destination=backup/(p.name if p!=XRAY else "production-xray.json")
            if destination.exists():
                destination=backup/(p.parent.name+"-"+p.name)
            shutil.copyfile(p,destination)
            os.chmod(destination,0o600)
        nginx,nginx_installed=acquire_nginx()
        # Prevalidate nginx with a standalone config. No interaction with Caddy.
        with tempfile.TemporaryDirectory(prefix=".wpo-nginx-check-",dir="/tmp") as td:
            candidate=Path(td)/"nginx.conf"
            candidate.write_text(nginx_config(domain),encoding="utf-8")
            RUN.mkdir(mode=0o750,parents=False,exist_ok=True)
            os.chown(RUN,0,grp.getgrnam("xray").gr_gid)
            os.chmod(RUN,0o750)
            check=command(nginx,"-t","-c",candidate,timeout=15)
            if check.returncode:
                raise RuntimeError("Nginx preflight failed: "+check.stderr[-1000:])
        ROOT.mkdir(mode=0o750,parents=False,exist_ok=False)
        os.chown(ROOT,0,grp.getgrnam("xray").gr_gid)
        os.chmod(ROOT,0o750)
        xconfig=ROOT/"xray.json"
        nconfig=ROOT/"nginx.conf"
        atomic_bytes(xconfig,json.dumps(config,ensure_ascii=False,indent=2).encode(),0o640,grp.getgrnam("xray").gr_gid)
        files_created.append(xconfig)
        atomic_bytes(nconfig,nginx_config(domain).encode(),0o640,grp.getgrnam("xray").gr_gid)
        files_created.append(nconfig)
        nu,xu=unit_files(nginx)
        for name,content in ((UNIT_N,nu),(UNIT_X,xu)):
            path=UNITDIR/name
            atomic_bytes(path,content.encode(),0o644,0)
            units_created.append(path)
        ok_command("systemctl","daemon-reload",timeout=20)
        ok_command("systemctl","start",UNIT_N,timeout=20)
        for _ in range(20):
            if SOCKET.is_socket() and active(UNIT_N):break
            time.sleep(.3)
        if not SOCKET.is_socket():raise RuntimeError("Nginx не поднял Unix TLS сокет")
        ok_command("systemctl","start",UNIT_X,timeout=20)
        for _ in range(20):
            if active(UNIT_X):
                try:
                    with socket.create_connection(("127.0.0.1",PORT),timeout=1):break
                except OSError:pass
            time.sleep(.3)
        else:raise RuntimeError("Тестовый Xray TCP 24443 не открылся")
        # End-to-end harmless TLS decoy test using SNI:
        # No secret-bearing URI is logged or sent anywhere.
        check=command("openssl","s_client","-connect", "127.0.0.1:"+str(PORT),
            "-servername",domain,"-brief",timeout=8)
        # We do not require its return code: unauthorized TLS decoy behaviour
        # can be browser-version-specific. Mandatory is local listener + services.
        if not active(UNIT_N) or not active(UNIT_X):
            raise RuntimeError("Тестовая служба остановилась после TLS-пробы")
        atomic_bytes(LINK,(uri+"\n").encode(),0o600,0)
        files_created.append(LINK)
        ok_command("systemctl","enable",UNIT_N,UNIT_X,timeout=15)
        print("✓ TEST READY: TCP 24443 слушает отдельный Xray; Nginx Unix TLS запущен")
        print("✓ Старая Швеция на 443 не менялась, все WPO службы оставлены активными")
        print("✓ Резервная копия:",backup)
        print("✓ Ссылка для HAPP сохранена ЛОКАЛЬНО:",LINK)
        print("  Чтобы получить: sudo cat "+str(LINK))
        print("  НЕ ПРИСЫЛАЙ ссылку в чат — в ней UUID клиента.")
        print("  Импортируй эту ссылку как ОТДЕЛЬНЫЙ профиль в HAPP и проверь интернет.")
        print("  Если внешне TCP 24443 недоступен, проверь firewall; скрипт его не изменяет.")
    except Exception as exc:
        for unit in (UNIT_X,UNIT_N):
            command("systemctl","disable","--now",unit,timeout=20)
        for path in units_created:
            try:path.unlink(missing_ok=True)
            except OSError:pass
        command("systemctl","daemon-reload",timeout=15)
        for path in files_created:
            try:path.unlink(missing_ok=True)
            except OSError:pass
        if ROOT.exists():
            try:ROOT.rmdir()
            except OSError:pass
        if nginx_installed and LOCAL_BIN.exists():
            shutil.rmtree(LOCAL_BIN,ignore_errors=True)
        print("! ТЕСТ НЕ УСТАНОВЛЕН: свои файлы/юниты убраны. Рабочие службы не трогал.")
        raise RuntimeError(str(exc)+"; backup="+str(backup)) from exc

def main():
    p=argparse.ArgumentParser(description="WPO isolated Remna-style REALITY test on SWEDEN")
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=p.parse_args()
    with open(LOCK,"a+") as lf:
        fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.check:
            preflight()
            print("✓ Только проверка. Изменений НЕТ.")
        else:apply()

if __name__=="__main__":
    try:main()
    except (RuntimeError,OSError,ValueError,KeyError,subprocess.SubprocessError,ssl.SSLError) as exc:
        print("ОШИБКА:",str(exc)[:1100],file=sys.stderr)
        raise SystemExit(1)
