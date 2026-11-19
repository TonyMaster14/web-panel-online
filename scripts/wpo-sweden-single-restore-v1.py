#!/usr/bin/env python3
"""WPO controller: Swedish single-node HAPP restoration and verified federation sync."""
import ast, datetime, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, traceback
APP=pathlib.Path("/opt/tproxy-panel")
DATA=pathlib.Path("/etc/web-proxy-panel/users.json")
NODES=pathlib.Path("/var/lib/tproxy-panel/nodes.json")
SERVICE="tproxy-panel.service"
def out(*a): print(*a,flush=True)
def run(*args,timeout=40):
    return subprocess.run(list(args),capture_output=True,text=True,timeout=timeout)
def patch(text,old,new,label):
    if new in text: return text
    if text.count(old)!=1: raise RuntimeError(label+": unexpected source code, aborting")
    return text.replace(old,new,1)
def replace(path,text):
    s=path.stat()
    fd,name=tempfile.mkstemp(prefix=".wpo-se-restore-",dir=path.parent)
    try:
        with os.fdopen(fd,"w") as f: f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(name,s.st_mode & 0o7777);os.chown(name,s.st_uid,s.st_gid);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
def node_test():
    sys.path.insert(0,str(APP))
    import wpp_nodes as api
    import wpo_xray_modes as modes
    from urllib.parse import urlparse
    nodes=api.load_nodes(NODES)
    se=[n for n in nodes if str(n.get("id",""))=="780edba3e61e98a4"
        or str(n.get("country_code","")).upper()=="SE"
        or "swejeep.goodarielservice.xyz"==urlparse(str(n.get("url",""))).hostname]
    if len(se)!=1:
        out("SWEDEN: unique target not found:",len(se));return False
    node=se[0]
    out("SWEDEN: node selected, active=",bool(node.get("enabled",True)),"country=",str(node.get("country_code","")),"flag=",api.flag("SE"))
    try:
        status=api.request(node,"GET",api.API_PREFIX+"/status",timeout=15)
        out("SWEDEN NODE API: OK, status keys:",",".join(sorted(status.keys())[:18]))
    except Exception as exc:
        cause=getattr(exc,"__cause__",None)
        out("SWEDEN NODE API: FAILED",type(exc).__name__,"HTTP",getattr(cause,"code","unknown"))
        return False
    data=json.loads(DATA.read_text())
    subs=data.get("subscriptions",[])
    candidates=[s for s in subs if s.get("enabled",True) and str(node.get("id")) in s.get("node_ids",[])]
    candidates.sort(key=lambda s:(len(s.get("node_ids",[]))!=1,len(s.get("node_ids",[]))))
    if not candidates:
        out("SWEDEN: no enabled subscription selects this node; no customer data changed")
        return False
    sub=candidates[0]
    devices=[d for d in sub.get("devices",[]) if isinstance(d,dict) and not d.get("revoked")]
    if not devices:
        out("SWEDEN: no allocated device in existing subscription")
        return False
    device=devices[0]
    sid=str(sub.get("id",""));did=str(device.get("id",""))
    if not re.fullmatch("[a-f0-9]{16}",sid) or not re.fullmatch("[a-f0-9]{16}",did):
        out("SWEDEN: invalid subscription/device id; stopped");return False
    env=run("systemctl","show","-p","Environment","--value",SERVICE).stdout
    import shlex
    domain=next((x.split("=",1)[1] for x in shlex.split(env) if x.startswith("WEBPROXY_DOMAIN=")),"")
    if not domain or "." not in domain:out("SWEDEN: panel domain not available");return False
    external=hashlib.sha256((domain.lower()+":"+sid+":"+did).encode()).hexdigest()
    wanted=tuple(dict.fromkeys(c.get("protocol") for c in sub.get("connections",[]) if isinstance(c,dict) and c.get("protocol") in ("vless","reality","hysteria")))
    selected=modes.select_for_node(node,wanted)
    out("SWEDEN: existing subscription nodes=",len(sub.get("node_ids",[])),"protocols=",",".join(selected))
    if not selected:out("SWEDEN: no compatible active protocol");return False
    try:
        import wpo_happ_async_feed as feed
        links=feed.verified_links(api,node,external,api.location_prefix(node),selected,timeout=90)
        out("SWEDEN SYNC: SUCCESS, verified VPN links=",len(links),"schemes=",",".join(x.split(":",1)[0] for x in links))
        return True
    except Exception as exc:
        cause=getattr(exc,"__cause__",None)
        code=getattr(cause,"code",None)
        out("SWEDEN SYNC: FAILED",type(exc).__name__,"HTTP",code if code is not None else "unknown")
        if code is not None:
            try:
                content=cause.read(4096).decode(errors="replace")
                obj=json.loads(content)
                msg=str(obj.get("message","")) if isinstance(obj,dict) else ""
                categories=["Xray configuration validation failed","Xray did not become ready","Node engine command failed","VPN service is not ready","Node protocols not ready","Invalid federation ID","permission denied"]
                for x in categories:
                    if x.lower() in msg.lower():out("SWEDEN REASON:",x)
            except Exception:pass
        return False
