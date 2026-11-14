#!/usr/bin/env python3
"""Eight-protocol headless WPO Node runtime.

Authoritative server-side credentials are generated and retained here. Each
profile is provisioned by its *own actual backend*. A link is returned only
after its backend accepts the profile. Keep site-agent API separately running.

This module intentionally reuses the WPO-tested AmneziaWG and Naive/Mieru
server modules. It does NOT share the main panel's user registry.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import uuid

import wpo_node_vpn as xray
import wpp_awg as awg
import wpp_extra_protocols as extras

ROOT = xray.ROOT
STATE = xray.STATE
SETTINGS = xray.SETTINGS
MT_BIN = "/opt/MTProxy/objs/bin/mtproto-proxy"
MT_AES = "/etc/mtproxy/proxy-secret"
MT_CONF = "/etc/mtproxy/proxy-multi.conf"
MT_UNIT_DIR = Path("/etc/systemd/system")
RELAY_CONFIG = Path("/etc/tproxy-server/profiles.json")
RELAY_SERVICE = "wpo-node-relay.service"
MT_SERVICE_PREFIX = "wpo-node-mtproxy-"
KNOWN = frozenset(("vless", "hysteria", "web", "mtproto", "awg20", "awg31", "naive", "mieru"))
NATIVE = KNOWN - xray.SUPPORTED
PROTOCOLS_ORDER = ("vless", "hysteria", "web", "mtproto", "awg20", "awg31", "naive", "mieru")
GROUPED_CONNECTIONS = {
    "naive": {"id": "naive-primary", "name": "NaiveProxy", "protocol": "naive",
              "enabled": True, "config": {"port": 53000}},
    "mieru": {"id": "mieru-primary", "name": "Mieru", "protocol": "mieru",
              "enabled": True, "config": {"port": 54000, "transport": "TCP"}},
}
USER_ID_RE = re.compile(r"^[a-f0-9]{16}$")
HEX_SECRET_RE = re.compile(r"^[a-f0-9]{32}$")


def _call(*args, timeout=50):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError("Node engine command failed: " + str(args[0]) +
                           " (exit " + str(p.returncode) + ")")
    return p


def _unit_active(unit):
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", unit],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=4).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _binary(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def available():
    """Backends actually installed, not merely present in a UI catalog.

    A newly installed server can be ready to accept profiles before per-user
    units begin running; every provision operation checks the spawned unit.
    """
    if not xray.live():
        return frozenset()
    caps = set(xray.SUPPORTED)
    if (_binary(MT_BIN) and Path(MT_AES).is_file() and Path(MT_CONF).is_file()):
        caps.add("mtproto")
        if (_binary("/usr/local/bin/tproxy-server") and
                _unit_active(RELAY_SERVICE)):
            caps.add("web")
    if (all(_binary(p) for p in
            ("/usr/local/bin/awg", "/usr/local/bin/awg-quick",
             "/usr/local/bin/amneziawg-go")) and
            Path("/etc/systemd/system/web-panel-proxy-awg@.service").is_file()):
        caps.update(("awg20", "awg31"))
    if (_binary(extras.NAIVE_BIN) and
            Path("/etc/systemd/system/web-panel-proxy-naive.service").is_file()):
        caps.add("naive")
    if (_binary(extras.MIERU_BIN) and
            Path("/etc/systemd/system/web-panel-proxy-mieru.service").is_file()):
        caps.add("mieru")
    return frozenset(caps)


def full_ready():
    return available() == KNOWN


def validate(data):
    external_id, name, protocols = xray.valid_params({
        "external_id": data.get("external_id"),
        "name": data.get("name"),
        "protocols": list(xray.SUPPORTED),
    })
    raw = data.get("protocols")
    if (not isinstance(raw, list) or not raw or len(raw) > 8 or
            any(not isinstance(v, str) or v not in KNOWN for v in raw)):
        raise ValueError("Invalid node protocol selection")
    if len(set(raw)) != len(raw):
        raise ValueError("Duplicate protocol selection")
    missing = sorted(set(raw) - available())
    if missing:
        raise RuntimeError("Node protocols not ready: " + ", ".join(missing))
    return external_id, name, sorted(raw, key=PROTOCOLS_ORDER.index)


def profile_id(external_id, protocol):
    """Stable, opaque 16-char local ID (never trusts user-provided file paths)."""
    if not xray.IDENTIFIER.fullmatch(external_id) or protocol not in KNOWN:
        raise ValueError("Invalid node profile identity")
    return hashlib.sha256((external_id + ":" + protocol).encode()).hexdigest()[:16]


def _allocated_port(uid, protocol):
    # Each MTProto backend has its own isolated listener.
    value = int(uid[:8], 16) % 950
    return (24000 if protocol == "web" else 25000) + value


def _stats_port(uid, protocol):
    value = int(uid[8:], 16) % 950
    return (27000 if protocol == "web" else 28000) + value


def build_profile(external_id, protocol, existing):
    """Keep client secrets stable across updates and panel reinstallations."""
    if isinstance(existing, dict):
        return copy.deepcopy(existing)
    uid = profile_id(external_id, protocol)
    base = {"id": uid, "protocol": protocol, "enabled": True}
    if protocol in xray.SUPPORTED:
        base["secret"] = str(uuid.uuid4())
    elif protocol in ("web", "mtproto"):
        base.update({"secret": secrets.token_hex(16),
                     "backend_port": _allocated_port(uid, protocol),
                     "stats_port": _stats_port(uid, protocol)})
    elif protocol in awg.PROTOCOLS:
        # Force no collision with already allocated AWG ports and addresses by
        # passing the prior AWG users to new_user via caller (see assemble).
        raise RuntimeError("AWG allocation requires the complete live registry")
    else:
        base.update(extras.new_user(protocol, uid))
        base["connection_id"] = GROUPED_CONNECTIONS[protocol]["id"]
    return base


def assemble(state):
    """Flatten all committed profiles into the isolated WPO backend records."""
    users = []
    for external_id, entry in state.items():
        if not xray.IDENTIFIER.fullmatch(external_id) or not isinstance(entry, dict):
            raise ValueError("Corrupted node subscriber registry")
        records = entry.get("native", {})
        if not isinstance(records, dict):
            raise ValueError("Corrupted native credentials")
        for protocol, record in records.items():
            if protocol not in KNOWN or not isinstance(record, dict):
                raise ValueError("Invalid native record")
            if record.get("id") != profile_id(external_id, protocol):
                raise ValueError("Wrong native profile ID")
            users.append(copy.deepcopy(record))
    return users


def with_profile(state, external_id, name, protocols):
    updated = copy.deepcopy(state)
    previous = updated.get(external_id, {})
    keys = previous.get("secrets", {}) if isinstance(previous, dict) else {}
    native = previous.get("native", {}) if isinstance(previous, dict) else {}
    existing_users = assemble(updated)
    result_keys = {}
    result_native = {}
    for protocol in protocols:
        if protocol in xray.SUPPORTED:
            value = keys.get(protocol)
            if value is None:
                value = str(uuid.uuid4())
            result_keys[protocol] = value
        else:
            record = native.get(protocol)
            if record is None and protocol in awg.PROTOCOLS:
                uid = profile_id(external_id, protocol)
                record = {"id": uid, "protocol": protocol, "enabled": True}
                record.update(awg.new_user(protocol, existing_users, uid))
            elif record is None:
                record = build_profile(external_id, protocol, None)
            record["name"] = name
            if record.get("id") != profile_id(external_id, protocol):
                raise ValueError("Native profile identity mismatch")
            result_native[protocol] = record
            existing_users.append(record)
    updated[external_id] = {"name": name, "secrets": result_keys,
                            "native": result_native}
    return updated


def _quote_cmd(arg):
    """Never interpolate untrusted credentials into shell units."""
    value = str(arg)
    if any(ch.isspace() for ch in value) or any(ch in "'\"\\$;%\n\r\t" for ch in value):
        raise ValueError("Invalid unit argument")
    return value


def _mt_unit(record):
    uid = record["id"]
    if not USER_ID_RE.fullmatch(uid):
        raise ValueError("Invalid MTProto service user ID")
    proto = record["protocol"]
    if proto not in ("web", "mtproto"):
        raise ValueError("Invalid MTProto service protocol")
    if not HEX_SECRET_RE.fullmatch(record["secret"]):
        raise ValueError("Invalid Telegram proxy secret")
    port, stats = int(record["backend_port"]), int(record["stats_port"])
    allowed = 24000 <= port < 26000 and 27000 <= stats < 29000
    if not allowed:
        raise ValueError("Invalid allocated MTProto port")
    return (
        "[Unit]\nDescription=WPO Node Telegram %s profile %s\n"
        "After=network-online.target wpo-node-mt-firewall.service\n"
        "Wants=network-online.target\nRequires=wpo-node-mt-firewall.service\n"
        "[Service]\nType=simple\nUser=mtproxy\nGroup=mtproxy\n"
        "ExecStart=%s -u mtproxy -p %d -H %d -S %s --aes-pwd %s %s -M 1\n"
        "Restart=always\nRestartSec=3\nNoNewPrivileges=true\nPrivateTmp=true\n"
        "[Install]\nWantedBy=multi-user.target\n"
    ) % (proto, uid, MT_BIN, stats, port, record["secret"], MT_AES, MT_CONF)


def _native_connections():
    return {"connections": list(GROUPED_CONNECTIONS.values())}


def _update_mtproxy(users, domain):
    current = {u["id"]: u for u in users if
               u.get("protocol") in ("web", "mtproto") and u.get("enabled", True)}
    all_ports = [u["backend_port"] for u in current.values()]
    all_stats = [u["stats_port"] for u in current.values()]
    if len(set(all_ports)) != len(all_ports) or len(set(all_stats)) != len(all_stats):
        raise RuntimeError("Telegram proxy port collision; registration rolled back")
    MT_UNIT_DIR.mkdir(parents=True, exist_ok=True)
    for name in MT_UNIT_DIR.glob(MT_SERVICE_PREFIX + "*.service"):
        uid = name.stem[len(MT_SERVICE_PREFIX):]
        if uid not in current:
            _call("systemctl", "disable", "--now", name.name)
            name.unlink(missing_ok=True)
    for uid, record in current.items():
        unit = MT_SERVICE_PREFIX + uid + ".service"
        path = MT_UNIT_DIR / unit
        desired = _mt_unit(record)
        if not path.is_file() or path.read_text() != desired:
            fd, tmp = __import__("tempfile").mkstemp(dir=str(MT_UNIT_DIR))
            with os.fdopen(fd, "w") as f:
                f.write(desired)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        _call("systemctl", "daemon-reload")
        _call("systemctl", "enable", unit)
        _call("systemctl", "restart", unit)
        if not _unit_active(unit):
            raise RuntimeError("MTProxy backend failed to start")
        # An active unit without a live listener must not produce a Telegram
        # connection URI. The same IPv4 listener works for MTProto and WEB.
        import time
        for _ in range(30):
            sockets = _call("ss", "-lntH", timeout=6).stdout
            if re.search(r":%d(?:\\s|$)" % int(record["backend_port"]), sockets):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("MTProxy backend did not open its listener")
    relay_profiles = [
        {"name": record["id"], "secret": record["secret"],
         "backend": "127.0.0.1:" + str(record["backend_port"]),
         "carrier_mode": "https"}
        for record in current.values() if record["protocol"] == "web"
    ]
    if not relay_profiles:
        # The upstream Go relay requires a nonempty registry even when no
        # WEB subscribers exist. Keep a private, random bootstrap capability
        # that routes to an unused local port, never disclose it to clients.
        bootstrap = Path("/etc/wpp-node-vpn/relay-bootstrap-secret")
        if not bootstrap.is_file():
            raise RuntimeError("WEB relay bootstrap credential is missing")
        secret = bootstrap.read_text(encoding="ascii").strip()
        if not HEX_SECRET_RE.fullmatch(secret):
            raise RuntimeError("WEB relay bootstrap credential is invalid")
        relay_profiles = [{
            "name": "node-bootstrap", "secret": secret,
            "backend": "127.0.0.1:2398", "carrier_mode": "https"
        }]
    xray.atomic_json(RELAY_CONFIG, {"profiles": relay_profiles})
    import grp
    os.chown(RELAY_CONFIG, 0, grp.getgrnam("tproxy").gr_gid)
    os.chmod(RELAY_CONFIG, 0o400)
    _call("systemctl", "restart", RELAY_SERVICE)
    if not _unit_active(RELAY_SERVICE):
        raise RuntimeError("WEB Proxy relay failed to restart")


def native_apply(state, settings):
    """Apply actual native units, no fake URL generation.

    Called only while the authenticated federation update lock is held.
    Failure triggers caller rollback of both Xray and native services.
    """
    users = assemble(state)
    _update_mtproxy(users, settings["domain"])
    awg.sync(users)
    extras.sync(users, _native_connections(), settings["domain"],
                str(xray.CERT), str(xray.KEY))


def _mtproto_link(record, domain):
    secret = record["secret"]
    if record["protocol"] == "web":
        return "https://t.me/webproxy?server=" + domain + "&secret=" + secret
    return ("https://t.me/proxy?server=" + domain + "&port=" +
            str(record["backend_port"]) + "&secret=dd" + secret)


def links(entry, settings):
    name = entry["name"]
    domain = settings["domain"]
    native = entry.get("native", {})
    result = [
        {"protocol": p, "link": xray.link(p, entry["secrets"][p], name, settings)}
        for p in PROTOCOLS_ORDER if p in entry.get("secrets", {})
    ]
    for protocol in PROTOCOLS_ORDER:
        if protocol not in native: continue
        record = native[protocol]
        if protocol in ("web", "mtproto"):
            link = _mtproto_link(record, domain)
            result.append({"protocol": protocol, "link": link})
        elif protocol in awg.PROTOCOLS:
            config = awg.client_config(record, domain, name)
            result.append({"protocol": protocol, "config": config,
                           "filename": "WPO-" + protocol + "-" + record["id"] + ".conf"})
        elif protocol in ("naive", "mieru"):
            connection = GROUPED_CONNECTIONS[protocol]
            link = extras.client_link(record, connection, domain, name)
            result.append({"protocol": protocol, "link": link})
    return result


def sync(data):
    external_id, name, protocols = validate(data)
    xray.LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    import fcntl
    with xray.LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        old = xray.read_json(STATE, {"profiles": {}}).get("profiles", {})
        new = with_profile(old, external_id, name, protocols)
        if new != old:
            try:
                xray.apply(new)
                native_apply(new, xray.read_json(SETTINGS))
            except Exception:
                # A failed sync is not recorded as a successful profile.
                try:
                    xray.apply(old)
                    native_apply(old, xray.read_json(SETTINGS))
                except Exception:
                    pass
                raise
            xray.atomic_json(STATE, {"profiles": new})
        return {"ok": True, "profiles": links(new[external_id], xray.read_json(SETTINGS))}


def remove(data):
    external_id = str(data.get("external_id", ""))
    if not xray.IDENTIFIER.fullmatch(external_id):
        raise ValueError("Invalid federation identity")
    xray.LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    import fcntl
    with xray.LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        old = xray.read_json(STATE, {"profiles": {}}).get("profiles", {})
        new = copy.deepcopy(old)
        new.pop(external_id, None)
        if new != old:
            try:
                xray.apply(new)
                native_apply(new, xray.read_json(SETTINGS))
            except Exception:
                try:
                    xray.apply(old)
                    native_apply(old, xray.read_json(SETTINGS))
                except Exception:
                    pass
                raise
            xray.atomic_json(STATE, {"profiles": new})
        return {"ok": True, "deleted": external_id in old}


def purge():
    xray.LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    import fcntl
    with xray.LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        old = xray.read_json(STATE, {"profiles": {}}).get("profiles", {})
        if old:
            xray.apply({})
            native_apply({}, xray.read_json(SETTINGS))
            xray.atomic_json(STATE, {"profiles": {}})
        return {"ok": True, "deleted": len(old)}
