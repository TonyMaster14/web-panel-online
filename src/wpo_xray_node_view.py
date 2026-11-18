"""WPO V28: authenticated, read-only Xray config inspector for a node.

The caller must authorize the admin request or federation request first.
No panel password/token is sent to the browser by default. The full JSON
is available only after a deliberate authenticated "reveal" request.
"""
import copy
import json
from pathlib import Path

MAX_BYTES = 820000
HIDDEN = "•••••••• (скрыто)"


def mask(value, *, in_credentials=False):
    if isinstance(value, list):
        return [mask(part, in_credentials=in_credentials) for part in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    result = {}
    for key, item in value.items():
        lower = str(key).lower()
        protected = (
            lower in ("privatekey", "password", "passwd", "passphrase",
                      "token", "secret", "psk", "auth")
            or (in_credentials and lower in ("id", "uuid", "password", "auth"))
        )
        if protected:
            result[key] = HIDDEN if item not in (None, "", [], {}) else item
        else:
            result[key] = mask(item, in_credentials=(in_credentials or
                lower in ("clients", "users", "accounts", "device_secrets")))
    return result


def view(path, *, reveal=False, reality_profile=None):
    if not isinstance(reveal, bool):
        raise ValueError("Некорректный режим просмотра")
    file = Path(path)
    if file.is_symlink() or not file.is_file():
        raise ValueError("Рабочий Xray JSON недоступен")
    size = file.stat().st_size
    if size < 2 or size > MAX_BYTES:
        raise ValueError("Рабочий Xray JSON слишком большой или пуст")
    config = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("inbounds"), list):
        raise ValueError("Рабочая конфигурация Xray повреждена")
    metadata = {"reality_internal": [], "hysteria_udp": []}
    for entry in config["inbounds"]:
        if not isinstance(entry, dict):
            continue
        stream = entry.get("streamSettings", {})
        if not isinstance(stream, dict):
            continue
        port = entry.get("port")
        if not isinstance(port, int):
            continue
        if entry.get("protocol") == "vless" and stream.get("security") == "reality":
            metadata["reality_internal"].append(port)
            if "sni" not in metadata:
                names = stream.get("realitySettings", {}).get("serverNames", [])
                if isinstance(names, list) and names and isinstance(names[0], str):
                    metadata["sni"] = names[0]
        elif entry.get("protocol") == "hysteria":
            metadata["hysteria_udp"].append(port)
    if isinstance(reality_profile, dict):
        metadata["reality_tcp"] = int(reality_profile.get("port", 443))
        metadata["address"] = str(reality_profile.get("address", ""))[:253]
        metadata["sni"] = str(reality_profile.get("sni", metadata.get("sni", "")))[:253]
    return {"ok": True, "config": config if reveal else mask(config),
            "secrets_visible": bool(reveal), "meta": metadata}


def protocol_status(config):
    result = {"reality": False, "hysteria": False}
    for entry in config.get("inbounds", []):
        if not isinstance(entry, dict):
            continue
        stream = entry.get("streamSettings", {})
        if not isinstance(stream, dict):
            continue
        if entry.get("protocol") == "vless" and stream.get("security") == "reality":
            result["reality"] = True
        elif entry.get("protocol") == "hysteria":
            result["hysteria"] = True
    return result
