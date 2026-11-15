#!/usr/bin/env python3
"""Read-only: inspect every registered remote WPO Node Agent and VPN sidecar.

Designed to run on MAIN WPO; queries existing authenticated GET endpoints
only, never touches VPN profiles, SSH, credentials, user records or systemd.
"""
from pathlib import Path
from urllib.parse import urlsplit
import sys
import time

PANEL=Path("/opt/tproxy-panel/panel.py")
NODES=Path("/var/lib/tproxy-panel/nodes.json")
AGENT=Path("/etc/wpp-node-agent/config.json")

def classify(exc):
    cause=getattr(exc,"__cause__",None)
    code=getattr(cause,"code",None)
    if isinstance(code,int):
        if code == 401: return "HTTP 401 (ключ Node API не принят)"
        if code == 404: return "HTTP 404 (нет маршрута Federation API)"
        if code == 502: return "HTTP 502 (нет ответа внутренней VPN-службы)"
        if code == 503: return "HTTP 503 (VPN-служба не готова)"
        return "HTTP "+str(code)
    reason=getattr(cause,"reason",None)
    if isinstance(reason,TimeoutError) or isinstance(cause,TimeoutError):
        return "тайм-аут ответа"
    if cause:
        return type(cause).__name__
    return type(exc).__name__

def inspect():
    if not PANEL.is_file() or not NODES.is_file() or AGENT.exists():
        print("Нужна ОСНОВНАЯ WPO с реестром дополнительных нод.")
        return 2
    sys.path.insert(0,str(PANEL.parent))
    import wpp_nodes as api
    nodes=api.load_nodes(NODES)
    print("=== WPO: GET-проверка всех зарегистрированных нод ===")
    print("Дополнительных нод:",len(nodes))
    if not nodes:
        print("В панели пока нет дополнительных нод.")
        return 2
    ready=0
    for index,node in enumerate(nodes,1):
        name=urlsplit(str(node.get("url",""))).hostname or "неизвестная нода"
        if not node.get("enabled",True):
            print(f"{index}. {name}: отключена в настройках WPO")
            continue
        results={}
        for endpoint,title in (("/status","Node Agent"),
                               ("/federation/status","VPN Federation")):
            start=time.monotonic()
            try:
                data=api.request(node,"GET",api.API_PREFIX+endpoint,timeout=7)
                caps=set(data.get("capabilities") or [])
                wanted={"vless","hysteria","federation"}
                missing=sorted(wanted-caps)
                detail=("VPN API готова" if not missing else
                        "нет возможностей: "+",".join(missing))
                print(f"{index}. {name} / {title}: OK; {detail}; "+
                      f"{time.monotonic()-start:.1f}с")
                results[endpoint]=not missing
            except Exception as exc:
                print(f"{index}. {name} / {title}: {classify(exc)}; "+
                      f"{time.monotonic()-start:.1f}с")
                results[endpoint]=False
        if all(results.values()):
            ready+=1
    print(f"Результат: {ready} из {len(nodes)} дополнительных нод подтвердили оба VPN-протокола.")
    print("Проверка ничего не изменяет. GET-готовность ещё не доказывает успешное создание профиля POST.")
    return 0 if ready==len(nodes) else 6

if __name__=="__main__":
    raise SystemExit(inspect())
