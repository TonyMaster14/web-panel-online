#!/usr/bin/env python3
"""Read-only smoke probe: a real VPN HTTPS/204 over every supported SNI.

Run ONLY after candidate Xray/HAProxy configs have been activated. Real
subscribed VLESS UUID is read locally and never printed or sent to the
controller. A failure exits nonzero so the host updater restores backups.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

PROFILE=Path("/etc/web-proxy-panel/reality/profile.json")
NODE=Path("/etc/wpp-node-vpn/xray.json")
PANEL=Path("/etc/web-panel-proxy-xray/config.json")
XRAY="/opt/web-panel-proxy/xray/xray"
SITES=("www.nvidia.com","www.apple.com","www.yahoo.com")
CHECK_URL="https://www.gstatic.com/generate_204"

def random_port():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]

def try_sni(host,profile,uuid):
    port=random_port()
    cfg={"log":{"loglevel":"error"},
         "inbounds":[{"listen":"127.0.0.1","port":port,"protocol":"socks",
                      "settings":{"auth":"noauth"}}],
         "outbounds":[{"protocol":"vless",
            "settings":{"vnext":[{"address":"127.0.0.1","port":443,
               "users":[{"id":uuid,"encryption":"none","flow":"xtls-rprx-vision"}]}]},
            "streamSettings":{"network":"tcp","security":"reality",
                "realitySettings":{"serverName":host,"fingerprint":profile["fingerprint"],
                     "publicKey":profile["public_key"],"shortId":profile["short_id"]}}}]}
    with tempfile.TemporaryDirectory(prefix="wpo-reality-compat-smoke-") as td:
        file=Path(td)/"probe.json"
        file.write_text(json.dumps(cfg))
        file.chmod(0o600)
        process=None
        try:
            process=subprocess.Popen([XRAY,"run","-config",str(file)],
                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(.45)
            if process.poll() is not None:return False
            for attempt in range(2):
                try:
                    result=subprocess.run(["curl","-4","--noproxy","","-sS",
                            "--socks5-hostname","127.0.0.1:"+str(port),
                            "--connect-timeout","4","--max-time","8",
                            "-o","/dev/null","-w","%{http_code}",
                            CHECK_URL],capture_output=True,text=True,timeout=11)
                    if result.returncode==0 and result.stdout.strip()=="204":return True
                except (OSError,subprocess.TimeoutExpired):
                    pass
                if attempt==0:time.sleep(.25)
            return False
        finally:
            if process is not None:
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=2)

def main():
    if os.geteuid()!=0:
        print("Smoke probe requires root",file=sys.stderr);return 2
    installed=NODE if NODE.is_file() else PANEL
    if not installed.is_file() or not PROFILE.is_file():
        print("Missing REALITY configuration",file=sys.stderr);return 2
    profile=json.loads(PROFILE.read_text())
    config=json.loads(installed.read_text())
    inbounds=[x for x in config.get("inbounds",[])
              if x.get("streamSettings",{}).get("security")=="reality"]
    hosts={x.get("streamSettings",{}).get("realitySettings",{}).get("serverNames",[None])[0]
           for x in inbounds}
    expected=set(SITES)|{profile["sni"]}
    if not expected.issubset(hosts):
        print("Some SNI backends are missing",file=sys.stderr);return 3
    users=next((x.get("settings",{}).get("clients",[]) for x in inbounds
                if x.get("settings",{}).get("clients")),[])
    client=next((x for x in users if x.get("flow")=="xtls-rprx-vision" and isinstance(x.get("id"),str)),None)
    if client is None:
        # Before a subscription is created, there can be no real UUID to test.
        print("Нет активных REALITY клиентов: конфигурация проверена, живой туннель пока проверить нельзя.")
        return 0
    for host in sorted(expected):
        if not try_sni(host,profile,client["id"]):
            print("REALITY handshake/HTTP 204 failed: "+host,file=sys.stderr)
            return 4
        print("✓ "+host+": REALITY Vision → HTTP 204",flush=True)
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print("REALITY smoke probe stopped: "+type(exc).__name__,file=sys.stderr)
        sys.exit(5)
