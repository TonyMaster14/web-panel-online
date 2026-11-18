#!/usr/bin/env python3
"""WPO one-command comprehensive, READ-ONLY subscription incident audit.

Run only on WPO PANEL as root. No valid POST syncs, no subscription fetches,
no changes to Xray/users, no restarts. Intentional invalid-ID POSTs return
400 before any profile writes. Reports only counts, country codes, harmless
status codes and exception classes, never secrets, domains, IDs or URLs.
"""
from __future__ import annotations
from collections import Counter,defaultdict
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError

APP=Path("/opt/tproxy-panel")
DB=Path("/etc/web-proxy-panel/users.json")
NODE_DB=Path("/var/lib/tproxy-panel/nodes.json")
READY=Path("/var/lib/tproxy-panel/happ-node-ready.json")
MAX_EVENTS=14

def emit(*values):
    print(*values,flush=True)

issues=[]
def finding(level,tag,message):
    issues.append((level,tag,message))
    emit("  "+level+" "+tag+" — "+message)

def safe_json(path):
    try:
        if not path.is_file() or path.is_symlink():
            return None
        value=json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value,(dict,list)) else None
    except (OSError,ValueError,UnicodeError):
        return None

def shell(*args,timeout=10):
    try:
        return subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,
                              text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):
        return None

def service(unit):
    p=shell("systemctl","is-active",unit,timeout=4)
    return p.stdout.strip() if p else "unknown"

def pkg_import():
    sys.path.insert(0,str(APP))
    import wpp_nodes
    import wpp_subscriptions
    return wpp_nodes,wpp_subscriptions

def classify_node_error(exc):
    cause=getattr(exc,"__cause__",None)
    code=getattr(cause,"code",None)
    # Never output raw exception text, URLs, tokens or response bodies.
    if isinstance(code,int):
        return "HTTP "+str(code)
    if isinstance(cause,TimeoutError):
        return "TIMEOUT"
    if cause is not None:return type(cause).__name__
    return type(exc).__name__

def load_nodes(api):
    try:
        rows=api.load_nodes(str(NODE_DB))
        if not isinstance(rows,list):raise ValueError("invalid list")
        return rows
    except (OSError,ValueError,TypeError) as exc:
        finding("ERROR","NODE_REGISTRY",type(exc).__name__)
        return []

def check_nodes(api,rows):
    emit("\n=== 1. ВСЕ NODE API / TLS / POST-ВАЛИДАЦИЯ ===")
    seen=set()
    capabilities={}
    enabled={}
    summary=Counter()
    for idx,node in enumerate(rows,1):
        if not isinstance(node,dict):continue
        code=str(node.get("country_code") or "UN").upper()
        code=code if re.fullmatch(r"[A-Z]{2}",code) else "UN"
        uid=str(node.get("id",""))
        if uid in seen:finding("ERROR","DUPLICATE_NODE","Дублирующийся ID ноды")
        seen.add(uid)
        enabled[uid]=bool(node.get("enabled",True))
        emit("НОДА",idx,"страна",code,"включена",enabled[uid])
        if not enabled[uid]:continue
        caps_status=set()
        for suffix in ("/status","/federation/status","/federation/reality"):
            try:
                data=api.request(node,"GET",api.API_PREFIX+suffix,timeout=10)
                c=data.get("capabilities",[]) if isinstance(data,dict) else []
                if isinstance(c,list):
                    caps_status.update(x for x in c if isinstance(x,str))
                managed=(data.get("profile",{}).get("managed_reality")==
                         "remna-443-mirror-v1") if isinstance(data.get("profile"),dict) else False
                emit("  GET",suffix,"200","managed443" if managed else "")
                summary["get_ok"]+=1
            except Exception as exc:
                typ=classify_node_error(exc)
                emit("  GET",suffix,typ)
                summary["get_failed"]+=1
                finding("ERROR","NODE_GET","Нода "+str(idx)+": "+suffix+" -> "+typ)
        capabilities[uid]=caps_status
        # This ID fails the remote validator BEFORE anything is provisioned.
        # An HTTP 400 is the expected safe response.
        try:
            api.request(node,"POST",api.API_PREFIX+"/federation/sync",
                {"external_id":"BAD_ID_NO_WRITE","name":"WPO audit","protocols":["reality"]},timeout=10)
            finding("ERROR","INVALID_POST_ACCEPTED","Нода "+str(idx)+": недопустимый ID принят")
        except Exception as exc:
            status=classify_node_error(exc)
            emit("  POST sync с НЕВЕРНЫМ ID:",status,"(ожидается HTTP 400)")
            if status=="HTTP 400":summary["post_400"]+=1
            else:
                summary["post_bad"]+=1
                finding("ERROR","NODE_POST","Нода "+str(idx)+" вернула "+status)
        if "reality-direct-443" in caps_status:
            summary["managed443"]+=1
        emit("  VPN-capabilities:",
             ",".join(x for x in ("reality","vless","hysteria","reality-direct-443")
                      if x in caps_status) or "none")
    return capabilities,enabled,summary

