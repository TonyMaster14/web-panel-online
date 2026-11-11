"""Fail-safe country detection for remote WPO Node Agent nodes.

Never assumes a flag from a hostname, and never overrides admin-renamed nodes.
"""
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

COUNTRY_RU = {
    "BR": "Бразилия", "AR": "Аргентина", "CL": "Чили", "CO": "Колумбия",
    "MX": "Мексика", "PE": "Перу", "PT": "Португалия", "GR": "Греция",
    "CY": "Кипр", "IL": "Израиль", "IN": "Индия", "AU": "Австралия",
    "ZA": "ЮАР", "KR": "Южная Корея", "ID": "Индонезия", "TH": "Таиланд",
    "VN": "Вьетнам", "GE": "Грузия", "AM": "Армения", "RS": "Сербия",
    "ME": "Черногория", "MD": "Молдова", "BY": "Беларусь",
    "FI": "Финляндия", "DE": "Германия", "NL": "Нидерланды",
    "FR": "Франция", "GB": "Великобритания", "US": "США",
    "CA": "Канада", "SE": "Швеция", "NO": "Норвегия",
    "DK": "Дания", "PL": "Польша", "CZ": "Чехия",
    "AT": "Австрия", "CH": "Швейцария", "ES": "Испания",
    "IT": "Италия", "RO": "Румыния", "BG": "Болгария",
    "TR": "Турция", "KZ": "Казахстан", "RU": "Россия",
    "UA": "Украина", "JP": "Япония", "SG": "Сингапур",
    "HK": "Гонконг", "AE": "ОАЭ", "LT": "Литва",
    "LV": "Латвия", "EE": "Эстония", "IS": "Исландия",
    "IE": "Ирландия", "BE": "Бельгия",
}

def _code(value):
    code = str(value or "").strip().upper()
    return code if re.fullmatch(r"[A-Z]{2}", code) and code != "UN" else ""

def _fetch_json(url, timeout=4):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "WPO-Node-Geo/1.0"}
    )
    class BlockRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), BlockRedirect()
    )
    with opener.open(req, timeout=timeout) as stream:
        data = stream.read(32769)
    if len(data) > 32768:
        return {}
    parsed = json.loads(data.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}

def _public_ipv4(node_url):
    parsed = urllib.parse.urlsplit(str(node_url or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443):
        return ""
    hostname = parsed.hostname
    values = set()
    for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            return ""
        if address.version == 4:
            values.add(str(address))
    return sorted(values)[0] if len(values) == 1 else ""

def lookup_country(node_url):
    """Use several independent HTTPS providers for a public node IPv4."""
    try:
        ip = _public_ipv4(node_url)
    except (OSError, ValueError):
        return {}
    if not ip:
        return {}
    quoted = urllib.parse.quote(ip, safe=".")
    urls = (
        ("https://ipapi.co/" + quoted + "/json/", "country_code", "country_name"),
        ("https://ipwho.is/" + quoted, "country_code", "country"),
        ("https://api.country.is/" + quoted, "country", ""),
    )
    answers = []
    for url, codekey, namekey in urls:
        try:
            result = _fetch_json(url)
            if result.get("success") is False or result.get("error"):
                continue
            code = _code(result.get(codekey))
            if code:
                name = str(result.get(namekey) or "").strip()[:80] if namekey else ""
                answers.append((code, name))
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError, urllib.error.URLError):
            pass
    if not answers:
        return {}
    from collections import Counter
    ranked = Counter(code for code, _ in answers).most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return {}  # Conflicting providers: show the unknown flag, not a false country.
    code = ranked[0][0]
    selected_name = next((name for value, name in answers if value == code and name), code)
    return {"country_code": code, "country_name": COUNTRY_RU.get(code, selected_name)}

def enrich(nodes, now=None):
    """Update incomplete geo and auto-generated names. Return whether to save nodes."""
    now = int(time.time()) if now is None else int(now)
    modified = False
    for n in nodes:
        if not isinstance(n, dict) or not n.get("enabled", True):
            continue
        url = str(n.get("url") or "")
        hostname = urllib.parse.urlsplit(url).hostname or ""
        original_name = str(n.get("name") or "").strip()
        current_code = _code(n.get("country_code"))
        previous_country = str(n.get("country_name") or "")
        inferred_auto = (original_name.casefold() in {
            hostname.split(".")[0].casefold(), "сервер", "нода", previous_country.casefold(), ""
        })
        automatic = n.get("name_auto", inferred_auto) is not False
        if current_code:
            country = COUNTRY_RU.get(current_code)
            if country and previous_country != country:
                n["country_name"] = country
                modified = True
            if automatic and country and original_name != country:
                n["name"] = country
                n["name_auto"] = True
                modified = True
            continue
        if now - int(n.get("geo_checked_at", 0) or 0) < 240:
            continue
        n["geo_checked_at"] = now
        modified = True
        geo = lookup_country(url)
        if geo:
            n.update(geo)
            if automatic:
                n["name"] = geo["country_name"]
                n["name_auto"] = True
    return modified
