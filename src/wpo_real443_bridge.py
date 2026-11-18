"""WPO Sweden direct-443 REALITY bridge (opt-in; test branch only).

The working Swedish canary is a *separate* Xray on TCP443. This module
mirrors WPO's canonical REALITY client set into that server, so Node Agent
sync, delete and purge do not leave unauthorized/stale users at 443.

No behavior changes unless MODE is explicitly enabled by a separate
installer. This is a compatibility bridge, not the final one-process layout.
"""
from __future__ import annotations

import copy
import grp
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

MODE = Path("/etc/wpo-reality-remna-test/managed.json")
CANARY = Path("/etc/wpo-reality-remna-test/xray.json")
SERVICE = "wpo-reality-remna-xray-test.service"
BINARY = Path("/opt/web-panel-proxy/xray/xray")
SOCKET = "/run/wpo-reality-remna-test/decoy.sock"
EXPECTED_DOMAIN = "swejeep.goodarielservice.xyz"


def enabled_for(domain):
    """Refuse bad opt-in configuration rather than silently skipping updates."""
    if not MODE.exists():
        return False
    if MODE.is_symlink() or not MODE.is_file():
        raise RuntimeError("Invalid REALITY managed-mode marker")
    data = json.loads(MODE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("mode") != "remna-443-mirror-v1":
        raise RuntimeError("Unsupported REALITY managed-mode marker")
    if data.get("domain") != EXPECTED_DOMAIN or domain != EXPECTED_DOMAIN:
        raise RuntimeError("Managed REALITY is only allowed on the Swedish test node")
    return True


def mirror_config(canonical, running):
    """Pure, side-effect-free strict diff of REALITY identities only."""
    if not isinstance(canonical, dict) or not isinstance(running, dict):
        raise ValueError("Invalid Xray JSON")
    sources = [x for x in canonical.get("inbounds", []) if
               x.get("protocol") == "vless" and
               x.get("streamSettings", {}).get("security") == "reality"]
    if len(sources) != 1 or len(running.get("inbounds", [])) != 1:
        raise RuntimeError("Expected exactly one source and one managed REALITY inbound")
    src, dst = sources[0], running["inbounds"][0]
    rs1 = src.get("streamSettings", {}).get("realitySettings", {})
    rs2 = dst.get("streamSettings", {}).get("realitySettings", {})
    if (dst.get("tag") != "wpo-remna-canary-reality"
        or dst.get("protocol") != "vless"
        or dst.get("listen") != "0.0.0.0" or dst.get("port") != 443
        or dst.get("streamSettings", {}).get("network") != "tcp"
        or dst.get("streamSettings", {}).get("security") != "reality"
        or rs2.get("serverNames") != [EXPECTED_DOMAIN]
        or rs2.get("dest") != SOCKET or rs2.get("xver") != 1
        or rs2.get("minClientVer") != "1.0.0"):
        raise RuntimeError("The live canary is no longer the tested Sweden 443 configuration")
    if (rs1.get("privateKey") != rs2.get("privateKey")
        or rs1.get("shortIds") != rs2.get("shortIds")
        or rs1.get("minClientVer") != "1.0.0"):
        raise RuntimeError("REALITY key/Short ID mismatch; refusing to change clients")
    # A single source of truth: the existing WPO canonical generator.
    clients = src.get("settings", {}).get("clients")
    if not isinstance(clients, list):
        raise RuntimeError("Canonical WPO REALITY client list missing")
    ids = [c.get("id") for c in clients]
    if (len(ids) != len(set(ids)) or
        any(not isinstance(c, dict) or not isinstance(c.get("id"), str)
            or c.get("flow") != "xtls-rprx-vision" for c in clients)):
        raise RuntimeError("Invalid or duplicate WPO REALITY clients")
    if (src.get("settings", {}).get("decryption") != "none"
        or dst.get("settings", {}).get("decryption") != "none"):
        raise RuntimeError("Unexpected REALITY VLESS decryption mode")
    updated = copy.deepcopy(running)
    updated["inbounds"][0]["settings"]["clients"] = copy.deepcopy(clients)
    return updated


def _run(*args, timeout=20):
    return subprocess.run([str(x) for x in args], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def _file_replace(path, payload, stat):
    fd, tmp = tempfile.mkstemp(prefix=".real443-sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, stat.st_mode & 0o777)
        os.chown(tmp, stat.st_uid, stat.st_gid)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def reconcile(canonical):
    """Sync and verify, with rollback if the isolated Xray fails to restart."""
    domain = EXPECTED_DOMAIN
    if not enabled_for(domain):
        return False
    if CANARY.is_symlink() or not CANARY.is_file():
        raise RuntimeError("Isolated Sweden 443 Xray config missing")
    current_bytes = CANARY.read_bytes()
    current = json.loads(current_bytes)
    candidate = mirror_config(canonical, current)
    if current == candidate:
        return False

    if _run("systemctl", "is-active", "--quiet", SERVICE, timeout=5).returncode:
        raise RuntimeError("Working Sweden 443 Xray is not active")
    if not BINARY.is_file():
        raise RuntimeError("Xray binary missing")
    with tempfile.TemporaryDirectory(prefix=".real443-candidate-") as td:
        preview = Path(td) / "xray.json"
        preview.write_text(json.dumps(candidate, separators=(",", ":")), encoding="utf-8")
        validation = _run(BINARY, "run", "-test", "-config", preview, timeout=25)
        if validation.returncode:
            raise RuntimeError("Managed REALITY candidate rejected: " + validation.stderr[-300:])

    original_stat = CANARY.stat()
    payload = (json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    try:
        _file_replace(CANARY, payload, original_stat)
        restarted = _run("systemctl", "restart", SERVICE, timeout=25)
        if restarted.returncode or _run("systemctl", "is-active", "--quiet", SERVICE, timeout=5).returncode:
            raise RuntimeError("Managed REALITY Xray failed to restart")
        with socket.create_connection(("127.0.0.1", 443), timeout=3):
            pass
    except Exception:
        _file_replace(CANARY, current_bytes, original_stat)
        _run("systemctl", "restart", SERVICE, timeout=25)
        raise
    return True


def reality_link(secret, name, domain, profile, link_fn):
    """Generate WPO subscription URI using the known-working 443 domain SNI."""
    if not enabled_for(domain):
        return link_fn(secret, name, profile)
    if not isinstance(profile, dict) or not profile.get("public_key"):
        raise RuntimeError("Missing WPO REALITY public key")
    selected = dict(profile, sni=domain, address=domain, port=443)
    return link_fn(secret, name, selected)