def check_registry(registry,rows,caps,enabled,subscriptions):
    emit("\n=== 2. ОДИНОЧНЫЕ / МУЛЬТИПОДПИСКИ ===")
    data=safe_json(DB)
    if not isinstance(data,dict):
        finding("ERROR","USER_REGISTRY","Не получается прочитать users.json")
        return []
    subs=data.get("subscriptions",[])
    clients=data.get("users",[])
    if not isinstance(subs,list) or not isinstance(clients,list):
        finding("ERROR","REGISTRY_SCHEMA","users/subscriptions должны быть списками")
        return []
    subscribed={str(n.get("id")) for n in rows if isinstance(n,dict)}
    counters=Counter()
    selected_requests=[]
    if len(subs)>64:
        finding("ERROR","SUBSCRIPTION_CAPACITY","Более 64 подписок")
    if len(clients)>=256:
        finding("WARN","PROFILE_CAPACITY","Превышен или достигнут лимит 256 профилей")
    active_users=defaultdict(list)
    for c in clients:
        if isinstance(c,dict):
            active_users[(str(c.get("subscription_id","")),str(c.get("device_id","")))].append(c)
    for idx,sub in enumerate(subs,1):
        if not isinstance(sub,dict):
            finding("ERROR","SUB_SCHEMA","Запись "+str(idx)+" не объект")
            continue
        if not sub.get("enabled",True):
            counters["disabled"]+=1
            continue
        counters["enabled"]+=1
        nid=sub.get("node_ids",["local"])
        if not isinstance(nid,list):
            finding("ERROR","NODE_SELECTION","Подписка "+str(idx)+": node_ids не список")
            continue
        selected=list(dict.fromkeys(str(x) for x in nid))
        if len(selected)>1:counters["multi"]+=1
        else:counters["single"]+=1
        if len(nid)!=len(selected):
            finding("WARN","DUP_NODE","Подписка "+str(idx)+": дубли выбранных нод")
        missing=[n for n in selected if n!="local" and n not in subscribed]
        if missing:finding("ERROR","STALE_NODE","Подписка "+str(idx)+": выбрана удалённая нода")
        disconnected=[n for n in selected if n!="local" and not enabled.get(n,False)]
        if disconnected:finding("ERROR","DISABLED_NODE","Подписка "+str(idx)+": нода выключена")
        connections=sub.get("connections",[])
        if not isinstance(connections,list):
            finding("ERROR","CONNECTIONS","Подписка "+str(idx)+": неправильный формат connections")
            continue
        protocols=tuple(dict.fromkeys(
            str(c.get("protocol")) for c in connections
            if isinstance(c,dict) and c.get("protocol") in ("vless","reality","hysteria")))
        if not protocols:finding("WARN","NO_VPN_CONNECTIONS","Подписка "+str(idx)+" не содержит VPN-подключений")
        for nid in selected:
            if nid=="local":continue
            have=caps.get(nid,set())
            missing_cap=[p for p in protocols if p not in have]
            if missing_cap:
                finding("ERROR","NODE_CAPABILITY",
                        "Подписка "+str(idx)+": запрошены неподдерживаемые протоколы "+
                        ",".join(missing_cap))
        devices=sub.get("devices",[])
        if not isinstance(devices,list):
            finding("ERROR","DEVICES","Подписка "+str(idx)+": devices не список")
            continue
        sid=str(sub.get("id",""))
        for device in devices:
            if not isinstance(device,dict) or device.get("revoked"):continue
            did=str(device.get("id",""))
            records=active_users.get((sid,did),[])
            expected={str(c.get("id")) for c in connections if isinstance(c,dict)}
            actual={str(u.get("connection_id")) for u in records}
            if expected!=actual:
                counters["device_mismatch"]+=1
                if counters["device_mismatch"]<=8:
                    finding("ERROR","DEVICE_PROFILE_MISMATCH",
                        "Подписка "+str(idx)+": количество профилей устройства не совпадает")
        # issue(...) works on a DEEP COPY: no filesystem writes. For a shared
        # subscription it recreates first-fetch state in RAM and catches 503.
        token=sub.get("token")
        if (isinstance(token,str) and len(token)==64
            and int(sub.get("max_devices",0) or 0)==0):
            try:
                copy_db=copy.deepcopy(data)
                _,result=registry.issue(copy_db,{"token":token})
                if not result.get("ok"):raise ValueError("issue did not report ok")
                counters["dry_issue_ok"]+=1
            except Exception as exc:
                counters["dry_issue_bad"]+=1
                if counters["dry_issue_bad"]<=8:
                    finding("ERROR","LOCAL_ISSUE",
                        "Подписка "+str(idx)+": моделирование выдачи -> "+type(exc).__name__)
        for n in selected:
            if n!="local" and n in subscribed and enabled.get(n,False) and protocols:
                selected_requests.append((idx,n,protocols))
    emit("Подписок:",len(subs),"активных:",counters["enabled"],
         "одиночных:",counters["single"],"мульти:",counters["multi"],
         "клиентских профилей:",len(clients))
    emit("Локальная выдача в памяти: ОК",counters["dry_issue_ok"],
         "ошибки",counters["dry_issue_bad"],
         "несовпадение профилей",counters["device_mismatch"])
    return selected_requests

