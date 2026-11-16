#!/usr/bin/env python3
"""Read-only REALITY connectivity diagnosis on a WPO VPS.

Tests the ACTUAL running TLS router and VLESS Vision server, never an isolated
synthetic REALITY server. Uses an existing (not newly provisioned) REALITY UUID
and a temporary local SOCKS client. Does not print or persist credentials.
Run on main WPO controller OR a remote node, as root, with no arguments.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

PROFILE=Path("/etc/web-proxy-panel/reality/profile.json")
NODE_XRAY=Path("/etc/wpp-node-vpn/xray.json")
MAIN_XRAY=Path("/etc/web-panel-proxy-xray/config.json")
NODE_SETTINGS=Path("/etc/wpp-node-vpn/settings.json")
BIN=Path("/opt/web-panel-proxy/xray/xray")
TARGET="https://www.gstatic.com/generate_204"

class CheckError(RuntimeError): pass

def safe_host(value):
    if not isinstance(value,str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}",value.lower()) or "." not in value:
        raise CheckError("Не удалось определить корректный публичный домен ноды")
    return value.lower()

def read_settings():
    if not PROFILE.is_file() or not BIN.is_file():
        raise CheckError("REALITY или исполняемый Xray не установлен на этом VPS")
    xray_file=NODE_XRAY if NODE_XRAY.is_file() else MAIN_XRAY
    if not xray_file.is_file():
        raise CheckError("Не найден рабочий конфигурационный файл Xray")
    try:
        cfg=json.loads(xray_file.read_text())
        profile=json.loads(PROFILE.read_text())
        inbounds=[x for x in cfg.get("inbounds",[]) if x.get("streamSettings",{}).get("security")=="reality"]
        sni=profile["sni"]
        # SNI compatibility may add multiple independent REALITY backends;
        # inspect exactly the preferred one, not merely the first found.
        matches=[x for x in inbounds if x["streamSettings"]["realitySettings"].get("serverNames")==[sni]]
        if len(matches)!=1:
            raise CheckError("Не найден однозначный REALITY backend для выбранного SNI")
        inbound=matches[0]
        reality=inbound["streamSettings"]["realitySettings"]
        if reality.get("serverNames")!=[sni]:
            raise CheckError("SNI профиля не совпадает с serverNames работающего Xray")
        if reality.get("target",reality.get("dest"))!=sni+":443":
            raise CheckError("Target Xray не совпадает с SNI сохранённого профиля")
        if profile["short_id"] not in reality["shortIds"]:
            raise CheckError("Short ID в профиле не совпадает с конфигурацией Xray")
        clients=inbound["settings"].get("clients",[])
        if not clients:
            raise CheckError("В Xray нет клиентских UUID REALITY; проверьте выбор нод в подписке")
        first=next((x for x in clients if x.get("flow")=="xtls-rprx-vision" and isinstance(x.get("id"),str)),None)
        if not first:
            raise CheckError("У клиентов REALITY отсутствует поток xtls-rprx-vision")
        fingerprint=profile["fingerprint"]
        if fingerprint not in ("firefox","edge"):
            raise CheckError("Неподдерживаемый fingerprint в REALITY-профиле")
        public_key=profile["public_key"]
        short_id=profile["short_id"]
        if (not isinstance(public_key,str) or len(public_key)!=43
                or not isinstance(short_id,str) or not re.fullmatch(r"[0-9a-fA-F]{0,32}",short_id)):
            raise CheckError("Неверные открытые параметры REALITY")
        if NODE_SETTINGS.is_file() and xray_file==NODE_XRAY:
            node_config=json.loads(NODE_SETTINGS.read_text())
            domain=safe_host(node_config["domain"])
            kind="Дополнительная нода"
        else:
            domain=str(profile.get("address",""))
            ipaddress.ip_address(domain)
            kind="Основная нода"
        return {"kind":kind,"domain":domain,"sni":sni,"fp":fingerprint,
                "key":public_key,"sid":short_id,"uuid":first["id"],"clients":len(clients)}
    except (KeyError,ValueError,TypeError) as exc:
        if isinstance(exc,CheckError):raise
        raise CheckError("Некорректные данные установленного REALITY") from exc

def resolve(host):
    found=[]
    try:
        entries=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        for entry in entries:
            ip=entry[4][0]
            if ipaddress.ip_address(ip).is_global and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found

def local_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]

def tunnel(profile,destination,attempts=3):
    # The test client uses the same REALITY settings and one currently enabled
    # UUID from Xray but points at the ACTUAL configured router TCP/443.
    port=local_port()
    with tempfile.TemporaryDirectory(prefix="wpo-happ-live-") as directory:
        cfg={
          "log":{"loglevel":"error"},
          "inbounds":[{"listen":"127.0.0.1","port":port,"protocol":"socks",
                       "settings":{"auth":"noauth"}}],
          "outbounds":[{"protocol":"vless",
              "settings":{"vnext":[{"address":destination,"port":443,
                  "users":[{"id":profile["uuid"],"encryption":"none","flow":"xtls-rprx-vision"}]}]},
              "streamSettings":{"network":"tcp","security":"reality",
                  "realitySettings":{"serverName":profile["sni"],
                      "fingerprint":profile["fp"],"publicKey":profile["key"],
                      "shortId":profile["sid"]}}}]}
        file=Path(directory)/"client.json"
        file.write_text(json.dumps(cfg),encoding="utf-8")
        file.chmod(0o600)
        process=None
        try:
            process=subprocess.Popen([str(BIN),"run","-config",str(file)],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            if process.poll() is not None:
                raise CheckError("Временный Xray-клиент не запустился")
            results=[]
            for _ in range(attempts):
                try:
                    outcome=subprocess.run(["curl","-4","--noproxy","","-sS",
                        "--socks5-hostname","127.0.0.1:"+str(port),
                        "--connect-timeout","4","--max-time","10",
                        "-o","/dev/null","-w","%{http_code} %{time_total}",
                        TARGET],capture_output=True,text=True,timeout=13)
                    parts=outcome.stdout.strip().split()
                    if outcome.returncode==0 and len(parts)==2 and parts[0]=="204":
                        results.append(str(round(float(parts[1])*1000))+"ms")
                    else:
                        results.append("FAIL")
                except (OSError,subprocess.TimeoutExpired,ValueError):
                    results.append("FAIL")
            return results
        finally:
            if process is not None:
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=2)

def active_units(profile):
    units=("wpo-tls-router.service",("wpo-node-xray.service" if profile["kind"]=="Дополнительная нода" else "web-panel-proxy-xray.service"))
    return [(unit,subprocess.run(["systemctl","is-active","--quiet",unit],
                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode==0) for unit in units]

def main():
    if os.geteuid()!=0:
        raise CheckError("Запустите через sudo на VPS проверяемой ноды")
    profile=read_settings()
    print("WPO / Happ: реальная проверка VLESS REALITY, без изменения конфигурации",flush=True)
    print("Сервер: "+profile["kind"]+" · "+profile["domain"],flush=True)
    print("SNI: "+profile["sni"]+"; fingerprint: "+profile["fp"]+"; клиентов REALITY: "+str(profile["clients"]),flush=True)
    for unit,active in active_units(profile):
        print("Служба "+unit+": "+("ACTIVE" if active else "INACTIVE"),flush=True)
    ips=resolve(profile["domain"])
    print("Публичные IP: "+(", ".join(ips) if ips else "не определены"),flush=True)
    print("REALITY через действующий локальный HAProxy (127.0.0.1:443):",flush=True)
    local=tunnel(profile,"127.0.0.1")
    print("  "+"/".join(local),flush=True)
    if not ips:
        print("REALITY через публичный адрес: пропущено (DNS/IP)",flush=True)
    else:
        ip4=next((ip for ip in ips if ":" not in ip),None)
        if ip4:
            print("REALITY через публичный IPv4 "+ip4+":",flush=True)
            external=tunnel(profile,ip4)
            print("  "+"/".join(external),flush=True)
        else:
            print("REALITY через публичный IPv4: нет A-записи",flush=True)
    print("Интерпретация: локальный FAIL — проблема REALITY/HAProxy/Xray на самой ноде;",flush=True)
    print("локальный OK, публичный FAIL — возможен hairpin NAT/маршрутизация;",flush=True)
    print("оба OK, Happ N/A — проверить свежесть URI, параметры клиента и путь от устройства.",flush=True)
    print("Проверка с VPS не заменяет проверку из сети устройства с Happ.",flush=True)
    print("UUID, публичные/приватные ключи, Short ID и API-токены не выводились.",flush=True)

if __name__=="__main__":
    try:main()
    except (CheckError,OSError,subprocess.TimeoutExpired) as exc:
        print("WPO REALITY: "+(str(exc) if isinstance(exc,CheckError) else type(exc).__name__),file=sys.stderr)
        sys.exit(2)
