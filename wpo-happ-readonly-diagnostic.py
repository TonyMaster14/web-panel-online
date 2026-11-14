#!/usr/bin/env python3
"""Read-only WPO Happ multi-node diagnosis, execute on PRIMARY WPO server.

No SSH, no installer, no writes, no federation/sync POST. Never output API
tokens, HWIDs, subscriptions' URLs or secret links. Only GET /status and
GET /federation/status with existing securely stored node credentials.
"""
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0,"/opt/tproxy-panel")
import wpp_nodes as api

PANEL=Path("/opt/tproxy-panel/panel.py")
NODES=Path("/var/lib/tproxy-panel/nodes.json")
USERS=Path("/etc/web-proxy-panel/users.json")
MARKER="wpo-multinode-parallel-v1"
REMOTE_ENDPOINTS=(("/status","Node Agent"),
                  ("/federation/status","VPN Federation"))

def check():
    if not PANEL.is_file() or not NODES.is_file() or not USERS.is_file() or Path("/etc/wpp-node-agent/config.json").exists():
        print("Ошибка: эту проверку можно запускать только на основной WPO.")
        return 2
    content=PANEL.read_text(encoding="utf-8")
    print("Основная панель:", "параллельная синхронизация включена" if MARKER in content else
          "используется старый механизм; обновление могло откатиться")
    nodes=api.load_nodes(NODES)
    print("Зарегистрировано дополнительных нод:",len(nodes))
    try:
        data=json.loads(USERS.read_text(encoding="utf-8"))
        subs=data.get("subscriptions",[]) if isinstance(data,dict) else []
        selected=[s for s in subs if isinstance(s,dict) and
                  s.get("enabled",True) and isinstance(s.get("node_ids"),list)
                  and any(uid!="local" for uid in s.get("node_ids",[]))]
        if selected:
            latest=max(selected,key=lambda s:int(s.get("created_at",0) or 0))
            ids=latest.get("node_ids",[])
            print("Последняя многонодовая подписка: выбрано нод",len(ids),
                  ", устройств",len(latest.get("devices",[])),
                  ", протоколы",",".join(str(v) for v in latest.get("protocols",[]))[:80])
            print("Проверяются только выбранные дополнительные ноды.")
            nodes=[n for n in nodes if n.get("id") in ids]
    except (OSError,ValueError,TypeError,UnicodeError):
        print("Невозможно прочитать настройки подписок; проверяются зарегистрированные ноды.")
    failed=False
    for n in nodes:
        host=urlsplit(n.get("url","")).hostname or "неизвестная нода"
        print("Нода:",host)
        for suffix,label in REMOTE_ENDPOINTS:
            start=time.monotonic()
            try:
                data=api.request(n,"GET",api.API_PREFIX+suffix,timeout=7)
                caps=data.get("capabilities",[])
                supported=isinstance(caps,list) and {"vless","hysteria"}.issubset(set(caps))
                print(f"  {label}: OK, {time.monotonic()-start:.1f}с; "
                      f"VPN VLESS/Hysteria: {'да' if supported else 'нет'}")
                if not supported:
                    failed=True
            except Exception as exc:
                cause=getattr(exc,"__cause__",None)
                status=getattr(cause,"code",None)
                cause_name=type(cause).__name__ if cause else type(exc).__name__
                if isinstance(status,int):
                    why="HTTP "+str(status)
                else:
                    why=cause_name
                print(f"  {label}: ОШИБКА {why}, {time.monotonic()-start:.1f}с")
                failed=True
    print("Это только GET-проверка: существующие VPN-профили, ключи и службы не изменены.")
    if not failed:
        print("Оба API отвечают. Если Happ всё ещё получает 503, сбой вероятен при POST создания профиля.")
    return 0

if __name__=="__main__":
    raise SystemExit(check())
