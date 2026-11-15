"""Automatic, diversity-aware website template delivery for new WPO nodes.

Keeps reservations in the node registry so they survive controller restarts.
Does not touch existing nodes or change templates selected manually.
"""
import base64
from collections import Counter
import os
import re
import secrets
import sys
import threading
import time

registry_lock = threading.RLock()
_started = False
_ASSET = re.compile(r"/(preset-[A-Za-z0-9_.-]+\.webp)")
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_ROOT = "/srv/tproxy-site"


def _eligible(presets):
    """Only publish templates supported by the existing node-site API."""
    ready = {}
    for p in presets:
        if not isinstance(p, dict):
            continue
        tid = str(p.get("id", "")).strip()
        page = p.get("html", "")
        if not _ID.fullmatch(tid) or not isinstance(page, str):
            continue
        if not page or len(page.encode("utf-8")) > 2100000:
            continue
        names = sorted(set(_ASSET.findall(page)))
        total = 0
        ok = True
        for name in names:
            try:
                size = os.stat(os.path.join(_ROOT, name)).st_size
            except OSError:
                ok = False
                break
            if size > 2000000:
                ok = False
                break
            total += size
            if total > 6500000:
                ok = False
                break
        if ok:
            ready[tid] = p
    return ready


def choose(nodes, presets):
    """Random among least used, so no repeats while free presets remain."""
    candidates = _eligible(presets)
    if not candidates:
        return ""
    used = Counter()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        tid = str(node.get("auto_site_template_id") or node.get("site_template_id") or "")
        if tid in candidates:
            used[tid] += 1
    least = min(used.get(tid, 0) for tid in candidates)
    pool = [tid for tid in candidates if used.get(tid, 0) == least]
    return secrets.choice(pool)


def _payload(presets, template_id):
    p = _eligible(presets).get(template_id)
    if p is None:
        raise ValueError("Шаблон больше не доступен или отсутствуют его изображения")
    page = p["html"]
    assets = []
    total = 0
    for name in sorted(set(_ASSET.findall(page))):
        with open(os.path.join(_ROOT, name), "rb") as f:
            raw = f.read(2000001)
        if len(raw) > 2000000:
            raise ValueError("Изображение шаблона превышает 2 МБ")
        total += len(raw)
        if total > 6500000:
            raise ValueError("Изображения шаблона превышают 6.5 МБ")
        assets.append({"name": name, "data": base64.b64encode(raw).decode("ascii")})
    return {"template_id": template_id, "html": page, "assets": assets}


def _loop(path, all_presets, node_api):
    retry = {}
    while True:
        try:
            with registry_lock:
                nodes = node_api.load_nodes(path)
                waiting = [
                    (str(n.get("id", "")), str(n.get("auto_site_template_id", "")))
                    for n in nodes
                    if isinstance(n, dict) and n.get("auto_site_template_id")
                ]
            now = time.monotonic()
            ids = {nid for nid, _ in waiting}
            for nid in list(retry):
                if nid not in ids:
                    retry.pop(nid, None)
            for nid, tid in waiting:
                scheduled, failures = retry.get(nid, (0, 0))
                if now < scheduled:
                    continue
                try:
                    with registry_lock:
                        current = node_api.load_nodes(path)
                        selected = next((n for n in current if n.get("id") == nid), None)
                        if not selected or selected.get("auto_site_template_id") != tid:
                            retry.pop(nid, None)
                            continue
                        # The worker never replaces a manually configured site.
                        if selected.get("site_template_id"):
                            selected.pop("auto_site_template_id", None)
                            node_api.save_nodes(path, current)
                            retry.pop(nid, None)
                            continue
                        node_copy = dict(selected)
                    payload = _payload(all_presets(), tid)
                    node_api.request(
                        node_copy, "POST", node_api.API_PREFIX + "/site-template",
                        payload, timeout=30,
                    )
                    with registry_lock:
                        fresh = node_api.load_nodes(path)
                        for node in fresh:
                            if node.get("id") == nid and node.get("auto_site_template_id") == tid:
                                if not node.get("site_template_id"):
                                    node["site_template_id"] = tid
                                node.pop("auto_site_template_id", None)
                                node_api.save_nodes(path, fresh)
                                break
                    retry.pop(nid, None)
                    print("Auto node template published:", nid, tid, file=sys.stderr, flush=True)
                except Exception as exc:
                    failures += 1
                    delay = min(300, 8 * (2 ** min(failures - 1, 5)))
                    retry[nid] = (time.monotonic() + delay, failures)
                    print("Auto node template retry:", nid, type(exc).__name__,
                          "in", delay, "seconds", file=sys.stderr, flush=True)
        except Exception as exc:
            print("Auto node template worker:", type(exc).__name__, file=sys.stderr, flush=True)
        time.sleep(3)


def start(path, all_presets, node_api):
    global _started
    if _started:
        return
    _started = True
    threading.Thread(
        target=_loop, args=(path, all_presets, node_api),
        name="wpo-node-autotemplate", daemon=True,
    ).start()