def check_prewarm(requests):
    emit("\n=== 3. ГДЕ ВОЗНИКАЕТ 503 ПРИ ВЫДАЧЕ ===")
    panel=APP/"panel.py"
    feed=APP/"wpo_happ_async_feed.py"
    prep=APP/"wpo_happ_preparer.py"
    text=panel.read_text(encoding="utf-8",errors="replace") if panel.is_file() else ""
    async_text=feed.read_text(encoding="utf-8",errors="replace") if feed.is_file() else ""
    has_pending=('Подписка готовится. Повторите обновление.' in text and
                 "wpo_happ_async_feed.collect" in text)
    emit("Код панели: 503 при ожидании удалённых профилей =",has_pending)
    emit("Асинхронная federation-синхронизация =",bool(async_text))
    if has_pending:finding("INFO","PENDING_503_BRANCH",
                           "При ожидании любой выбранной ноды панель возвращает 503 с Retry-After=2")
    if "RETRY_DELAY = 30" in async_text:
        emit("Повторная попытка после NodeError: 30 секунд")
    ready=safe_json(READY)
    if ready is None:
        finding("WARN","PREWARM_CACHE_MISSING","Нет файла предварительно подготовленных профилей")
        ready={}
    if not isinstance(ready,dict):
        finding("ERROR","PREWARM_BAD_FORMAT","happ-node-ready.json повреждён")
        ready={}
    emit("В кеше предварительной подготовки записей:",len(ready))
    if prep.is_file():
        try:
            import wpo_happ_preparer as pp
            jobs=pp.tasks()  # returns metadata only, no network POST or writes
            ages=[]
            now=int(time.time())
            for job in jobs:
                stamp=ready.get(job[0],0)
                if isinstance(stamp,int) and stamp>0:
                    ages.append(now-stamp)
            emit("Ожидаемых заданий:",len(jobs),
                 "подготовлено:",sum(x>=0 and x<600 for x in ages),
                 "неподготовлено:",len(jobs)-sum(x>=0 and x<600 for x in ages))
            if jobs and not ages:
                finding("WARN","NO_PREWARMED_NODES",
                        "Существуют удалённые подключения, но ни одно не отмечено как подготовленное")
        except Exception as exc:
            finding("ERROR","PREWARM_TASKS","Не удалось вычислить задания: "+type(exc).__name__)
    else:finding("WARN","PREWARM_MODULE_MISSING","Модуль предварительной подготовки не установлен")
    p=shell("systemctl","list-timers","--all","--no-pager","--no-legend",timeout=6)
    timers=[line for line in (p.stdout.splitlines() if p else [])
            if "happ" in line.lower() or "prepar" in line.lower()]
    emit("Таймеров предварительной подготовки:",len(timers))
    emit("Состояние панели:",service("tproxy-panel.service"))

