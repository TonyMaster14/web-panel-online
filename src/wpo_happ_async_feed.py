#!/usr/bin/env python3
"""WPO: verified asynchronous remote VLESS/Hysteria provisioning for Happ.

No fictitious credentials. A node is included only AFTER authenticated POST
federation/sync returned its complete and verified protocol URLs. Slow node
reconfiguration runs outside the subscription HTTP request; global workers
are bounded. A remote-only feed with nothing ready must still report pending.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import threading
import time
import sys
from urllib.parse import urlparse

WORKERS = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="wpo-fed")
LOCK = threading.RLock()
CACHE = {}
PENDING = {}
FAILURES = {}
CACHE_TTL = 86400
RETRY_DELAY = 30
MAX_ENTRIES = 2048


def verified_links(api, node, external_id, name, protocols, timeout=90):
    """Return ordered real remote links, never construct the remote secrets."""
    if not protocols or len(set(protocols)) != len(protocols):
        raise ValueError("Invalid remote protocols")
    result = api.request(node, "POST", api.API_PREFIX + "/federation/sync", {
        "external_id": external_id, "name": name, "protocols": list(protocols)
    }, timeout=timeout)
    entries = result.get("profiles") if isinstance(result, dict) else None
    if not isinstance(entries, list) or len(entries) != len(protocols):
        raise api.NodeError("Нода вернула неполный набор VPN-протоколов")
    matches = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise api.NodeError("Нода вернула некорректный профиль")
        protocol = entry.get("protocol")
        uri = entry.get("link")
        expected_scheme = {"vless": "vless", "reality": "vless", "hysteria": "hysteria2"}.get(protocol)
        if (protocol not in protocols or protocol in matches
                or not isinstance(uri, str) or len(uri) > 8192
                or not expected_scheme):
            raise api.NodeError("Нода вернула неподдерживаемый протокол")
        parsed = urlparse(uri)
        if (parsed.scheme.lower() != expected_scheme
                or not parsed.hostname
                or parsed.hostname != urlparse(node.get("url", "")).hostname):
            raise api.NodeError("Нода вернула неверный адрес VPN")
        matches[protocol] = uri
    if set(matches) != set(protocols):
        raise api.NodeError("Нода не вернула все выбранные VPN-протоколы")
    return [matches[p] for p in protocols]


def _sync_worker(key, api, node, external_id, name, protocols):
    success = None
    try:
        success = verified_links(api, node, external_id, name, protocols, timeout=90)
    except Exception as exc:
        # Print only the safe class, not server text, domains, tokens or links.
        error_kind = type(exc).__name__
        # Node ID is opaque; never log HTTP response bodies or credentials.
        print("wpo asynchronous node sync failed:", key[0], error_kind,
              file=sys.stderr, flush=True)
        with LOCK:
            FAILURES[key] = (time.monotonic() + RETRY_DELAY, error_kind)
    else:
        with LOCK:
            CACHE[key] = (time.monotonic() + CACHE_TTL, tuple(success))
            FAILURES.pop(key, None)
    finally:
        with LOCK:
            PENDING.pop(key, None)
    return success


def enqueue(api, node, external_id, name, protocols):
    """Return (verified links or [], preparing bool), never block for network."""
    if not node.get("enabled", True):
        return [], False
    protocols = tuple(protocols)
    key = (str(node.get("id", "")), str(node.get("url", "")),
           hashlib.sha256(str(node.get("token", "")).encode()).hexdigest(),
           external_id, protocols)
    now = time.monotonic()
    with LOCK:
        item = CACHE.get(key)
        if item and item[0] > now:
            return list(item[1]), False
        if key in PENDING:
            return [], True
        failure = FAILURES.get(key)
        if failure and failure[0] > now:
            return [], True
        # Clean up expired entries when bounded memory is approached.
        if len(CACHE) > MAX_ENTRIES:
            CACHE.clear()
        if len(FAILURES) > MAX_ENTRIES:
            FAILURES.clear()
        if len(PENDING) >= 4:
            return [], True
        # Reserve the slot before starting a worker: a fast completed task
        # must not race with setting the PENDING flag afterwards.
        PENDING[key] = True
        try:
            WORKERS.submit(_sync_worker, key, api, dict(node),
                           external_id, name, protocols)
        except RuntimeError:
            PENDING.pop(key, None)
            raise
        return [], True


def collect(api, node_items, external_id, protocols, *, grace_seconds=4.5):
    """Launch all remote setups at once; wait ≤4.5s total, never per server.

    Returns (all verified links in chosen order, number of pending nodes).
    Even when a remote fails, a local+remote subscription remains importable:
    the next Happ refresh includes newly verified nodes.
    """
    items = [(n, api.location_prefix(n)) for n in node_items]
    for node,name in items:
        enqueue(api,node,external_id,name,protocols)
    deadline=time.monotonic()+max(0.0,min(float(grace_seconds),6.0))
    while items and time.monotonic()<deadline:
        with LOCK:
            keys=[(str(n.get("id","")),str(n.get("url","")),
                   hashlib.sha256(str(n.get("token","")).encode()).hexdigest(),
                   external_id,tuple(protocols)) for n,_ in items]
            if not any(k in PENDING for k in keys):
                break
        time.sleep(0.075)
    links=[]
    pending=0
    for node,name in items:
        batch,waiting=enqueue(api,node,external_id,name,protocols)
        if batch:
            links.extend(batch)
        else:
            pending+=1
    return links,pending


def invalidate_all():
    """Invalidate cached credentials after a subscription revocation/update."""
    with LOCK:
        CACHE.clear()
        FAILURES.clear()



def prewarmed(nodes, external_id, protocols):
    """Return true only when the controller verified each remote in advance.

    The preparer stores timestamps only, not credentials. During Happ fetch
    the remote link is verified against the node's authenticated API.
    """
    try:
        store = json.loads(
            Path("/var/lib/tproxy-panel/happ-node-ready.json").read_text(encoding="utf-8")
        )
        if not isinstance(store, dict):
            return False
        now = time.time()
        for node in nodes:
            if not node.get("enabled", True):
                return False
            key = hashlib.sha256((
                external_id + ":" + str(node.get("id", "")) + ":" +
                str(node.get("url", "")) + ":" + ",".join(protocols)
            ).encode()).hexdigest()
            age = now - int(store.get(key, 0))
            if not 0 <= age < 12 * 3600:
                return False
        return bool(nodes)
    except (OSError, ValueError, TypeError, UnicodeError):
        return False


def warm(api, node, external_id, name, protocols):
    """One-time blocking prewarm outside Happ HTTP; uses same verified cache."""
    protocols = tuple(protocols)
    key = (str(node.get("id", "")), str(node.get("url", "")),
           hashlib.sha256(str(node.get("token", "")).encode()).hexdigest(),
           external_id, protocols)
    result = verified_links(api, node, external_id, name, protocols, timeout=90)
    with LOCK:
        CACHE[key] = (time.monotonic() + CACHE_TTL, tuple(result))
        FAILURES.pop(key, None)
    return result
