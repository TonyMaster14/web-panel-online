#!/usr/bin/env python3
"""WPO read-only Remnawave comparison audit v1.
Reads Docker, live RemnaNode Xray config and selected panel config metadata.
Never restarts services, changes configuration, or exports credentials.
The only write is a redacted JSON report under /root (mode 0600).
"""
import datetime
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

VERSION = "1.0"
MAX_CAPTURE = 12 * 1024 * 1024
MAX_LINES = 120
REDACT = "[REDACTED]"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
UUID = re.compile(r"(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE = re.compile(r"(?i)(secret|password|passwd|passphrase|private.?key|token|api.?key|credential|authorization|jwt|cookie|certificate|cert.?pem|bearer|subscription.?url|session.?id|client.?id|auth.?key|public.?key|short.?id|encryption.?key|user.?id|refresh.?key)")
SPECIAL_KEYS = {"clients", "users", "accounts", "deviceSecrets", "shortIds", "certificates", "peers"}
LOG_TOKENS = ("error", "warn", "fail", "xray", "reality", "config", "routing", "profile", "sync", "connect")

def run(*args, timeout=12):
    try:
        p = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, check=False)
        if len(p.stdout) > MAX_CAPTURE:
            return 125, "", "output too large"
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")[:500]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 125, "", type(exc).__name__

def fingerprint(val):
    return "sha256:" + hashlib.sha256(str(val).encode()).hexdigest()[:12]

def safe_str(val):
    if not isinstance(val, str):
        return val
    val = ANSI.sub("", val).strip()
    if (len(val) > 480 or "-----BEGIN " in val or
            re.search(r"(?i)(vless|trojan|hysteria2|ss)://", val) or
            re.search(r"(?i)(bearer\s+[a-z0-9._-]{12,}|[?&](token|key|password|auth)=)", val)):
        return "[long or credential-bearing string hidden]"
    val = UUID.sub("[UUID]", val)
    val = EMAIL.sub("[EMAIL]", val)
    # Hide raw long opaque strings (tokens, encoded keys, JWTs).
    if re.fullmatch(r"[A-Za-z0-9_+/=-]{52,}", val):
        return fingerprint(val)
    return val

def scrub(value, key="", depth=0):
    if depth > 20:
        return "[maximum depth]"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:350]:
            ks = str(k)
            kl = ks.lower()
            if kl in ("clients", "users", "accounts", "devices", "peers") and isinstance(v, list):
                out[ks] = {"count": len(v), "individual_entries": "hidden"}
            elif kl in ("shortids", "short_ids") and isinstance(v, list):
                out[ks] = {"count": len(v), "fingerprints": [fingerprint(item) for item in v[:10]]}
            elif kl in ("certificates", "keys") and isinstance(v, list):
                out[ks] = {"count": len(v), "content": "hidden"}
            elif SENSITIVE.search(ks):
                if kl in ("publickey", "public_key", "shortid", "short_id"):
                    out[ks] = fingerprint(v)
                elif isinstance(v, list):
                    out[ks] = {"count": len(v), "content": "hidden"}
                else:
                    out[ks] = REDACT
            else:
                out[ks] = scrub(v, ks, depth + 1)
        if len(value) > 350:
            out["_truncated_keys"] = len(value) - 350
        return out
    if isinstance(value, list):
        out = [scrub(x, key, depth + 1) for x in value[:500]]
        if len(value) > 500:
            out.append({"truncated_items": len(value) - 500})
        return out
    if isinstance(value, str):
        return safe_str(value)
    if isinstance(value, (float, int, bool)) or value is None:
        return value
    return "[unknown type]"

def extract_json(text):
    clean = ANSI.sub("", text.replace("\r", "\n"))
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", clean):
        try:
            obj, _ = decoder.raw_decode(clean, match.start())
            if isinstance(obj, dict) and "inbounds" in obj and "outbounds" in obj:
                return obj
        except (ValueError, TypeError):
            continue
    return None

