#!/usr/bin/env python3
"""WPO Node VPN federation. No VPN capability is advertised before Xray is live.

This is a separate localhost-only service: the existing Node Agent continues
to serve site templates, while the controller provisions XHTTP/Hysteria2 here.
"""
import argparse
import copy
import fcntl
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlencode

NODE_CONFIG = Path("/etc/wpp-node-agent/config.json")
ROOT = Path("/etc/wpp-node-vpn")
SETTINGS = ROOT / "settings.json"
STATE = ROOT / "profiles.json"
XRAY = ROOT / "xray.json"
CERT = ROOT / "tls" / "certificate.crt"
KEY = ROOT / "tls" / "private.key"
LOCK = ROOT / ".federation.lock"
XRAY_BIN = "/opt/web-panel-proxy/xray/xray"
UNIT = "wpo-node-xray.service"
SUPPORTED = frozenset(("vless", "hysteria"))
IDENTIFIER = re.compile(r"^[a-f0-9]{64}$")
VALID_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError("JSON must be an object")
        return value
    except FileNotFoundError:
        if default is not None:
            return copy.deepcopy(default)
        raise


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".wpo-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def command(*args, timeout=30):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)


def valid_params(data):
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    external_id = str(data.get("external_id", ""))
    name = data.get("name")
    protocols = data.get("protocols")
    if not IDENTIFIER.fullmatch(external_id):
        raise ValueError("Invalid federation ID")
    if not isinstance(name, str) or not VALID_NAME.fullmatch(name.strip()):
        raise ValueError("Invalid profile name")
    if not isinstance(protocols, list) or not protocols or len(protocols) > 2:
        raise ValueError("Select supported VPN protocols")
    if any(not isinstance(p, str) or p not in SUPPORTED for p in protocols):
        raise ValueError("VPN protocols supported here: VLESS XHTTP and Hysteria2")
    return external_id, name.strip(), sorted(set(protocols))


def render_xray(state, settings):
    domain = settings["domain"]
    path = settings["xhttp_path"]
    vless, hysteria = [], []
    for external_id, item in state.items():
        if not IDENTIFIER.fullmatch(external_id):
            raise ValueError("Invalid stored federation ID")
        if not isinstance(item, dict):
            raise ValueError("Invalid stored profile")
        for protocol, secret in item.get("secrets", {}).items():
            if protocol not in SUPPORTED:
                raise ValueError("Invalid stored protocol")
            try:
                canonical = str(uuid.UUID(str(secret)))
            except (ValueError, AttributeError) as exc:
                raise ValueError("Invalid stored VPN key") from exc
            if canonical != secret:
                raise ValueError("Noncanonical VPN key")
            if protocol == "vless":
                vless.append({"id": secret, "email": "node:" + external_id, "level": 0})
            else:
                hysteria.append({"auth": secret, "email": "node:" + external_id, "level": 0})
    inbounds = []
    if vless:
        inbounds.append({
            "tag": "wpo-vless-xhttp", "listen": "127.0.0.1", "port": 19000,
            "protocol": "vless", "settings": {"clients": vless, "decryption": "none"},
            "streamSettings": {"network": "xhttp", "security": "none",
                               "xhttpSettings": {"path": path, "mode": "auto"}},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"],
                         "routeOnly": True}
        })
    if hysteria:
        if not CERT.is_file() or not KEY.is_file():
            raise RuntimeError("Hysteria2 TLS certificate is missing")
        inbounds.append({
            "tag": "wpo-hysteria2", "listen": "0.0.0.0", "port": 8443,
            "protocol": "hysteria", "settings": {"version": 2, "clients": hysteria},
            "streamSettings": {"network": "hysteria", "security": "tls",
                               "tlsSettings": {"alpn": ["h3"], "minVersion": "1.3",
                                               "certificates": [{
                                                   "certificateFile": str(CERT),
                                                   "keyFile": str(KEY)
                                               }]},
                               "hysteriaSettings": {"version": 2, "udpIdleTimeout": 60}},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"],
                         "routeOnly": True}
        })
    return {"log": {"loglevel": "warning"}, "inbounds": inbounds,
            "outbounds": [{"tag": "direct", "protocol": "freedom"}]}


def link(protocol, secret, name, settings):
    domain = settings["domain"]
    title = quote(name + (" · XHTTP" if protocol == "vless" else " · Hysteria2"), safe="")
    if protocol == "vless":
        q = urlencode({"encryption": "none", "security": "tls", "sni": domain,
                       "fp": "chrome", "type": "xhttp", "host": domain,
                       "path": settings["xhttp_path"], "mode": "auto", "alpn": "h2"})
        return "vless://" + secret + "@" + domain + ":443?" + q + "#" + title
    q = urlencode({"sni": domain, "alpn": "h3"})
    return "hysteria2://" + secret + "@" + domain + ":8443/?" + q + "#" + title


def live():
    for unit in (UNIT, "caddy.service"):
        try:
            if command("systemctl", "is-active", "--quiet", unit, timeout=3).returncode:
                return False
        except (OSError, subprocess.TimeoutExpired):
            return False
    return CERT.is_file() and KEY.is_file() and XRAY.is_file()


def apply(state):
    settings = read_json(SETTINGS)
    config = render_xray(state, settings)
    previous = XRAY.read_bytes() if XRAY.is_file() else None
    atomic_json(XRAY, config)
    # The Xray daemon runs as a locked-down xray user, not root.
    import grp
    os.chown(XRAY, 0, grp.getgrnam("xray").gr_gid)
    os.chmod(XRAY, 0o640)
    try:
        result = command(XRAY_BIN, "run", "-test", "-config", str(XRAY), timeout=15)
        if result.returncode:
            raise RuntimeError("Xray configuration validation failed: " + result.stderr[-600:])
        result = command("systemctl", "restart", UNIT, timeout=30)
        if result.returncode or not live():
            raise RuntimeError("Xray did not become ready")
    except Exception:
        if previous is None:
            XRAY.unlink(missing_ok=True)
        else:
            fd, tmp = tempfile.mkstemp(dir=str(XRAY.parent))
            with os.fdopen(fd, "wb") as f:
                f.write(previous)
            os.chmod(tmp, 0o600)
            os.replace(tmp, XRAY)
            command("systemctl", "restart", UNIT, timeout=30)
        raise


