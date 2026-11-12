#!/bin/sh
# WPO 3.0 VPN diagnostics. Read-only. No configuration, service or firewall changes.
set -u
umask 077
if [ "$(id -u)" -ne 0 ]; then
  echo 'Запустите через sudo.' >&2
  exit 1
fi
python3 - <<'PY'
import json, os, re, shutil, socket, subprocess
from pathlib import Path
from collections import Counter

print("======== WPO VPN DIAGNOSTICS · READ ONLY ========")
def run(args, timeout=12):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", type(exc).__name__
def redacted(text):
    text = re.sub(r'(?i)(bearer|token|password|secret|private.?key|api.?key)\s*[:=]\s*\S+', r'\1=[HIDDEN]', text)
    text = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '[UUID]', text, flags=re.I)
    text = re.sub(r'(vless|hysteria2?)://\S+', '[LINK HIDDEN]', text, flags=re.I)
    return text[:230]
def json_file(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value, None
    except (OSError, ValueError) as exc:
        return {}, type(exc).__name__

print("\n[1] СЛУЖБЫ")
units = ["tproxy-panel.service", "web-panel-proxy-xray.service", "caddy.service",
         "web-panel-proxy-sync-tls.timer", "web-proxy-panel-firewall.service",
         "tproxy-server.service", "web-panel-proxy-tls-mux.service"]
for unit in units:
    rc, out, err = run(["systemctl", "is-active", unit], 5)
    status = (out.strip() or err.strip() or "unknown").splitlines()[0]
    print(f"{unit:44} {status}")

print("\n[2] КОНФИГУРАЦИЯ XRAY / КЛИЕНТЫ")
cfgpath="/etc/web-panel-proxy-xray/config.json"
cfg, err = json_file(cfgpath)
if err:
    print("Xray config:", err)
else:
    inbounds=cfg.get("inbounds",[])
    print("Xray inbounds:",len(inbounds) if isinstance(inbounds,list) else "invalid")
    expected=set()
    if isinstance(inbounds,list):
        for ib in inbounds:
            if not isinstance(ib,dict): continue
            port=ib.get("port","?")
            if isinstance(port,int):expected.add(port)
            stream=ib.get("streamSettings",{})
            sec=stream.get("security") if isinstance(stream,dict) else None
            net=stream.get("network") if isinstance(stream,dict) else None
            clients=ib.get("settings",{}).get("clients",[]) if isinstance(ib.get("settings",{}),dict) else []
            count=len(clients) if isinstance(clients,list) else "invalid"
            print("  %s / %s / %s / %s / %s clients / bind=%s"%
                  (str(ib.get("protocol"))[:18],str(net)[:14],str(sec)[:14],port,count,str(ib.get("listen","*"))[:18]))
    xray="/opt/web-panel-proxy/xray/xray"
    if Path(xray).is_file():
        rc,out,err=run([xray,"run","-test","-config",cfgpath], 35)
        print("Xray -test:", "PASS" if rc==0 else "FAIL ("+str(rc)+")")
        if rc: print("  error:",redacted((err or out).strip().splitlines()[-1] if (err or out).strip() else "unknown"))
    else: print("Xray binary: MISSING")
users,err=json_file("/etc/web-proxy-panel/users.json")
if err: print("Users file:",err)
else:
    items=users.get("users",[]) if isinstance(users,dict) else []
    if not isinstance(items,list): items=[]
    print("Enabled users by protocol:",dict(Counter(str(u.get("protocol","?")) for u in items if isinstance(u,dict) and u.get("enabled",True))))
conn,err=json_file("/etc/web-proxy-panel/connections.json")
if err: print("Connections registry:",err)
else:
    items=conn.get("connections",[]) if isinstance(conn,dict) else []
    print("Enabled connections by protocol:",dict(Counter(str(u.get("protocol","?")) for u in items if isinstance(u,dict) and u.get("enabled",True))))

print("\n[3] СЛУШАЮЩИЕ ПОРТЫ")
rc,out,err=run(["ss","-lntup"],8)
if rc: print("ss:",redacted(err.strip()))
else:
    watch={80,443,8443,8090,10085,18443,24443} | set(range(10000,10006))
    if "expected" in locals(): watch|=expected
    seen=0
    for line in out.splitlines():
        if not any(re.search(r'[:\]]'+str(n)+r'\b',line) for n in watch): continue
        cols=line.split()
        if len(cols)<5: continue
        print("  ",cols[0],cols[4],redacted(" ".join(cols[5:])))
        seen+=1
        if seen>=28:break
    if not seen:print("  На ожидаемых портах слушателей нет")

print("\n[4] CADDY / TLS")
caddy=Path("/etc/caddy/Caddyfile")
if caddy.exists():
    txt=caddy.read_text(encoding="utf-8",errors="replace")
    print("Caddyfile: present, XHTTP routes:",("YES" if "@web_panel_vless" in txt else "NO"),
          "probe:",("YES" if "__wpp_cdn_probe" in txt else "NO"))
    if shutil.which("caddy"):
        rc,out,err=run(["caddy","validate","--config",str(caddy),"--adapter","caddyfile"],20)
        print("Caddy validate:","PASS" if rc==0 else "FAIL")
        if rc: print("  ",redacted((err or out).strip().splitlines()[-1] if (err or out).strip() else "unknown"))
else:print("Caddyfile: MISSING")
cert=Path("/etc/web-panel-proxy-xray/tls/domain.crt")
key=Path("/etc/web-panel-proxy-xray/tls/domain.key")
print("Hysteria TLS certificate:",cert.exists(),"private key present:",key.exists())
if cert.exists() and shutil.which("openssl"):
    rc,out,err=run(["openssl","x509","-noout","-enddate","-in",str(cert)],10)
    print("Hysteria TLS expiry:",out.strip() if rc==0 else "INVALID")

print("\n[5] СЕТЬ / DNS / HTTPS")
domain=""
file=Path("/etc/systemd/system/caddy.service.d/tproxy.conf")
if file.exists():
    for line in file.read_text(encoding="utf-8",errors="replace").splitlines():
        if line.startswith("Environment=TPROXY_HOSTNAME="):
            domain=line.split("=",2)[-1].strip().strip('"').lower()
            break
print("Panel domain configured:",bool(domain))
try:
    a={item[4][0] for item in socket.getaddrinfo(socket.gethostname(),None,family=socket.AF_INET)}
except OSError:a=set()
rc,out,err=run(["hostname","-I"],4)
server_ips=set((out or "").split())
print("Server IPv4:",", ".join(sorted(ip for ip in server_ips if ":" not in ip)) or "n/a")
if domain and re.fullmatch(r"[a-z0-9.-]+",domain):
    try:
        dns=sorted({row[4][0] for row in socket.getaddrinfo(domain,443,family=socket.AF_INET,type=socket.SOCK_STREAM)})
        print("Panel DNS A:",", ".join(dns) or "none")
        print("DNS matches server IPv4:",bool(set(dns)&server_ips))
    except OSError as exc:print("Panel DNS A lookup: FAIL")
    if shutil.which("curl"):
        for title,more,url in [
            ("Caddy LOCAL HTTPS probe",["-k","--resolve",domain+":443:127.0.0.1"],"https://"+domain+"/__wpp_cdn_probe"),
            ("Public HTTPS probe",[],"https://"+domain+"/__wpp_cdn_probe")]:
            rc,out,err=run(["curl","-4","-sS","-o","/dev/null","-w","%{http_code}",
                            "--connect-timeout","5","--max-time","9"]+more+[url],11)
            print(title+":",("HTTP "+out.strip() if rc==0 else "ERROR "+str(rc)))
if shutil.which("curl"):
    rc,out,err=run(["curl","-4","-sS","-o","/dev/null","-w","%{http_code}",
                    "--connect-timeout","5","--max-time","9","https://example.com/"],11)
    print("VPS outbound HTTPS:",("HTTP "+out.strip() if rc==0 else "ERROR "+str(rc)))

print("\n[6] ФАЙРВОЛ")
if shutil.which("ufw"):
    rc,out,err=run(["ufw","status"],8)
    first=out.strip().splitlines()
    print("UFW:", first[0] if first else "not reported")
    if first and "active" in first[0] and "inactive" not in first[0]:
        for spec in ("443/tcp","8443/udp"):
            print("  "+spec+":", "rule found" if any(spec in row for row in first) else "not explicitly allowed")
if shutil.which("nft"):
    for name in ("web_proxy_panel","web_proxy_awg"):
        rc,out,err=run(["nft","list","table","inet" if name=="web_proxy_panel" else "ip",name],8)
        print("nft table "+name+":","present" if rc==0 else "MISSING")
rc,out,err=run(["ip","-4","route","show","default"],5)
print("Default IPv4 route:", "present" if rc==0 and out.strip() else "MISSING")

print("\n[7] ПОСЛЕДНИЕ ОШИБКИ СЛУЖБ (без секретов)")
regex=re.compile(r"error|fail|panic|permission|denied|refused|certificate|invalid|timeout|bind|fatal|handshake|connection closed",re.I)
for unit in ["web-panel-proxy-xray.service","caddy.service","tproxy-panel.service"]:
    rc,out,err=run(["journalctl","-u",unit,"-n","90","--no-pager","-o","cat"],12)
    lines=[redacted(v.strip()) for v in out.splitlines() if regex.search(v)]
    print(unit+":",len(lines),"matched lines, showing last 5")
    for line in lines[-5:]: print("  ",line)
print("\n======== END · NO CHANGES MADE ========")
PY
