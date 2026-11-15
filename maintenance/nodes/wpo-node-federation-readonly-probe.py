#!/usr/bin/env python3
"""Read-only Node POST routing and Xray VLESS config preflight.

Use ON AN ADDITIONAL Node Agent VPS, never the main WPO. Does not change
user data, API tokens, running Xray, any on-disk configuration or services.
A deliberately invalid federation identity must be rejected with HTTP 400,
demonstrating that POST reaches the real sidecar behind Caddy.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
import uuid
import hashlib

AGENT=Path("/etc/wpp-node-agent/config.json")
APP=Path("/opt/wpp-node-agent/wpo_node_vpn.py")
ROOT=Path("/etc/wpp-node-vpn")
BIN=Path("/opt/web-panel-proxy/xray/xray")
KNOWN=("Invalid federation ID","VPN service is not ready","VPN provisioning failed",
       "Unauthorized","Not found")

def safe_status(uri, key):
    body=b'{"external_id":"invalid","name":"route-probe","protocols":["vless"]}'
    req=Request(uri,data=body,method="POST",headers={
        "Authorization":"Bearer "+key,
        "Accept":"application/json","Content-Type":"application/json"})
    try:
        with build_opener(ProxyHandler({})).open(req,timeout=8) as resp:
            code=resp.status
            raw=resp.read(1024)
    except HTTPError as exc:
        code=exc.code
        raw=exc.read(1024)
    except (URLError,OSError,TimeoutError) as exc:
        print("  Ошибка сети:",type(exc).__name__)
        return None
    try:
        value=json.loads(raw.decode("utf-8"))
        message=value.get("message","") if isinstance(value,dict) else ""
    except (ValueError,UnicodeDecodeError):
        message=""
    # Never print arbitrary server text (could leak values).
    label=next((x for x in KNOWN if x in message),"неизвестный ответ")
    print(f"  HTTP {code}; тип: {('JSON' if message else 'без JSON')}; причина: {label}")
    if code==400 and "Invalid federation ID" in message:
        print("  ✓ POST доходит до VPN Federation, пользователь не создан")
    elif code==503:
        print("  ! POST не дошёл до валидации или VPN-сервис отказал")
    return code

def check():
    if not AGENT.is_file() or not APP.is_file() or not BIN.is_file():
        print("Нужна дополнительная нода с установленным VPN Federation")
        return 2
    if Path("/opt/tproxy-panel/panel.py").exists():
        print("Это основная WPO. Изменений не сделано.")
        return 2
    conf=json.loads(AGENT.read_text(encoding="utf-8"))
    domain=conf["domain"]
    key=conf["api_key"]
    print("Нода:",domain)
    print("=== GET/POST не перепутаны: проверка ошибочного ID, без создания профилей ===")
    suffix="/wpp-api/v1/federation/sync"
    local=safe_status("http://127.0.0.1:9089"+suffix,key)
    public=safe_status("https://"+domain+suffix,key)
    print("=== Xray: безопасная проверка добавления одного VLESS-пользователя ===")
    sys.path.insert(0,str(APP.parent))
    import wpo_node_vpn as vpn
    try:
        state=vpn.read_json(vpn.STATE,{"profiles":{}}).get("profiles",{})
        if not isinstance(state,dict):raise ValueError("Invalid profiles state")
        clone=dict(state)
        ident=hashlib.sha256(("wpo-probe:"+domain).encode()).hexdigest()
        if ident in clone:
            print("  ! Предсказуемый ID уже занят, проверка остановлена.")
            return 3
        clone[ident]={"name":"WPO Readonly Probe","secrets":{"vless":str(uuid.uuid4())}}
        rendered=vpn.render_xray(clone,vpn.read_json(vpn.SETTINGS))
        with tempfile.TemporaryDirectory(prefix="wpo-config-preflight-") as temp:
            path=Path(temp)/"xray.json"
            path.write_text(json.dumps(rendered,separators=(",",":")),encoding="utf-8")
            os.chmod(path,0o600)
            test=subprocess.run([str(BIN),"run","-test","-config",str(path)],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                text=True,timeout=18)
            if test.returncode:
                print("  ✗ Тест Xray: отказ, код",test.returncode,
                      "(детали смотрите в журнале ноды)")
            else:
                print("  ✓ Xray принимает конфигурацию с VLESS")
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print("  ✗ Проверка конфигурации:",type(exc).__name__)
    print("=== Готовность локальных служб ===")
    for name in ("caddy.service","wpp-node-agent.service",
                 "wpo-node-vpn.service","wpo-node-xray.service"):
        proc=subprocess.run(["systemctl","is-active",name],capture_output=True,
                            text=True,timeout=7)
        status=proc.stdout.strip()
        print(" ",name,":",status if status in ("active","inactive","failed","activating") else "неизвестно")
    print("Ничего не изменено. Если оба POST дают 400, но реальное создание 503,")
    print("сбой происходит при применении профиля или записи его конфигурации.")
    return 0 if local==400 and public==400 else 3

if __name__=="__main__":
    if os.geteuid()!=0:
        raise SystemExit("Запустите sudo на дополнительной WPO-ноде.")
    raise SystemExit(check())
