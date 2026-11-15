#!/usr/bin/env python3
"""One-time primary-controller provisioning of the newest imported multi-node Happ subscription.

Only uses WPO's authenticated federation API. Never SSHs to a node, edits
existing users, creates devices, or emits credentials to logs.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT=Path("/opt/tproxy-panel")
sys.path.insert(0,str(ROOT))
import wpp_nodes as api

USERS=Path("/etc/web-proxy-panel/users.json")
NODES=Path("/var/lib/tproxy-panel/nodes.json")

def domain():
    proc=subprocess.run(["systemctl","show","-p","Environment","--value",
                         "tproxy-panel.service"],capture_output=True,
                        text=True,timeout=10,check=True)
    for pair in shlex.split(proc.stdout):
        if pair.startswith("WEBPROXY_DOMAIN="):
            value=pair.split("=",1)[1]
            if re.fullmatch(r"[a-z0-9.-]{3,253}",value) and "." in value:
                return value
    raise RuntimeError("Cannot safely obtain main panel domain")

def selected_subscription():
    root=json.loads(USERS.read_text(encoding="utf-8"))
    subs=root.get("subscriptions",[])
    if not isinstance(subs,list): raise ValueError("Invalid subscriptions registry")
    # Work on only the most recently created, already imported, selected
    # multi-node account. Never scan or reprovision the whole client base.
    eligible=[
        s for s in subs if isinstance(s,dict)
        and s.get("enabled",True)
        and isinstance(s.get("devices"),list) and s["devices"]
        and isinstance(s.get("node_ids"),list)
        and any(uid!="local" for uid in s["node_ids"])
        and isinstance(s.get("connections"),list)
    ]
    if not eligible:
        return None
    return max(eligible,key=lambda s:int(s.get("created_at",0) or 0))

def prepare():
    main=domain()
    sub=selected_subscription()
    if not sub:
        print("ℹ Пока нет импортированной в Happ подписки с дополнительными нодами; "
              "подготовка начнётся при первом обращении клиента.")
        return True
    nodes={str(n.get("id","")):n for n in api.load_nodes(NODES)}
    chosen=sub["node_ids"]
    if len(chosen)>17 or any(uid!="local" and uid not in nodes for uid in chosen):
        print("✗ Выбранная нода удалена: нужна проверка подписки в WPO.")
        return False
    wanted=list(dict.fromkeys(
        c.get("protocol") for c in sub["connections"] if isinstance(c,dict)
        and c.get("protocol") in ("vless","hysteria")))
    if not wanted:
        print("ℹ В выбранной подписке отсутствуют поддерживаемые VPN-протоколы.")
        return False
    remotes=[(uid,nodes[uid]) for uid in chosen if uid!="local"]
    devices=[d for d in sub["devices"] if isinstance(d,dict) and
             not d.get("revoked",False) and re.fullmatch(r"[a-f0-9]{16}",str(d.get("id","")))]
    if not devices:
        print("ℹ В этой подписке ещё нет активного устройства для подготовки.")
        return True
    # The latest HWID session is the device that likely just imported Happ.
    device=max(devices,key=lambda d:int(d.get("created_at",0) or 0))
    identifier=hashlib.sha256(
        (main+":"+str(sub["id"])+":"+str(device["id"])).encode()).hexdigest()
    name=str(sub.get("name") or "Подписка")[:80]
    print(f"Проверка подписки «{name}»: {len(remotes)} дополнительных VPN-нод, "
          f"протоколы {', '.join(wanted)}.")
    print("Профили создаются через существующий защищённый API; пароли и ключи не выводятся.")
    def one(item):
        uid,node=item
        if not node.get("enabled",True):
            return uid,node,False,"нода выключена",0
        start=time.monotonic()
        try:
            response=api.request(
                node,"POST",api.API_PREFIX+"/federation/sync",
                {"external_id":identifier,
                 "name":api.location_prefix(node),
                 "protocols":wanted},
                timeout=90)
            records=response.get("profiles")
            if not isinstance(records,list) or len(records)!=len(wanted):
                raise api.NodeError("неполный набор профилей")
            matched={}
            for p in records:
                if not isinstance(p,dict):
                    raise api.NodeError("некорректный профиль")
                proto=p.get("protocol")
                link=p.get("link")
                expected="vless" if proto=="vless" else "hysteria2" if proto=="hysteria" else ""
                if (proto not in wanted or proto in matched or not isinstance(link,str) or
                    len(link)>8192 or urlsplit(link).scheme!=expected or
                    urlsplit(link).hostname!=urlsplit(str(node.get("url",""))).hostname):
                    raise api.NodeError("неверный адрес или протокол")
                matched[proto]=link
            if set(matched)!=set(wanted):
                raise api.NodeError("отсутствует выбранный протокол")
            return uid,node,True,"",time.monotonic()-start
        except Exception as exc:
            upstream=getattr(getattr(exc,"__cause__",None),"code",None)
            status=("HTTP "+str(upstream)) if isinstance(upstream,int) else type(exc).__name__
            # No server-provided raw body is printed: it could contain secrets.
            return uid,node,False,status,time.monotonic()-start
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(remotes),4)) as pool:
        results=list(pool.map(one,remotes))
    healthy=True
    for uid,node,ok,error,seconds in results:
        label=str(node.get("name") or node.get("country_name") or node.get("url") or uid)[:80]
        print(("✓ " if ok else "✗ ")+label+
              (f" — готово ({seconds:.1f} с)" if ok else f" — {error} ({seconds:.1f} с)"))
        if not ok:healthy=False
    if healthy:
        print("✓ Все выбранные удалённые профили готовы. Обновите эту подписку в Happ.")
    else:
        print("✗ Не все ноды готовы: не публикуйте неполную подписку. "
              "Для диагностики потребуется журнал отказавшей ноды.")
    return healthy

if __name__=="__main__":
    try:
        sys.exit(0 if prepare() else 6)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print("Не удалось безопасно подготовить подписку: "+type(exc).__name__,file=sys.stderr)
        sys.exit(6)
