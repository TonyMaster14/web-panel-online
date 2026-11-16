#!/usr/bin/env python3
"""WPO node: change REALITY decoy only after a real tunnel probe.

No new UUIDs, keys, short IDs, profiles, ports, OS packages or firewall rules.
Keeps a persistent backup and rolls back on ANY unsuccessful live tunnel test.
Run ONLY on the affected REALITY node VPS as root.
"""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

APP=Path("/opt/wpp-node-agent")
SYSREALITY=Path("/etc/web-proxy-panel/reality")
XRAY_FILE=Path("/etc/wpp-node-vpn/xray.json")
BIN=Path("/opt/web-panel-proxy/xray/xray")
CANDIDATES=("www.nvidia.com","www.apple.com","gateway.icloud.com","www.cloudflare.com")
PROBE_URL="https://www.gstatic.com/generate_204"

class TargetError(RuntimeError):
    pass

def command(argv,timeout=20):
    try:
        return subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise TargetError("Команда проверки не выполнена: "+type(exc).__name__) from exc

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]

def run_tunnel(sni,profile,client,original_inbound,server_port=None):
    """HTTP 204 via an actual REALITY handshake, including Xray + SOCKS.

    If server_port is None, start an isolated REALITY server on loopback using
    copied inbound/credentials. Never modify the running Xray or HAProxy.
    Otherwise test the real HAProxy TCP/443 path.
    """
    processes=[]
    with tempfile.TemporaryDirectory(prefix="wpo-reality-probe-") as directory:
        folder=Path(directory)
        try:
            if server_port is None:
                server_port=free_port()
                inbound=copy.deepcopy(original_inbound)
                inbound["listen"]="127.0.0.1"
                inbound["port"]=server_port
                rs=inbound["streamSettings"]["realitySettings"]
                rs.pop("dest",None)
                rs["target"]=sni+":443"
                rs["serverNames"]=[sni]
                rs["show"]=False
                isolated={"log":{"loglevel":"error"},"inbounds":[inbound],
                          "outbounds":[{"tag":"direct","protocol":"freedom"}]}
                launch(folder,"server",isolated,processes)
            socks=free_port()
            if socks==server_port: raise TargetError("Конфликт локальных портов проверки")
            config={"log":{"loglevel":"error"},
                    "inbounds":[{"listen":"127.0.0.1","port":socks,
                                 "protocol":"socks","settings":{"auth":"noauth"}}],
                    "outbounds":[{"protocol":"vless",
                                  "settings":{"vnext":[{"address":"127.0.0.1",
                                      "port":server_port,
                                      "users":[{"id":client["id"],"encryption":"none",
                                                "flow":"xtls-rprx-vision"}]}]},
                                  "streamSettings":{"network":"tcp","security":"reality",
                                      "realitySettings":{"serverName":sni,
                                          "fingerprint":profile.get("fingerprint","firefox"),
                                          "publicKey":profile["public_key"],
                                          "shortId":profile["short_id"]}}}]}
            launch(folder,"client",config,processes)
            for attempt in range(2):
                outcome=command(["curl","-4","--noproxy","","-sS",
                    "--socks5-hostname","127.0.0.1:"+str(socks),
                    "--connect-timeout","5","--max-time","12",
                    "-o","/dev/null","-w","%{http_code}",PROBE_URL],16)
                if outcome.returncode==0 and outcome.stdout.strip()=="204":
                    return True
                if attempt==0: time.sleep(0.5)
            return False
        finally:
            for process,log in reversed(processes):
                if process.poll() is None: process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=2)
                log.close()

def launch(folder,name,config,processes):
    conf=folder/(name+".json")
    conf.write_text(json.dumps(config),encoding="utf-8")
    conf.chmod(0o600)
    log=(folder/(name+".log")).open("w")
    try:
        proc=subprocess.Popen([str(BIN),"run","-config",str(conf)],
                              stdout=log,stderr=log)
    except Exception:
        log.close()
        raise
    processes.append((proc,log))
    time.sleep(.6)
    if proc.poll() is not None:
        raise TargetError("Временный Xray не запустился: "+name)

def backups():
    files={"profile.json":SYSREALITY/"profile.json",
           "haproxy.cfg":SYSREALITY/"haproxy.cfg",
           "xray.json":XRAY_FILE}
    folder=SYSREALITY/("target-backup-"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"-"+os.urandom(3).hex())
    folder.mkdir(mode=0o700)
    for filename,source in files.items():
        shutil.copy2(source,folder/filename)
    return folder

def apply_profile(reality,vpn,request):
    return reality.configure(request,lambda:
        vpn.apply(vpn.read_json(vpn.STATE,{"profiles":{}})["profiles"]))

def revert(reality,vpn,backup):
    # The original profile/config/router bytes are restored in-place, and Xray
    # is regenerated from the preserved subscription state. No key rotation.
    reality.atomic(reality.PUBLIC,(backup/"profile.json").read_text(),0o644)
    reality.atomic(reality.ROOT/"haproxy.cfg",(backup/"haproxy.cfg").read_text(),0o600)
    vpn.apply(vpn.read_json(vpn.STATE,{"profiles":{}})["profiles"])
    subprocess.run(["systemctl","reload","wpo-tls-router"],check=True,timeout=15)