def mutate(operation, data):
    # A process lock guards against parallel subscription imports and updates.
    LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(LOCK, "a+", encoding="ascii") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        before = read_json(STATE, {"profiles": {}})
        profiles = before.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("Invalid profile registry")
        updated = copy.deepcopy(profiles)
        if operation == "sync":
            external_id, name, protocols = valid_params(data)
            old = updated.get(external_id, {})
            keys = old.get("secrets", {}) if isinstance(old, dict) else {}
            secrets_by_protocol = {
                p: (keys[p] if p in keys else str(uuid.uuid4())) for p in protocols
            }
            updated[external_id] = {"name": name, "secrets": secrets_by_protocol}
        elif operation == "delete":
            external_id = str(data.get("external_id", ""))
            if not IDENTIFIER.fullmatch(external_id):
                raise ValueError("Invalid federation ID")
            updated.pop(external_id, None)
        elif operation == "purge":
            updated.clear()
        else:
            raise ValueError("Unknown operation")
        if updated != profiles:
            apply(updated)  # Never persist a broken server configuration.
            atomic_json(STATE, {"profiles": updated})
        if operation == "sync":
            item = updated[external_id]
            settings = read_json(SETTINGS)
            return {"ok": True, "profiles": [
                {"protocol": p, "link": link(p, item["secrets"][p], name, settings)}
                for p in protocols
            ]}
        if operation == "delete":
            return {"ok": True, "deleted": external_id in profiles}
        return {"ok": True, "deleted": len(profiles)}


class API(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        bearer = self.headers.get("Authorization", "")
        key = read_json(NODE_CONFIG)["api_key"]
        return bearer.startswith("Bearer ") and hmac.compare_digest(bearer[7:].strip(), key)

    def do_GET(self):
        if self.path == "/healthz":
            self.respond({"ok": live()})
        elif self.path == "/wpp-api/v1/federation/status":
            if not self.authorized():
                self.respond({"ok": False}, 401)
            else:
                self.respond({"ok": live(), "capabilities": ["federation", "vless", "hysteria"] if live() else []})
        else:
            self.respond({"ok": False}, 404)

    def do_POST(self):
        if self.path not in ("/wpp-api/v1/federation/sync",
                             "/wpp-api/v1/federation/delete",
                             "/wpp-api/v1/federation/purge"):
            self.respond({"ok": False}, 404)
            return
        if not self.authorized():
            self.respond({"ok": False, "message": "Unauthorized"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 2 <= length <= 8192:
                self.respond({"ok": False, "message": "Invalid JSON size"}, 413)
                return
            data = json.loads(self.rfile.read(length))
            if not live():
                self.respond({"ok": False, "message": "VPN service is not ready"}, 503)
                return
            operation = self.path.rsplit("/", 1)[-1]
            self.respond(mutate(operation, data))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.respond({"ok": False, "message": str(exc)[:180]}, 400)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.respond({"ok": False, "message": "VPN provisioning failed: " + str(exc)[:160]}, 503)


def sync_tls():
    settings = read_json(SETTINGS)
    domain = settings["domain"]
    source = Path("/var/lib/caddy/.local/share/caddy/certificates")
    candidates = sorted(source.glob("**/" + domain + "/" + domain + ".crt"))
    for crt in candidates:
        key = crt.with_suffix(".key")
        if not key.is_file():
            continue
        checked = command("openssl", "x509", "-in", str(crt), "-checkhost", domain, "-noout", timeout=5)
        if checked.returncode:
            continue
        still_valid = command("openssl", "x509", "-in", str(crt), "-checkend", "7200", "-noout", timeout=5)
        if still_valid.returncode:
            continue
        if CERT.is_file() and KEY.is_file() and CERT.read_bytes() == crt.read_bytes() and KEY.read_bytes() == key.read_bytes():
            return True
        CERT.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        for target, original in ((CERT, crt), (KEY, key)):
            fd, tmp = tempfile.mkstemp(dir=str(target.parent))
            with os.fdopen(fd, "wb") as output, open(original, "rb") as source_file:
                shutil.copyfileobj(source_file, output)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(tmp, 0o640)
            os.replace(tmp, target)
        try:
            import grp
            gid = grp.getgrnam("xray").gr_gid
            for target in (CERT, KEY):
                os.chown(target, 0, gid)
        except KeyError:
            pass
        if XRAY.is_file():
            command("systemctl", "try-restart", UNIT, timeout=30)
        return True
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--serve", action="store_true")
    p.add_argument("--sync-tls", action="store_true")
    p.add_argument("--init", action="store_true")
    args = p.parse_args()
    if args.sync_tls:
        if not sync_tls():
            raise SystemExit("No valid Caddy TLS certificate found")
    elif args.init:
        if not sync_tls():
            raise SystemExit("No valid Caddy TLS certificate found")
        if not STATE.is_file():
            atomic_json(STATE, {"profiles": {}})
        apply(read_json(STATE).get("profiles", {}))
    elif args.serve:
        server = ThreadingHTTPServer(("127.0.0.1", 9089), API)
        server.serve_forever()
    else:
        p.error("Choose --serve, --init or --sync-tls")


if __name__ == "__main__":
    main()
