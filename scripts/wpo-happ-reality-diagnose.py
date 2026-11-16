#!/usr/bin/env python3
"""Read-only WPO fleet check for fluctuating Happ N/A.

Run as root on the primary WPO controller. Never prints client IDs, bearer
tokens, UUIDs, private keys, public keys, or subscription URLs. The TCP port
tests DO NOT prove the REALITY handshake or Happ via-proxy connectivity.
"""
import concurrent.futures
import ipaddress
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlsplit

APP = "/opt/tproxy-panel"
REGISTRY = "/var/lib/tproxy-panel/nodes.json"
API = "/wpp-api/v1/federation/reality"
CHECKS = 3

def hostname(url):
    host = urlsplit(str(url)).hostname
    if not host or len(host) > 253:
        raise ValueError("invalid node host")
    return host

def tcp_probe(host, port=443, timeout=3.0):
    started=time.monotonic()
    try:
        addresses=socket.getaddrinfo(host,port,family=socket.AF_INET,type=socket.SOCK_STREAM)
        public=[a for a in addresses if ipaddress.ip_address(a[4][0]).is_global]
        if not public:
            return "DNS/IP"
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(public[0][4])
        return str(round((time.monotonic()-started)*1000))+"ms"
    except (OSError,ValueError,TimeoutError):
        return "timeout"

def concise(profile):
    if not isinstance(profile,dict):
        return ("unknown","unknown")
    sni=profile.get("sni")
    fp=profile.get("fingerprint")
    # Never print cryptographic keys or any arbitrary server error message.
    safe_sni=sni if isinstance(sni,str) and len(sni)<255 and all(c.isalnum() or c in ".-" for c in sni) else "unknown"
    safe_fp=fp if fp in ("firefox","edge","chrome","safari") else "unknown"
    return safe_sni,safe_fp

def scan_node(node,api):
    name=str(node.get("name") or node.get("country_name") or node.get("id") or "Нода")[:60]
    host=hostname(node.get("url"))
    info={"name":name,"host":host,"api":"unknown","sni":"unknown","fp":"unknown"}
    try:
        response=api.request(node,"GET",API,timeout=8)
        info["sni"],info["fp"]=concise(response.get("profile"))
        info["api"]="OK"
    except Exception:
        info["api"]="ERROR"
    info["tcp"]=[tcp_probe(host) for _ in range(CHECKS)]
    return info

def main():
    if os.geteuid()!=0:
        print("Запустите через sudo на основном VPS WPO.",file=sys.stderr)
        return 2
    if not Path(APP+"/wpp_nodes.py").is_file() or not Path(REGISTRY).is_file():
        print("На VPS не найдена основная панель WPO.",file=sys.stderr)
        return 2
    sys.path.insert(0,APP)
    import wpp_nodes as api
    import wpo_reality as reality
    nodes=api.load_nodes(REGISTRY)
    print("WPO / Happ REALITY · диагностика только для чтения")
    print("TCP 443 ≠ проверка REALITY. Значения ниже — TCP, не ping через VPN.")
    try:
        profile=reality.read_profile()
        main_sni,main_fp=concise(profile)
        address=str(profile.get("address",""))
        try:
            if not ipaddress.ip_address(address).is_global:
                raise ValueError()
            baseline=[tcp_probe(address) for _ in range(CHECKS)]
        except ValueError:
            baseline=["invalid IP"]
        print("\nОСНОВНАЯ: SNI="+main_sni+"; fingerprint="+main_fp+
              "; TCP443="+"/".join(baseline))
    except Exception:
        main_sni="unknown"
        print("\nОСНОВНАЯ: профиль REALITY не удалось прочитать.")
    print("\nДОПОЛНИТЕЛЬНЫЕ НОДЫ ("+str(len(nodes))+"):")
    if nodes:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6,len(nodes))) as executor:
            futures=[executor.submit(scan_node,node,api) for node in nodes]
            for future in futures:
                try:
                    item=future.result(timeout=25)
                    differs="  [SNI отличается от основной]" if main_sni!="unknown" and item["sni"] not in ("unknown",main_sni) else ""
                    print("• "+item["name"]+" ("+item["host"]+")")
                    print("  API="+item["api"]+"; SNI="+item["sni"]+
                          "; fingerprint="+item["fp"]+differs)
                    print("  TCP443="+"/".join(item["tcp"]))
                except Exception:
                    print("• Нода: не удалось завершить проверку")
    print("\nВажно: успешный TCP443 не означает, что REALITY или проверка Via Proxy в Happ успешны.")
    print("Скрипт ничего не сохранял и не изменял. Пароли, ключи и UUID не выводились.")
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (OSError,ValueError) as exc:
        print("WPO: невозможно завершить диагностику: "+type(exc).__name__,file=sys.stderr)
        sys.exit(3)
