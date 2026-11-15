"""Remote native WPO profiles (Telegram, AWG, Naive, Mieru).

Keeps the panel-side copy of *real* remote node credentials, never generates a
Telegram/AWG link before the authenticated node has provisioned its service.
The existing Happ subscription path handles VLESS and Hysteria2 separately.
"""
import copy
from html import escape
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time

import wpp_nodes as nodes

DATA = Path("/var/lib/tproxy-panel/remote-users.json")
NATIVE = frozenset(("web","mtproto","awg20","awg31","naive","mieru"))
ID = re.compile(r"^[a-f0-9]{32}$")
NODE_ID = re.compile(r"^[a-f0-9]{16}$")
TITLES = {
    "web": "WEB Proxy · Telegram", "mtproto": "MTProto · Telegram",
    "awg20": "AmneziaWG 2.0", "awg31": "AmneziaWG 3.1",
    "naive": "NaiveProxy", "mieru": "Mieru",
}


def load():
    try:
        data=json.loads(DATA.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"users":[]}
    if not isinstance(data,dict) or not isinstance(data.get("users"),list):
        raise ValueError("Corrupt WPO remote-user registry")
    return data


def save(data):
    DATA.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".wpo-rem-",dir=str(DATA.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,ensure_ascii=True,indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,DATA)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def node_by_id(registry,identifier):
    if not NODE_ID.fullmatch(str(identifier)):
        raise ValueError("Incorrect remote node")
    return next((n for n in registry if n.get("id")==identifier and
                 n.get("enabled",True)),None)


def create(node_id, name, protocol, registry, expiry=0):
    if protocol not in NATIVE:
        raise ValueError("Remote profile protocol is unsupported")
    if not isinstance(name,str) or not 1<=len(name)<=80 or any(ord(c)<32 for c in name):
        raise ValueError("Invalid remote profile name")
    node=node_by_id(registry,node_id)
    if node is None:
        raise ValueError("Selected remote node no longer exists")
    # This is a LIVE check. Never issue profile from cached UI capabilities.
    status=nodes.request(node,"GET",nodes.API_PREFIX+"/status",timeout=8)
    capabilities=status.get("capabilities",[])
    if (not status.get("ok") or not isinstance(capabilities,list) or
            "federation" not in capabilities or protocol not in capabilities):
        raise nodes.NodeError("На выбранной ноде протокол не установлен или не готов.")
    if expiry:
        try: deadline=int(expiry)
        except (TypeError,ValueError) as exc: raise ValueError("Incorrect expiry") from exc
        if deadline<=int(time.time())+59 or deadline>4102487999:
            raise ValueError("Incorrect future expiry")
    identifier=secrets.token_hex(16)
    external_id=secrets.token_hex(32)
    # First native service launch (especially Mieru/AWG) may be slower than
    # lightweight XHTTP provisioning. Only acknowledge success after the
    # additional VPS returns its committed real service configuration.
    answer=nodes.request(node,"POST",nodes.API_PREFIX+"/federation/sync",{
        "external_id":external_id,"name":name,"protocols":[protocol]
    },timeout=90)
    profiles=answer.get("profiles") if isinstance(answer,dict) else None
    if not isinstance(profiles,list) or len(profiles)!=1:
        try: nodes.delete_profile(node,external_id)
        except nodes.NodeError: pass
        raise nodes.NodeError("Нода не вернула созданный профиль.")
    profile=profiles[0]
    if not isinstance(profile,dict) or profile.get("protocol")!=protocol:
        try: nodes.delete_profile(node,external_id)
        except nodes.NodeError: pass
        raise nodes.NodeError("Нода вернула неверный тип профиля.")
    credential = profile.get("config") if protocol in ("awg20","awg31") else profile.get("link")
    if not isinstance(credential,str) or not credential or len(credential)>16384:
        try: nodes.delete_profile(node,external_id)
        except nodes.NodeError: pass
        raise nodes.NodeError("Нода не подтвердила рабочую ссылку/конфигурацию.")
    record={
        "id":identifier,"external_id":external_id,"node_id":node_id,
        "node_name":str(node.get("name") or node.get("country_name") or node.get("url") or "Нода")[:80],
        "name":name,"protocol":protocol, "credential":credential,
        "created_at":int(time.time()), "expires_at":int(expiry or 0),
        "enabled":True
    }
    state=load()
    state["users"].append(record)
    try:
        save(state)
    except Exception:
        try: nodes.delete_profile(node,external_id)
        except nodes.NodeError: pass
        raise
    return {k:v for k,v in record.items() if k not in ("credential","external_id")}


