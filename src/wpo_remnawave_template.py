"""RemnaWave REALITY + Hysteria2 transport template for WEB PANEL ONLINE.

Pure builders: no filesystem writes, no service changes, no passwords committed.

This describes only the two inbounds from the user's working RemnaWave profile.
The caller provides each node's own domain, port, X25519 secret/short ID,
certificates, UUID/auth clients and a working PROXY-v1 fallback socket.

IMPORTANT:
- REALITY xver=1 requires the fallback receiver to understand PROXY v1.
- Existing WPO installations use HAProxy and Caddy instead of the original
  /dev/shm/nginx.sock; a compatible socket relay must exist before activation.
- TCP 443 and UDP 443 can coexist, but public firewall rules are separate.
- WPO's other inbounds, API, user stats, credentials, routing and old listeners
  must be preserved by the deployment integration (not by copying this template).
"""
from __future__ import annotations

import copy
import re

DOMAIN = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")
SHORT_ID = re.compile(r"(?:[0-9a-f]{2}){1,8}\Z")
KEY = re.compile(r"[A-Za-z0-9_-]{43}\Z")
CONGESTION = {"debug": False, "congestion": "bbr"}
DNS = {"servers": [{"address": "https://dns.google/dns-query", "skipFallback": False}],
       "queryStrategy": "UseIPv4"}
OUTBOUNDS = [{"tag": "DIRECT", "protocol": "freedom"}, {"tag": "BLOCK", "protocol": "blackhole"}]
ROUTING = {"rules": [
    {"ip": ["geoip:private"], "outboundTag": "BLOCK"},
    {"protocol": ["bittorrent"], "outboundTag": "BLOCK"}
]}


def _port(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError("Port must be an integer from 1 to 65535")
    return value


def _hostname(value: str) -> str:
    if not isinstance(value, str) or not DOMAIN.fullmatch(value.lower()):
        raise ValueError("The node needs its own valid DNS hostname")
    return value.lower()


def reality_inbound(*, node_domain: str, private_key: str, short_id: str,
                    fallback_socket: str, clients: list, port: int = 19444,
                    listen: str = "127.0.0.1", tag: str = "vless-reality") -> dict:
    """REALITY TCP inbound behind WPO HAProxy; public TCP port is a separate bind.

    RemnaWave's same settings are retained, including minClientVer 1.0.0,
    xver=1, and fallback to a PROXY-v1 Unix socket. WPO must provision
    fallback_socket before activating this inbound.
    """
    domain = _hostname(node_domain)
    _port(port)
    if not isinstance(private_key, str) or not KEY.fullmatch(private_key):
        raise ValueError("Missing or invalid node-local X25519 private key")
    if not isinstance(short_id, str) or not SHORT_ID.fullmatch(short_id):
        raise ValueError("Invalid node-local REALITY short ID")
    if not isinstance(fallback_socket, str) or not fallback_socket.startswith("/"):
        raise ValueError("A provisioned absolute Unix socket path is required")
    if not isinstance(clients, list):
        raise ValueError("The panel must supply its current REALITY clients")
    if not isinstance(tag, str) or not tag:
        raise ValueError("REALITY tag is required")
    return {
        "tag": tag, "port": port, "listen": listen, "protocol": "vless",
        "settings": {"clients": copy.deepcopy(clients), "decryption": "none"},
        "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
        "streamSettings": {
            "network": "tcp", "security": "reality",
            "realitySettings": {
                "dest": fallback_socket, "show": False, "xver": 1,
                "spiderX": "", "shortIds": [short_id],
                "privateKey": private_key, "serverNames": [domain],
                "minClientVer": "1.0.0",
            },
        },
    }


def hysteria_inbound(*, cert_path: str, key_path: str, clients: list,
                    port: int = 443, listen: str = "0.0.0.0",
                    tag: str = "hysteria2") -> dict:
    """Hysteria2 UDP from RemnaWave with BBR; certificates are WPO node-local."""
    _port(port)
    for path in (cert_path, key_path):
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("Certificate/key path must be absolute")
    if not isinstance(clients, list):
        raise ValueError("The panel must supply its current Hysteria2 clients")
    if not isinstance(tag, str) or not tag:
        raise ValueError("Hysteria2 tag is required")
    return {
        "tag": tag, "port": port, "listen": listen, "protocol": "hysteria",
        "settings": {"clients": copy.deepcopy(clients), "version": 2},
        "streamSettings": {
            "network": "hysteria", "security": "tls",
            "finalmask": {"quicParams": copy.deepcopy(CONGESTION)},
            "tlsSettings": {
                "alpn": ["h3"],
                "certificates": [{
                    "keyFile": key_path, "certificateFile": cert_path
                }],
            },
            "hysteriaSettings": {"version": 2},
        },
    }


def remnawave_server_reference(reality: dict, hysteria: dict) -> dict:
    """Reference structure for review; NEVER directly replace a WPO Xray config.

    This omits WPO's API, accounting, user management and other inbound routes.
    Deployment should merge approved inbounds into the existing WPO config,
    then test Xray and rollback on failure.
    """
    if reality.get("protocol") != "vless" or hysteria.get("protocol") != "hysteria":
        raise ValueError("Expected one REALITY and one Hysteria2 inbound")
    return {
        "log": {"loglevel": "warning"},
        "dns": copy.deepcopy(DNS),
        "inbounds": [copy.deepcopy(reality), copy.deepcopy(hysteria)],
        "outbounds": copy.deepcopy(OUTBOUNDS),
        "routing": copy.deepcopy(ROUTING),
    }
