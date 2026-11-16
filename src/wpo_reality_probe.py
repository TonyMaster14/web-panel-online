"""Read-only end-to-end REALITY target probe using ephemeral Xray processes.

TLS 1.3/HTTP2 alone can pass even when REALITY fails with an 8192-byte
certificate record. A green result requires HTTP 204 THROUGH VLESS Vision.
No live services, keys, profile files or listening ports are modified.
"""
import copy
import grp
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from uuid import uuid4

XRAY="/opt/web-panel-proxy/xray/xray"
URL="https://www.gstatic.com/generate_204"

class ProbeError(ValueError):
    pass

def local_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]

def probe(host, fingerprint, reality, timeout=12):
    """Return factual stages and measured HTTPS roundtrip, never invented ping."""
    checks=[{"name":"TLS 1.3 / HTTP/2","status":"ok","detail":"Сертификат и ALPN подтверждены"}]
    profile=dict(reality.read_profile(),sni=host,fingerprint=fingerprint)
    if not reality.PRIVATE.is_file():
        raise ProbeError("На ноде отсутствует приватный ключ REALITY")
    user_id=str(uuid4())
    server_port=local_port()
    socks_port=local_port()
    if socks_port==server_port:socks_port=local_port()
    server_inbound=reality.inbound([{"id":user_id,"flow":"xtls-rprx-vision","level":0}],profile)
    server_inbound["listen"]="127.0.0.1"
    server_inbound["port"]=server_port
    server={"log":{"loglevel":"error"},"inbounds":[server_inbound],
            "outbounds":[{"protocol":"freedom"}]}
    client={"log":{"loglevel":"error"},"inbounds":[{"listen":"127.0.0.1",
            "port":socks_port,"protocol":"socks","settings":{"auth":"noauth"}}],
            "outbounds":[{"protocol":"vless",
                "settings":{"vnext":[{"address":"127.0.0.1","port":server_port,
                        "users":[{"id":user_id,"encryption":"none","flow":"xtls-rprx-vision"}]}]},
                "streamSettings":{"network":"tcp","security":"reality",
                    "realitySettings":{"serverName":host,
                        "fingerprint":fingerprint,
                        "publicKey":profile["public_key"],
                        "shortId":profile["short_id"]}}}]}
    procs=[]
    with tempfile.TemporaryDirectory(prefix="wpo-reality-verify-") as td:
        root=Path(td)
        try:
            uid=0;gid=0
            try:
                account=grp.getgrnam("xray")
                gid=account.gr_gid
                import pwd
                user=pwd.getpwnam("xray")
                uid=user.pw_uid
            except KeyError:pass
            if uid:
                os.chown(root,0,gid)
                root.chmod(0o750)
            def start(name,config):
                path=root/(name+".json")
                path.write_text(json.dumps(config),encoding="utf-8")
                path.chmod(0o640 if uid else 0o600)
                if uid:os.chown(path,0,gid)
                log=(root/(name+".log")).open("w")
                if uid:
                    os.chown(root/(name+".log"),0,gid)
                    (root/(name+".log")).chmod(0o660)
                try:
                    p=subprocess.Popen([XRAY,"run","-config",str(path)],
                                        stdout=log,stderr=log,
                                        user=uid if uid else None,
                                        group=gid if uid else None)
                except Exception:
                    log.close();raise
                procs.append((p,log))
                time.sleep(.4)
                if p.poll() is not None:
                    raise ProbeError("Временный Xray не запустился: "+name)
            start("server",server)
            start("client",client)
            response=None
            for i in range(2):
                try:
                    response=subprocess.run(["curl","-4","--noproxy","","-sS",
                        "--socks5-hostname","127.0.0.1:"+str(socks_port),
                        "--connect-timeout","4","--max-time",str(timeout),
                        "-o","/dev/null","-w","%{http_code} %{time_total}",
                        URL],capture_output=True,text=True,timeout=timeout+3)
                except (OSError,subprocess.TimeoutExpired) as exc:
                    raise ProbeError("REALITY-туннель: ошибка проверки соединения") from exc
                parts=response.stdout.strip().split()
                if response.returncode==0 and len(parts)==2 and parts[0]=="204":
                    ms=round(float(parts[1])*1000)
                    checks.append({"name":"REALITY Vision","status":"ok",
                                   "detail":"Рукопожатие и VLESS-подключение работают"})
                    checks.append({"name":"HTTPS через туннель","status":"ok",
                                   "detail":"HTTP 204 · "+str(ms)+" мс"})
                    return {"ok":True,"checks":checks,"latency_ms":ms,
                            "message":"Цель REALITY доступна: туннель проверен"}
                if i==0:time.sleep(.5)
            raise ProbeError("TLS доступен, но REALITY-туннель не работает (HTTP 204 не получен). Попробуйте другую цель.")
        finally:
            for proc,log in reversed(procs):
                if proc.poll() is None:proc.terminate()
                try:proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=2)
                log.close()
