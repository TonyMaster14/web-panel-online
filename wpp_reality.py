"""VLESS TCP REALITY / XTLS Vision support for WEB PANEL ONLINE.

Keys are generated only on the controller, never included in the panel's HTTP
responses or in share links. One stable server keypair and short ID are
persisted independently of the client records and reused on every update.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from pathlib import Path
from urllib.parse import quote, urlencode

PORT = 8444
TARGET = "www.microsoft.com:443"
SERVER_NAME = "www.microsoft.com"
KEY_FILE = "/etc/web-proxy-panel/reality.json"
_KEY = re.compile(r"^[a-zA-Z0-9_-]{43}$")
_HEX = re.compile(r"^[0-9a-f]{2,16}$")


def _parse_keys(output):
    """Support legacy and Xray 26.x x25519 CLI output formats."""
    fields = {}
    for line in str(output).splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        normalized = re.sub(r"[^a-z]", "", label.casefold())
        candidate = value.strip()
        if normalized in ("privatekey", "private"):
            fields["private"] = candidate
        elif normalized.startswith("password") or normalized == "publickey":
            fields["public"] = candidate
    if not _KEY.fullmatch(fields.get("private", "")) or not _KEY.fullmatch(fields.get("public", "")):
        raise RuntimeError("Xray x25519 returned invalid Reality keys")
    return fields["private"], fields["public"]


def _validate(data):
    if not isinstance(data, dict):
        raise RuntimeError("Invalid persisted Reality settings")
    for key in ("private_key", "public_key"):
        if not _KEY.fullmatch(str(data.get(key, ""))):
            raise RuntimeError("Invalid Reality key stored in "+KEY_FILE)
    if not _HEX.fullmatch(str(data.get("short_id", ""))):
        raise RuntimeError("Invalid Reality short ID")
    return data


def load_or_create(xray_bin, key_file=KEY_FILE):
    """Atomically provision credentials with strict permissions.

    The panel serializes all state mutations; O_EXCL guards unexpected
    simultaneous provisioning by another process and avoids overwriting keys.
    """
    path = Path(key_file)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Reality credentials path is not a regular file")
        return _validate(json.loads(path.read_text(encoding="utf-8")))
    response = subprocess.run([str(xray_bin), "x25519"], capture_output=True,
                              text=True, timeout=15, check=True)
    private_key, public_key = _parse_keys(response.stdout)
    data = {
        "private_key": private_key,
        "public_key": public_key,
        "short_id": secrets.token_hex(8),
        "target": TARGET,
        "server_name": SERVER_NAME,
        "port": PORT,
    }
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=True, separators=(",", ":"))
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        if path.exists():
            return _validate(json.loads(path.read_text(encoding="utf-8")))
        os.replace(temp, path)
        path.chmod(0o600)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    return _validate(data)


def inbound(clients, credentials):
    credentials = _validate(credentials)
    return {
        "tag": "vless-reality",
        "listen": "0.0.0.0",
        "port": int(credentials.get("port", PORT)),
        "protocol": "vless",
        "settings": {"clients": [
            {**item, "flow": "xtls-rprx-vision"} for item in clients
        ], "decryption": "none"},
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "target": credentials.get("target", TARGET),
                "serverNames": [credentials.get("server_name", SERVER_NAME)],
                "privateKey": credentials["private_key"],
                "shortIds": [credentials["short_id"]],
            },
        },
        "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"],
                     "routeOnly": True},
    }


def client_link(secret, domain, name, credentials):
    credentials = _validate(credentials)
    params = {
        "encryption": "none",
        "security": "reality",
        "type": "tcp",
        "sni": credentials.get("server_name", SERVER_NAME),
        "fp": "chrome",
        "pbk": credentials["public_key"],
        "sid": credentials["short_id"],
        "spx": "/",
        "flow": "xtls-rprx-vision",
    }
    return ("vless://" + quote(secret, safe="-") + "@" + domain + ":" +
            str(int(credentials.get("port", PORT))) + "?" + urlencode(params) +
            "#" + quote(name, safe=""))
