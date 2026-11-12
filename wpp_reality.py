#!/usr/bin/env python3
"""Isolated VLESS TCP REALITY + XTLS Vision runtime for WPO 3.0.

REALITY keys never enter connections.json or the HTML admin payload.
The client receives only the public key (pbk), SNI and Short ID.
"""
import json
import os
import re
import secrets
import subprocess
import tempfile
from urllib.parse import quote, urlencode

XRAY_BIN = "/opt/web-panel-proxy/xray/xray"
STATE = "/etc/web-proxy-panel/reality-profiles.json"
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_CID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


class RealityError(ValueError):
    pass


def _check_id(connection_id):
    if not _CID_RE.fullmatch(str(connection_id)):
        raise RealityError("Некорректный идентификатор REALITY.")
    return str(connection_id)


def _load(path):
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise RealityError("Повреждено хранилище ключей REALITY.")
    return data


def _write(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".wpo-reality-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _validate_profile(value):
    return (isinstance(value, dict)
            and _KEY_RE.fullmatch(str(value.get("private_key", "")))
            and _KEY_RE.fullmatch(str(value.get("public_key", "")))
            and re.fullmatch(r"[0-9a-f]{16}", str(value.get("short_id", ""))))


def read_profile(connection_id, path=STATE):
    profile = _load(path).get(_check_id(connection_id))
    if not _validate_profile(profile):
        raise RealityError("Ключи REALITY ещё не созданы. Сначала создайте клиента.")
    return profile


def ensure_profile(connection_id, xray_bin=XRAY_BIN, path=STATE):
    connection_id = _check_id(connection_id)
    profiles = _load(path)
    existing = profiles.get(connection_id)
    if existing is not None:
        if not _validate_profile(existing):
            raise RealityError("Ключи REALITY повреждены; автоматическая смена запрещена.")
        return existing
    result = subprocess.run([xray_bin, "x25519"], capture_output=True,
                            text=True, timeout=20, check=False)
    if result.returncode:
        raise RealityError("Xray не смог создать ключи REALITY.")
    output = result.stdout + "\n" + result.stderr
    private = re.search(r"(?im)^\s*Private\s*Key\s*:\s*([A-Za-z0-9_-]+)\s*$", output)
    public = re.search(r"(?im)^\s*(?:Password(?:\s*\(\s*Public\s*Key\s*\))?|Public\s*Key)\s*:\s*([A-Za-z0-9_-]+)\s*$", output)
    if not private or not public:
        raise RealityError("Не удалось распознать ключи Xray x25519.")
    profile = {"private_key": private.group(1), "public_key": public.group(1),
               "short_id": secrets.token_hex(8)}
    if not _validate_profile(profile):
        raise RealityError("Xray вернул ключи в неожиданном формате.")
    profiles[connection_id] = profile
    _write(path, profiles)
    return profile


def is_reality(connection):
    return (isinstance(connection, dict)
            and connection.get("protocol") == "vless"
            and isinstance(connection.get("config"), dict)
            and connection["config"].get("route") == "reality")


def server_inbound(connection, clients, profile):
    if not is_reality(connection) or not _validate_profile(profile):
        raise RealityError("Некорректный профиль VLESS REALITY.")
    cfg = connection["config"]
    sni = cfg["sni"]
    return {
        "tag": "vless-reality-" + _check_id(connection["id"]),
        "listen": "0.0.0.0",
        "port": int(cfg["port"]),
        "protocol": "vless",
        "settings": {"clients": clients, "decryption": "none"},
        "streamSettings": {
            "network": "raw", "security": "reality",
            "realitySettings": {
                "show": False, "target": sni + ":443",
                "serverNames": [sni],
                "privateKey": profile["private_key"],
                "shortIds": [profile["short_id"]],
                "xver": 0,
                "limitFallbackUpload": {"afterBytes": 0, "bytesPerSec": 65536, "burstBytesPerSec": 131072},
                "limitFallbackDownload": {"afterBytes": 0, "bytesPerSec": 65536, "burstBytesPerSec": 131072},
            },
        },
        "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"],
                     "routeOnly": True},
    }


def client_link(uuid, server, name, connection, profile):
    if not is_reality(connection) or not _validate_profile(profile):
        raise RealityError("Подключение REALITY не готово.")
    cfg = connection["config"]
    # The address is our actual VPS; SNI is the cover hostname, not the VPS.
    options = {
        "encryption": "none", "security": "reality",
        "type": "tcp", "sni": cfg["sni"],
        "fp": cfg.get("fingerprint", "chrome"),
        "pbk": profile["public_key"],
        "sid": profile["short_id"],
        "flow": "xtls-rprx-vision",
        "spx": "/",
    }
    address = str(cfg.get("address") or server)
    if ":" in address and not address.startswith("["): address = "[" + address + "]"
    return ("vless://" + quote(str(uuid), safe="-") + "@"
            + address + ":" + str(int(cfg["port"])) + "?"
            + urlencode(options) + "#" + quote(str(name or "VLESS REALITY"), safe=""))