def logs():
    emit("\n=== 4. ЖУРНАЛЫ 503 / NODEERROR / TRACEBACK (БЕЗ ДАННЫХ) ===")
    p=shell("journalctl","-u","tproxy-panel.service",
            "--since","-4h","--no-pager","-o","cat",timeout=16)
    if not p:
        finding("WARN","JOURNAL_UNAVAILABLE","Журнал панели недоступен")
        return
    content=p.stdout[-400000:]
    counters=Counter()
    exceptions=Counter()
    functions=Counter()
    all_lines=content.splitlines()
    for i,line in enumerate(all_lines):
        if "wpo asynchronous node sync failed:" in line:counters["async_NodeError"]+=1
        if "Подписка готовится" in line:counters["pending_sub"]+=1
        if "BrokenPipeError" in line:counters["BrokenPipeError"]+=1
        if re.search(r"\bHTTP(?: Error| status)?\s*:?\s*503\b",line):counters["HTTP503"]+=1
        m=re.match(r'^([A-Za-z_][A-Za-z0-9_.]{0,90}(?:Error|Exception|Interrupt))\s*:',line)
        if m:exceptions[m.group(1)]+=1
        if "Traceback (most recent call last)" in line:
            segment=all_lines[i+1:i+35]
            for stack in segment:
                m=re.search(r'File "[^"]+", line \d+, in ([A-Za-z_][A-Za-z_0-9]{0,70})',stack)
                if m:functions[m.group(1)]+=1
    emit("События:",dict(counters))
    emit("Типы исключений:",exceptions.most_common(7))
    emit("Функции из traceback:",functions.most_common(9))
    if counters["async_NodeError"]:
        finding("WARN","REMOTE_SYNC_ERRORS",
                str(counters["async_NodeError"])+" ошибок фоновой федерации; GET-статус ноды этого не выявляет")
    if counters["BrokenPipeError"]:
        finding("INFO","BROKEN_PIPE",
                "Обрыв ответа клиенту — вторичный симптом, не причина отказа Xray")

def summarize():
    emit("\n================ ИТОГ ================")
    counter=Counter(level for level,_,_ in issues)
    emit("Ошибок:",counter["ERROR"],"предупреждений:",counter["WARN"],
         "подсказок:",counter["INFO"])
    unique=set()
    for level,tag,desc in issues:
        if (level,tag) in unique:continue
        unique.add((level,tag))
        emit(level,tag,desc)
    emit("ОГРАНИЧЕНИЕ: полноценный POST с новым реальным клиентом намеренно НЕ выполняется.")
    emit("КОНЕЦ: файлы, подписки, API-токены и сервисы НЕ изменялись.")
    emit("======================================")

def main():
    import os
    if os.geteuid()!=0:raise RuntimeError("Запусти через sudo")
    if not (APP/"panel.py").is_file() or not DB.is_file():
        raise RuntimeError("Запускать на основной панели WPO, а не на ноде")
    emit("WPO ПОЛНАЯ ПРОВЕРКА ПОДПИСОК — ТОЛЬКО ЧТЕНИЕ")
    emit("Панель работает:",service("tproxy-panel.service"))
    api,subs_module=pkg_import()
    nodes=load_nodes(api)
    caps,enabled,summary=check_nodes(api,nodes)
    reqs=check_registry(subs_module,nodes,caps,enabled,None)
    check_prewarm(reqs)
    logs()
    summarize()

if __name__=="__main__":
    try:main()
    except Exception as exc:
        emit("DIAGNOSTIC FAILED:",type(exc).__name__,
             "(подробности скрыты, чтобы не раскрыть данные)")
        raise SystemExit(1)