def inspect_containers():
    rc, stdout, err = run("docker", "ps", "-a", "--format", "{{.Names}}", timeout=12)
    if rc:
        return [], "Docker unavailable: " + err
    names = [x.strip() for x in stdout.splitlines() if x.strip()][:80]
    if not names:
        return [], "No Docker containers"
    rc, stdout, err = run("docker", "inspect", *names, timeout=20)
    if rc:
        return [], "Docker inspect failed: " + err
    try:
        return json.loads(stdout), ""
    except ValueError:
        return [], "Docker inspect returned invalid JSON"

def get_container_summary(c):
    cfg = c.get("Config") or {}
    hostcfg = c.get("HostConfig") or {}
    netcfg = c.get("NetworkSettings") or {}
    env = cfg.get("Env") or []
    return {
        "name": str(c.get("Name", "")).lstrip("/"),
        "image": cfg.get("Image"),
        "image_id": str(c.get("Image", ""))[:30],
        "running": (c.get("State") or {}).get("Running", False),
        "started_at": (c.get("State") or {}).get("StartedAt"),
        "network_mode": hostcfg.get("NetworkMode"),
        "port_bindings": scrub(hostcfg.get("PortBindings") or {}),
        "docker_networks": sorted((netcfg.get("Networks") or {}).keys()),
        "mounts": [{"source": safe_str(x.get("Source", "")),
                    "target": safe_str(x.get("Destination", "")),
                    "read_only": not bool(x.get("RW", False))}
                   for x in (c.get("Mounts") or [])[:40]],
        "environment_variable_names_only": sorted({str(k).split("=", 1)[0] for k in env}),
        "health": ((c.get("State") or {}).get("Health") or {}).get("Status"),
    }

def node_dump(name):
    rc, data, err = run("docker", "exec", "-e", "NO_COLOR=1",
                        name, "cli", "--dump-config", timeout=27)
    if rc:
        return None, "cli --dump-config failed (exit %d): %s" % (rc, err[:130])
    obj = extract_json(data)
    if obj is None:
        return None, "Live dump did not contain a valid Xray JSON object"
    return obj, ""

def xray_summary(obj):
    inbound = obj.get("inbounds") or []
    if not isinstance(inbound, list):
        inbound = []
    reality = []
    for entry in inbound:
        if not isinstance(entry, dict):
            continue
        st = entry.get("streamSettings") or {}
        rs = st.get("realitySettings") or {}
        if st.get("security") == "reality":
            reality.append({
                "tag": safe_str(entry.get("tag")),
                "listen": safe_str(entry.get("listen")),
                "port": entry.get("port"),
                "protocol": entry.get("protocol"),
                "network": st.get("network"),
                "sni": scrub(rs.get("serverNames") or []),
                "target": safe_str(rs.get("target") or rs.get("dest") or ""),
                "minClientVer": rs.get("minClientVer"),
                "maxClientVer": rs.get("maxClientVer"),
                "short_id_count": len(rs.get("shortIds") or []),
                "client_count": len((entry.get("settings") or {}).get("clients") or []),
                "sniffing": scrub(entry.get("sniffing")),
                "flow_types": sorted({str(x.get("flow", "")) for x in
                     (entry.get("settings") or {}).get("clients", [])
                     if isinstance(x, dict)}),
            })
    return {
        "inbounds_count": len(inbound),
        "outbounds_count": len(obj.get("outbounds") or []),
        "routing_rules_count": len((obj.get("routing") or {}).get("rules") or []),
        "reality": reality,
        "api_present": "api" in obj,
        "stats_present": "stats" in obj,
        "policy_present": "policy" in obj,
        "dns_present": "dns" in obj,
    }

def postgres_read(container, sql, user, database, password=None):
    command = ["docker", "exec"]
    if password:
        command += ["-e", "PGPASSWORD=" + password]
    command += [container, "psql", "-X", "-A", "-t", "-U", user,
                "-d", database, "-c", sql]
    return run(*command, timeout=18)

