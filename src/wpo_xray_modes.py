"""WPO per-node Xray configuration choice for test deployment (V27).

Modes select which REALITY/Hysteria2 inbound is active. Existing XHTTP,
management API, other protocols and user credentials remain untouched.
Changes are transactional: never persist a new choice if Xray rejects it.

RemnaWave transport deltas supported without changing WPO's HAProxy/Caddy
architecture: REALITY minClientVer 1.0.0 and Hysteria2 BBR congestion.
The Unix-socket/xver=1 fallback from RemnaWave is NOT enabled here: WPO
does not yet provide a PROXY-v1-compatible socket receiver.
"""
import copy
import json
import os
from pathlib import Path
import tempfile

MODES = {
    "both": "REALITY + Hysteria2",
    "reality": "REALITY",
    "hysteria": "Hysteria2",
}
PANEL_STATE = Path("/etc/web-proxy-panel/xray-mode.json")
NODE_STATE = Path("/etc/wpp-node-vpn/xray-mode.json")


def normalize(mode):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Выберите REALITY + Hysteria2, REALITY или Hysteria2.")
    return mode


def get(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return normalize(value["mode"])
    except FileNotFoundError:
        return "both"


def save(path, mode):
    mode = normalize(mode)
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".wpo-xray-mode-", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"mode": mode}, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def allowed(mode):
    mode = normalize(mode)
    return frozenset(("reality", "hysteria") if mode == "both" else (mode,))


def is_enabled(mode, proto):
    return proto in allowed(mode)


def tune_config(value, mode):
    """Return a copy; skip ONLY the deselected REALITY/Hysteria inbound tags."""
    allow = allowed(mode)
    config = copy.deepcopy(value)
    inbounds = config.get("inbounds", [])
    if not isinstance(inbounds, list):
        raise ValueError("Xray inbounds must be a list")
    filtered = []
    for row in inbounds:
        if not isinstance(row, dict):
            raise ValueError("Invalid Xray inbound")
        protocol = row.get("protocol")
        stream = row.get("streamSettings", {})
        if not isinstance(stream, dict):
            raise ValueError("Invalid stream settings")
        security = stream.get("security")
        if protocol == "vless" and security == "reality":
            if "reality" not in allow:
                continue
            settings = stream.setdefault("realitySettings", {})
            settings["minClientVer"] = "1.0.0"
            # No xver=1 or Unix socket without a PROXY-v1 capable receiver.
        if protocol == "hysteria":
            if "hysteria" not in allow:
                continue
            stream["finalmask"] = {"quicParams": {"debug": False, "congestion": "bbr"}}
        filtered.append(row)
    config["inbounds"] = filtered
    return config


def _current_clients(config, protocol):
    result = []
    for inbound in config.get("inbounds", []):
        stream = inbound.get("streamSettings", {})
        if protocol == "hysteria" and inbound.get("protocol") == "hysteria":
            result += inbound.get("settings", {}).get("clients", [])
        elif protocol == "reality" and stream.get("security") == "reality":
            result += inbound.get("settings", {}).get("clients", [])
    return result


def refuse_live_drop(mode, config):
    """Refuse deactivating an inbound with provisioned live credentials."""
    allow = allowed(mode)
    for proto in ("reality", "hysteria"):
        if proto not in allow and _current_clients(config, proto):
            raise ValueError(
                "На ноде уже есть пользователи " +
                ("REALITY" if proto == "reality" else "Hysteria2") +
                ". Сначала перенесите их подключения; отключение не применено."
            )


def switch(path, mode, current_config, sync):
    """Atomic mode switch with live Xray apply and rollback on error."""
    mode = normalize(mode)
    old_mode = get(path)
    if mode == old_mode:
        return {"ok": True, "mode": mode, "unchanged": True}
    refuse_live_drop(mode, current_config)
    save(path, mode)
    try:
        sync()
    except Exception:
        save(path, old_mode)
        try:
            sync()
        except Exception as rollback_error:
            raise RuntimeError("Не удалось восстановить Xray. Проверьте службы на VPS.") from rollback_error
        raise
    return {"ok": True, "mode": mode}


def select_for_node(node, protocols):
    """Filter ONLY REALITY/Hysteria2 when building per-node Happ links."""
    mode = normalize(node.get("xray_mode", "both"))
    return tuple(p for p in protocols
                 if p not in ("reality", "hysteria") or p in allowed(mode))