def remove(uid,registry):
    if not ID.fullmatch(str(uid)):
        raise ValueError("Invalid remote profile ID")
    state=load()
    record=next((r for r in state["users"] if r.get("id")==uid),None)
    if record is None:
        raise ValueError("Remote profile not found")
    node=node_by_id(registry,record["node_id"])
    if node is None:
        raise nodes.NodeError("Нода удалена из списка. Сначала восстановите её подключение.")
    # Do not erase the audit record if node cannot confirm revocation.
    reply=nodes.delete_profile(node,record["external_id"])
    if not reply.get("ok"):
        raise nodes.NodeError("Нода не подтвердила отзыв ключа.")
    state["users"]=[r for r in state["users"] if r.get("id")!=uid]
    save(state)
    return True


def config(uid):
    if not ID.fullmatch(str(uid)):
        raise ValueError("Invalid remote profile ID")
    record=next((r for r in load()["users"] if r.get("id")==uid),None)
    if not record or record.get("protocol") not in ("awg20","awg31"):
        raise ValueError("AWG configuration not found")
    return str(record["credential"]), "WPO-"+record["protocol"]+"-"+uid+".conf"


def cards(path, csrf):
    records=load()["users"]
    if not records:
        return ""
    h=lambda value:escape(str(value),quote=True)
    rendered=[]
    for r in records:
        uid=h(r.get("id","")); title=h(r.get("name","")); protocol=r.get("protocol","")
        if protocol not in NATIVE: continue
        node_name=h(r.get("node_name","Нода"))
        if protocol in ("awg20","awg31"):
            access=(
                f'<a class="primary" href="{h(path)}/remote-user-config?id={uid}">'
                'Скачать конфигурацию .conf</a>')
        else:
            access=(
                f'<button type="button" class="primary" data-remote-copy="{h(r.get("credential",""))}">'
                'Скопировать ссылку</button>')
        rendered.append(
            '<article class="card" style="padding:14px;margin:9px 0">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:8px">'
            f'<div><strong>{title}</strong><small style="display:block;opacity:.7">'
            f'{h(TITLES[protocol])} · {node_name}</small></div>'
            f'<div>{access}</div></div>'
            f'<form method="post" action="{h(path)}/remote-user-action" '
            'onsubmit="return confirm(&quot;Удалить удалённый профиль и отозвать ключ на ноде?&quot;)">'
            f'<input type="hidden" name="csrf" value="{h(csrf)}">'
            f'<input type="hidden" name="id" value="{uid}">'
            '<button type="submit" style="margin-top:6px">Удалить профиль</button></form>'
            '</article>'
        )
    return (
        '<section class="card" style="padding:16px;margin:15px 0">'
        '<h3>Подключения на дополнительных нодах</h3>'
        + "".join(rendered) +
        '</section>'
        '<script>(function(){document.querySelectorAll("[data-remote-copy]").forEach(function(button){'
        'button.addEventListener("click",async function(){'
        'try{await navigator.clipboard.writeText(button.dataset.remoteCopy);'
        'button.textContent="Скопировано";}catch(e){button.textContent="Не удалось скопировать";}'
        '});});})();</script>'
    )