def main():
    if os.geteuid()!=0:raise RuntimeError("use sudo")
    panel=APP/"panel.py";prep=APP/"wpo_happ_preparer.py"
    original={p:p.read_text() for p in (panel,prep)}
    code=original[panel]
    code=patch(code,'                if pending:\n                    self.send_data("Подписка готовится. Повторите обновление.",503,headers={"Retry-After":"2"}); return\n                lines.extend(remote_links)',
        '                if pending and not (lines or remote_links):\n                    self.send_data("Подписка готовится. Повторите обновление.",503,headers={"Retry-After":"2"}); return\n                lines.extend(remote_links)',"pending guard")
    code=patch(code,'            failover=bool(subscription.get("failover_enabled",True)) and len(chosen)>1',
        '            failover=bool(subscription.get("failover_enabled",True)) and len(distinct_nodes)>1',"failover")
    code=patch(code,'        except Exception:\n            self.send_data("Подписка временно недоступна.",503)',
        '        except Exception as exc:\n            _tb=traceback.extract_tb(exc.__traceback__)\n            _loc=_tb[-1] if _tb else None\n            print("WPO subscription exception:",type(exc).__name__,os.path.basename(_loc.filename) if _loc else "unknown",_loc.lineno if _loc else 0,file=sys.stderr,flush=True)\n            self.send_data("Подписка временно недоступна.",503)',"subscription error logging")
    if 'import traceback\n' not in code:code='import traceback\n'+code if not code.startswith("#!") else code.replace("\n","\nimport traceback\n",1)
    ast_tree=ast.parse(code)
    global_reality=any(isinstance(n,ast.Import) and any(a.name=="wpo_reality" for a in n.names) for n in ast_tree.body)
    if global_reality:
        line_numbers=set()
        for n in ast.walk(ast_tree):
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                for c in ast.walk(n):
                    if isinstance(c,ast.Import) and len(c.names)==1 and c.names[0].name=="wpo_reality":line_numbers.add(c.lineno)
        if line_numbers:
            lines=code.splitlines(keepends=True)
            for lineno in line_numbers:
                old=lines[lineno-1]
                if not re.fullmatch(r"\s+import wpo_reality\s*\n?",old):raise RuntimeError("unexpected local REALITY import")
                lines[lineno-1]=old[:len(old)-len(old.lstrip())]+"pass # global wpo_reality already imported\n"
            code="".join(lines)
    source=original[prep]
    source=patch(source,"import wpo_happ_async_feed as feed\n","import wpo_happ_async_feed as feed\nimport wpo_xray_modes\n","preparer imports")
    source=patch(source,'                digest=hashlib.sha256(\n                    (ext+":"+uid+":"+str(node.get("url",""))+":"+",".join(protocols)).encode()\n                ).hexdigest()\n                jobs.append((digest,node,ext,api.location_prefix(node),protocols))',
        '                node_protocols=tuple(wpo_xray_modes.select_for_node(node,protocols))\n                if not node_protocols:continue\n                digest=hashlib.sha256(\n                    (ext+":"+uid+":"+str(node.get("url",""))+":"+",".join(node_protocols)).encode()\n                ).hexdigest()\n                jobs.append((digest,node,ext,api.location_prefix(node),node_protocols))',"node protocol match")
    for p,s in ((panel,code),(prep,source)):compile(s,str(p),"exec")
    changed={panel:code,prep:source}
    backup=pathlib.Path("/var/backups/web-panel-online")/("sweden-sub-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(parents=True,mode=0o700)
    for p in changed:shutil.copy2(p,backup/p.name)
    out("BACKUP:",backup)
    touched=[]
    try:
        for p,s in changed.items():
            if s!=original[p]:replace(p,s);touched.append(p)
        if touched:
            r=run("systemctl","restart",SERVICE,timeout=35)
            if r.returncode:raise RuntimeError("panel restart failed")
        if run("systemctl","is-active","--quiet",SERVICE).returncode:raise RuntimeError("panel not active")
        out("PANEL: ACTIVE; local patch applied, other node configurations untouched")
    except Exception:
        for p in touched:shutil.copy2(backup/p.name,p)
        run("systemctl","restart",SERVICE,timeout=35)
        out("ROLLBACK: original files restored")
        raise
    ok=node_test()
    out("RESULT:","SWEDEN FEDERATION READY" if ok else "SWEDEN FEDERATION NOT READY - node API failure must be corrected separately")
    if not ok:sys.exit(3)
if __name__=="__main__":
    try:main()
    except Exception as exc:
        out("RESTORE FAILED:",type(exc).__name__,str(exc)[:160]);sys.exit(2)