def verify_services():
    for name in ("wpo-node-xray","wpo-tls-router","wpo-node-vpn","caddy"):
        if command(["systemctl","is-active","--quiet",name],6).returncode:
            raise TargetError("Неактивна служба "+name)

def change(reality,vpn,sni,profile,inbound,client,probe=run_tunnel):
    """Run under vpn.LOCK: no other provisioning may interleave our state."""
    reality.check_target(sni)
    if not probe(sni,profile,client,inbound):
        raise TargetError("Цель "+sni+" не прошла предварительный REALITY-туннель. Настройки не изменены.")
    print("✓ Предварительный туннель REALITY через "+sni+": HTTP 204",flush=True)
    backup=backups()
    print("Резервная копия: "+str(backup),flush=True)
    try:
        new=dict(profile,preset="custom",sni=sni)
        apply_profile(reality,vpn,{"preset":"custom","sni":sni,
                                   "fingerprint":new.get("fingerprint","firefox")})
        verify_services()
        if not probe(sni,new,client,inbound,443):
            raise TargetError("Туннель через рабочий порт 443 не прошёл проверку HTTP 204.")
        if reality.read_profile().get("sni")!=sni:
            raise TargetError("Цель REALITY не сохранилась.")
        print("✓ Рабочий порт 443: REALITY → HTTPS 204",flush=True)
        print("✓ Новая цель: "+sni+". UUID, ключи и профили сохранены.",flush=True)
        print("Обновите подписки клиентов: SNI изменился.",flush=True)
        return True
    except BaseException as exc:
        print("✗ Проверка после переключения не пройдена. Выполняю откат.",flush=True)
        try:
            revert(reality,vpn,backup)
            print("✓ Исходные профиль REALITY, HAProxy и Xray восстановлены.",flush=True)
        except Exception as restore_error:
            print("КРИТИЧНО: автоматический откат не завершён: "+str(restore_error),flush=True)
            print("Резервная копия сохранена: "+str(backup),flush=True)
        raise TargetError("Изменения отменены: "+type(exc).__name__) from exc

def main():
    parser=argparse.ArgumentParser(description="WPO REALITY safe target switch")
    parser.add_argument("--target",help="Проверить только эту цель; без аргумента перебирает безопасные кандидаты")
    args=parser.parse_args()
    if os.geteuid()!=0: raise TargetError("Запустите через sudo на VPS проблемной ноды.")
    if not BIN.is_file() or not XRAY_FILE.is_file() or not (SYSREALITY/"profile.json").is_file():
        raise TargetError("REALITY Node Agent не найден. Запускайте только на VPS ноды.")
    sys.path.insert(0,str(APP))
    import wpo_reality as reality
    import wpo_node_vpn as vpn
    profile=reality.read_profile()
    config=json.loads(XRAY_FILE.read_text())
    inbound=next((x for x in config["inbounds"]
                   if x.get("streamSettings",{}).get("security")=="reality"),None)
    if not inbound:
        raise TargetError("В Xray нет активного REALITY inbound.")
    settings=inbound["streamSettings"]["realitySettings"]
    if settings.get("serverNames")!=[profile["sni"]]:
        raise TargetError("Профиль и активная конфигурация Xray расходятся. Не меняю настройки.")
    clients=inbound.get("settings",{}).get("clients",[])
    if not clients: raise TargetError("Нет действующего REALITY-подключения для проверки туннеля.")
    candidates=(args.target,) if args.target else CANDIDATES
    for host in candidates:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{1,251})[a-z0-9]",host) or "." not in host:
            raise TargetError("Некорректное доменное имя для REALITY.")
    print("WPO REALITY: безопасная смена цели, установленная нода не переустанавливается.",flush=True)
    print("Сейчас: "+profile["sni"],flush=True)
    vpn.LOCK.parent.mkdir(parents=True,exist_ok=True)
    with vpn.LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        if reality.read_profile().get("sni")!=profile["sni"]:
            raise TargetError("Настройки изменились во время проверки, повторите операцию.")
        for sni in candidates:
            if sni==profile["sni"]: continue
            print("Проверяю "+sni+" (TLS 1.3 / HTTP2 / REALITY / HTTPS 204)...",flush=True)
            try:
                change(reality,vpn,sni,profile,inbound,clients[0])
                return 0
            except (TargetError,OSError,ValueError,subprocess.CalledProcessError) as exc:
                print("Не удалось: "+str(exc),flush=True)
                # A failure after writing must NOT automatically try another
                # candidate: leave the rollback result for inspection.
                if "Изменения отменены:" in str(exc):
                    return 5
        raise TargetError("Ни одна цель не прошла предварительный тест. Конфигурация не изменена.")

if __name__=="__main__":
    try: sys.exit(main())
    except (TargetError,OSError,KeyError,ValueError,subprocess.CalledProcessError) as exc:
        print("WPO REALITY: "+str(exc),file=sys.stderr,flush=True)
        sys.exit(4)
