"""WPO shared multi-node protocol planner (test branch).

Eight protocol backends are distinct: do not claim that installation of Xray
alone enables Telegram, AWG, Naive, or Mieru on additional nodes.

A plan is *not* provisioning. The caller must apply it transactionally to
fully provisioned node services and verify readiness BEFORE issuing links.
"""
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Protocol:
    key: str
    title: str
    family: str
    client: str
    unit_class: str
    multi_node_feed: bool


PROTOCOLS = (
    Protocol("vless", "VLESS XHTTP", "happ", "Happ", "xray", True),
    Protocol("reality", "VLESS REALITY", "happ", "Happ", "xray", True),
    Protocol("hysteria", "Hysteria2", "happ", "Happ", "xray", True),
    Protocol("web", "WEB Proxy", "telegram", "Telegram", "https-proxy", False),
    Protocol("mtproto", "MTProto", "telegram", "Telegram", "mtproxy", False),
    Protocol("awg20", "AmneziaWG 2.0", "amnezia", "Amnezia", "awg", False),
    Protocol("awg31", "AmneziaWG 3.1", "amnezia", "Amnezia", "awg", False),
    Protocol("naive", "NaiveProxy", "other", "Naive", "caddy-naive", False),
    Protocol("mieru", "Mieru", "other", "Mieru", "mita", False),
)

CATALOG = {item.key: item for item in PROTOCOLS}
CAPABILITY_SET = frozenset(CATALOG)
if len(CATALOG) != 9:
    raise RuntimeError("The WPO eight-protocol catalog must have unique keys")


class PlanError(ValueError):
    """Invalid or unprovisionable node/protocol combination."""


def normalize_ids(values: Sequence[str], *, label: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise PlanError(f"{label}: expected an array")
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value or len(value) > 64:
            raise PlanError(f"{label}: invalid entry")
        if value in seen:
            raise PlanError(f"{label}: duplicates are not allowed")
        seen.add(value)
        result.append(value)
    if not result:
        raise PlanError(f"{label}: choose at least one")
    return result


def node_capabilities(node: Mapping) -> frozenset[str]:
    """Only services verified by the running node are eligible.

    A cache of protocol names is insufficient. The calling controller must
    obtain these from its authenticated live status, not from user input.
    """
    raw = node.get("capabilities")
    if not isinstance(raw, (list, tuple)) or any(not isinstance(v, str) for v in raw):
        return frozenset()
    if node.get("online") is not True or node.get("vpn_ready") is not True:
        return frozenset()
    return frozenset(v for v in raw if v in CATALOG)


def plan_subscription(
    selected_nodes: Sequence[str],
    selected_protocols: Sequence[str],
    registry: Mapping[str, Mapping],
    *,
    amnezia_node: str | None = None,
) -> dict:
    """Return the exact independently provisioned (node, protocol) pairs.

    VLESS/Hysteria can share one multi-node Happ feed.
    Telegram, Naive and Mieru have native links, not Happ URLs.
    AmneziaWG uses ONE explicitly selected node per config (no phantom
    cross-node WG link). An operator may create other configs separately.
    """
    nodes = normalize_ids(selected_nodes, label="Ноды")
    protocols = normalize_ids(selected_protocols, label="Протоколы")
    for protocol in protocols:
        if protocol not in CATALOG:
            raise PlanError("Unknown protocol: " + protocol)
    for node_id in nodes:
        if node_id not in registry:
            raise PlanError("Unknown node: " + node_id)
    has_awg = any(CATALOG[p].family == "amnezia" for p in protocols)
    if has_awg:
        if amnezia_node is None:
            if len(nodes) > 1:
                raise PlanError("Для Amnezia выберите одну конкретную ноду")
            amnezia_node = nodes[0]
        if amnezia_node not in nodes:
            raise PlanError("Нода Amnezia должна быть среди выбранных")
    elif amnezia_node is not None:
        raise PlanError("Нода Amnezia указана без протокола AmneziaWG")

    by_family = {"happ": [], "telegram": [], "amnezia": [], "other": []}
    unavailable = []
    for protocol in protocols:
        definition = CATALOG[protocol]
        assigned_nodes = [amnezia_node] if definition.family == "amnezia" else nodes
        for node_id in assigned_nodes:
            node = registry[node_id]
            if protocol not in node_capabilities(node):
                unavailable.append((node_id, protocol))
                continue
            by_family[definition.family].append({
                "node_id": node_id,
                "protocol": protocol,
                "client": definition.client,
                "link_ready": False,  # not until server-side apply returns success
            })
    if unavailable:
        desc = ", ".join(f"{n}/{p}" for n, p in unavailable)
        raise PlanError("На выбранной ноде VPN-служба не готова: " + desc)
    result = {
        "node_ids": nodes, "protocols": protocols,
        "happ_subscription": {
            "format": "base64-links",
            "connections": by_family["happ"],
            "one_url": bool(by_family["happ"]),
        },
        "telegram_links": by_family["telegram"],
        "amnezia_profiles": by_family["amnezia"],
        "other_native_links": by_family["other"],
        "connection_count": sum(map(len, by_family.values())),
    }
    return result
