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


# Internal-only TCP backends. Public 443 is reserved for the TLS SNI mux.
CADDY_BACKEND_PORT = 18443
REALITY_BACKEND_PORT = 24443
ROUTER_CONFIG = "/etc/web-proxy-panel/tls-mux.cfg"
ROUTER_SERVICE = "web-panel-proxy-tls-mux.service"
# Shared candidates for connection and node editors.
SNI_CANDIDATES = (
    ("www.microsoft.com", "Microsoft"),
    ("www.apple.com", "Apple"),
    ("www.google.com", "Google"),
    ("www.amazon.com", "Amazon"),
    ("www.wikipedia.org", "Wikipedia"),
)
DEFAULT_SNI = SNI_CANDIDATES[0][0]

MUX_BEGIN = "# WPP REALITY TLS MUX BEGIN"
MUX_END = "# WPP REALITY TLS MUX END"


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
        # TCP/443 is owned by the SNI pass-through router, never Xray.
        "listen": "127.0.0.1" if int(cfg["port"]) == 443 else "0.0.0.0",
        "port": REALITY_BACKEND_PORT if int(cfg["port"]) == 443 else int(cfg["port"]),
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


def shared_443_sni(connections, active_connection_ids, panel_domain=""):
    """Return the sole active REALITY SNI sharing TCP/443, or empty string.

    Many clients can share one connection/inbound. Two different REALITY
    inbounds cannot share 443 without an explicit additional SNI mapping.
    """
    matched = []
    for item in connections:
        if (is_reality(item) and item.get("enabled", True)
                and item.get("id") in active_connection_ids
                and int(item.get("config", {}).get("port", 0) or 0) == 443):
            matched.append(item)
    if len(matched) > 1:
        raise RealityError("TCP/443 поддерживает только одно активное подключение REALITY. Другим укажите отдельный порт.")
    if not matched:
        return ""
    sni = str(matched[0]["config"]["sni"]).strip().lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9.-]{4,253}", sni) or "." not in sni:
        raise RealityError("Некорректный SNI для общего TCP/443.")
    if not str(panel_domain).strip():
        raise RealityError("Не удалось определить домен панели для безопасного разделения TCP/443.")
    if sni == str(panel_domain).strip().lower().rstrip("."):
        raise RealityError("SNI REALITY на 443 не может совпадать с доменом панели: Caddy должен получать HTTPS и ACME.")
    return sni


def caddy_mux_enabled(source):
    return MUX_BEGIN in source


def configure_caddy_mux(source, enabled):
    """Toggle managed internal Caddy listener, keeping all site routes intact.

    https_port is explicitly *internal* according to Caddy's documentation;
    443 remains the public URL and TLS-ALPN-01 challenge port. default_bind
    prevents accidentally exposing the internal 18443 backend externally.
    """
    if not isinstance(source, str):
        raise RealityError("Caddyfile должен быть текстом.")
    if source.count(MUX_BEGIN) != source.count(MUX_END) or source.count(MUX_BEGIN) > 1:
        raise RealityError("Повреждены маркеры маршрутизатора в Caddyfile.")
    managed = re.compile(
        r"(?m)^[ \t]*" + re.escape(MUX_BEGIN)
        + r"\n(?:.*\n)*?^[ \t]*" + re.escape(MUX_END) + r"\n?"
    )
    clean = managed.sub("", source)
    if not enabled:
        return clean
    if re.search(r"(?m)^\s*(?:https_port|default_bind)\s+", clean):
        raise RealityError("В Caddy уже настроены https_port/default_bind. Автоматический TLS-маршрутизатор не будет менять чужую конфигурацию.")
    if re.search(r"(?m)^\s*bind\s+", clean):
        raise RealityError("В Caddy есть пользовательские bind: безопасный перенос на внутренний HTTPS-порт требует отдельной проверки.")
    if re.search(r"(?m)^\s*servers\s+127\.0\.0\.1:18443\s*\{", clean):
        raise RealityError("Сервер Caddy на 127.0.0.1:18443 уже настроен вручную.")
    directive = ("    " + MUX_BEGIN + "\n"
                 "    https_port " + str(CADDY_BACKEND_PORT) + "\n"
                 "    default_bind 127.0.0.1\n"
                 # Preserve the source IP of HTTPS/panel visitors. HAProxy
                 # sends PROXY v2 only to Caddy, not to the REALITY inbound.
                 "    servers 127.0.0.1:" + str(CADDY_BACKEND_PORT) + " {\n"
                 "        protocols h1 h2\n"
                 "        listener_wrappers {\n"
                 "            proxy_protocol {\n"
                 "                timeout 2s\n"
                 "                allow 127.0.0.1/32\n"
                 "                fallback_policy require\n"
                 "            }\n"
                 "            tls\n"
                 "        }\n"
                 "    }\n"
                 "    " + MUX_END + "\n")
    # A global options block in Caddy is denoted by a bare opening brace.
    global_block = re.search(r"(?m)^\{[ \t]*\r?\n", clean)
    if global_block:
        position = global_block.end()
        return clean[:position] + directive + clean[position:]
    return "{\n" + directive + "}\n\n" + clean


def haproxy_config(sni, ipv6=True):
    """Generate a strict, transparent TCP router; no TLS termination."""
    if not isinstance(sni, str) or not re.fullmatch(r"[a-z0-9.-]{4,253}", sni) or "." not in sni:
        raise RealityError("Недопустимый SNI для HAProxy.")
    listeners = "    bind 0.0.0.0:443\n"
    if ipv6:
        listeners += "    bind :::443 v6only\n"
    return (
        "# Managed by WEB PANEL ONLINE. Do not edit by hand.\n"
        "global\n"
        "    maxconn 10000\n"
        "    user haproxy\n"
        "    group haproxy\n\n"
        "defaults\n"
        "    mode tcp\n"
        "    timeout connect 5s\n"
        "    timeout client 1h\n"
        "    timeout server 1h\n"
        "    timeout tunnel 24h\n\n"
        "frontend wpo_tls_443\n"
        + listeners
        + "    mode tcp\n"
        "    tcp-request inspect-delay 5s\n"
        "    tcp-request content accept if { req.ssl_hello_type 1 }\n"
        + "    use_backend wpo_reality if { req.ssl_sni -i " + sni + " }\n"
        "    default_backend wpo_caddy\n\n"
        "backend wpo_reality\n"
        "    server xray 127.0.0.1:" + str(REALITY_BACKEND_PORT) + " check\n\n"
        "backend wpo_caddy\n"
        "    server caddy 127.0.0.1:" + str(CADDY_BACKEND_PORT) + " check send-proxy-v2\n"
    )