def inspect_database(containers):
    result = {"status": "not_found", "tables": [], "config_samples": [], "warnings": []}
    db = next((c for c in containers
               if "postgres" in str((c.get("Config") or {}).get("Image", "")).lower()
               and (c.get("State") or {}).get("Running")), None)
    if not db:
        return result
    name = str(db.get("Name", "")).lstrip("/")
    env = dict(x.split("=", 1) for x in (db.get("Config") or {}).get("Env", [])
               if "=" in x)
    user = env.get("POSTGRES_USER") or "postgres"
    database = env.get("POSTGRES_DB") or user
    pwd = env.get("POSTGRES_PASSWORD")
    result["status"] = "database discovered"
    result["container"] = name
    sql = ("SELECT table_name, column_name, data_type FROM information_schema.columns "
           "WHERE table_schema='public' AND ("
           "lower(table_name) LIKE '%config%' OR "
           "lower(table_name) LIKE '%profile%' OR "
           "lower(table_name) LIKE '%happ%' OR "
           "lower(table_name) LIKE '%rout%' OR "
           "lower(table_name) LIKE '%template%' OR "
           "lower(table_name) LIKE '%host%' OR "
           "lower(table_name) LIKE '%node%') "
           "ORDER BY table_name,column_name LIMIT 320")
    rc, out, err = postgres_read(name, sql, user, database, pwd)
    if rc:
        result["status"] = "DB metadata query unavailable"
        result["warnings"].append(err[:160])
        return result
    cols = []
    for line in out.splitlines():
        chunks = line.split("|")
        if len(chunks) == 3:
            cols.append(tuple(chunks))
    by_table = {}
    for table, col, datatype in cols:
        by_table.setdefault(table, []).append({"name": col, "type": datatype})
    result["tables"] = [{"name": k, "columns": v}
                        for k, v in list(by_table.items())[:30]]
    relevant = [(table, col) for table, fields in by_table.items()
                if any(t in table.lower() for t in ("config", "profile", "happ", "rout", "template"))
                and not any(t in table.lower() for t in ("user", "session", "token", "credential"))
                for col in [f["name"] for f in fields
                            if f["type"] in ("json", "jsonb")]
                if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", table)
                and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", col)][:18]
    for table, col in relevant:
        q = 'SELECT "%s"::text FROM public."%s" WHERE "%s" IS NOT NULL LIMIT 3' % (col, table, col)
        rc, out, err = postgres_read(name, q, user, database, pwd)
        if rc:
            result["warnings"].append("Cannot inspect %s.%s" % (table, col))
            continue
        entries = []
        for line in out.splitlines()[:3]:
            if len(line) > 1000000:
                continue
            try:
                v = json.loads(line)
            except ValueError:
                continue
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    continue
            entries.append(scrub(v))
        if entries:
            result["config_samples"].append({"table": table, "column": col, "samples": entries})
    result["status"] = "metadata and selected configuration inspected"
    return result

def reverse_proxy_config():
    roots = [Path("/opt/remnanode"), Path("/opt/remnawave"), Path("/opt/selfsteal"),
             Path("/etc/nginx/conf.d"), Path("/etc/nginx/sites-enabled"),
             Path("/etc/haproxy"), Path("/etc/caddy")]
    selectors = re.compile(r"(?i)^\s*(?:listen|server_name|proxy_pass|reverse_proxy|proxy_protocol|bind|use_backend|default_backend|backend|frontend|upstream|map|stream|server\s|handle\s|route\s|tls\s|ssl_preread|ssl_protocols|tcp-request|http-request|redir|return\s|respond\s)")
    forbidden = re.compile(r"(?i)(secret|token|password|authorization|private|keyfile|api.?key|credential|cookie)")
    paths = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            paths.append(root)
            continue
        try:
            paths.extend(p for p in root.glob("*.conf") if p.is_file())
            paths.extend(p for p in root.glob("**/Caddyfile") if p.is_file())
            paths.extend(p for p in root.glob("**/*.conf") if p.is_file())
            if root.name in ("haproxy", "caddy"):
                paths.extend(p for p in root.glob("*") if p.is_file())
        except (OSError, PermissionError):
            continue
        if len(paths) > 150:
            paths = paths[:150]
            break
    output = []
    seen = set()
    for p in paths:
        sp = str(p)
        if sp in seen:
            continue
        seen.add(sp)
        try:
            if p.is_symlink() or p.stat().st_size > 250000:
                continue
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        matched = [safe_str(x) for x in content.splitlines()
                   if selectors.search(x) and not forbidden.search(x)]
        if matched:
            output.append({"path": sp, "selected_nonsecret_lines": matched[:90]})
        if len(output) >= 30:
            break
    return output

def safe_host():
    d = {}
    for label, cmd in [
        ("os", ("uname", "-srmo")),
        ("ipv4_routes", ("ip", "-4", "route")),
        ("listening_tcp_udp", ("ss", "-lntu")),
        ("docker_version", ("docker", "version", "--format", "{{.Server.Version}}")),
    ]:
        rc, out, _ = run(*cmd, timeout=6)
        d[label] = [safe_str(x) for x in out.splitlines()[:MAX_LINES]] if rc == 0 else "unavailable"
    rc, out, _ = run("systemctl", "list-units", "--type=service", "--state=running",
                      "--no-pager", "--no-legend", timeout=6)
    d["relevant_systemd_services"] = [safe_str(x) for x in out.splitlines()
         if any(word in x.lower() for word in
                ("xray", "remna", "caddy", "nginx", "haproxy", "docker", "sing-box"))][:50] if rc == 0 else []
    return d

def log_signals(name):
    rc, out, err = run("docker", "logs", "--tail", "220", "--since", "40m",
                        name, timeout=10)
    if rc and not out:
        return {"status": "logs unavailable"}
    selected = [x for x in out.splitlines()
                if any(t in x.lower() for t in LOG_TOKENS)]
    # Never export log lines; they may contain tokens, usernames or raw configs.
    return {"matched_operational_lines": len(selected),
            "error_lines": sum("error" in x.lower() or "fail" in x.lower() for x in selected),
            "warning_lines": sum("warn" in x.lower() for x in selected),
            "raw_logs_exported": False}

def main():
    if os.geteuid() != 0:
        print("Run as root with sudo", file=sys.stderr)
        return 2
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("WPO / Remnawave read-only audit v%s" % VERSION)
    print("Scanning running Remnawave installation; no service restarts or config changes.")
    report = {"audit_version": VERSION, "timestamp_utc": now,
              "privacy": "sanitized; no secret material, UUIDs, or raw logs exported",
              "host": safe_host(), "containers": [], "node_configs": [],
              "database": {}, "reverse_proxy": [], "warnings": []}
    containers, error = inspect_containers()
    if error:
        report["warnings"].append(error)
    for c in containers:
        report["containers"].append(get_container_summary(c))
    for c in containers:
        name = str(c.get("Name", "")).lstrip("/")
        image = str((c.get("Config") or {}).get("Image", "")).lower()
        if not (c.get("State") or {}).get("Running"):
            continue
        if "remnawave/node" in image or name in ("remnanode", "remna") or (
                "remna" in name and "node" in name):
            print("Node found: %s; reading live Xray config..." % name)
            config, err = node_dump(name)
            if config is None:
                report["warnings"].append("%s: %s" % (name, err))
                continue
            summary = xray_summary(config)
            report["node_configs"].append({
                "container": name,
                "source": "live RemnaNode cli --dump-config, not template",
                "summary": summary,
                "xray_configuration_redacted": scrub(config)
            })
            print("  Xray inbounds=%s outbounds=%s routing=%s REALITY=%s" %
                  (summary["inbounds_count"], summary["outbounds_count"],
                   summary["routing_rules_count"], len(summary["reality"])))
    print("Inspecting panel DB metadata/config samples, if local PostgreSQL exists...")
    report["database"] = inspect_database(containers)
    report["reverse_proxy"] = reverse_proxy_config()
    name = re.sub(r"[^A-Za-z0-9_-]", "-", socket.gethostname())[:35]
    path = Path("/root/remnawave-audit-%s-%s.json" % (name, now))
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(raw + "\n")
    print("DONE. Redacted report: %s (%d bytes)" % (path, len(raw)))
    print("Containers=%d, live Xray configs=%d, DB=%s, reverse-proxy files=%d" %
          (len(report["containers"]), len(report["node_configs"]),
           report["database"].get("status"), len(report["reverse_proxy"])))
    for w in report["warnings"][:10]:
        print("NOTE: " + w)
    if not report["node_configs"]:
        print("NOTE: No live Xray dumped here; RemnaWave Panel and Node can be on different VPS.")
        print("Run this SAME command on the RemnaWave Node VPS too.")
    print("Attach the JSON report in ChatGPT. It is redacted, but still review before sharing.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
