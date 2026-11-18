#!/usr/bin/env python3
"""WPO V31: independent, read-only Xray JSON endpoint for older Node Agents.

For test Sweden node (or other pre-V27 nodes). No dependency on V27/V28/V29
on the remote VPS. This script never changes the VPN/Xray configuration,
certificate, user profiles, ports, routing, Caddy or Xray process.
Only wpo-node-vpn.service restarts, with automatic source rollback if the
authenticated API does not return a redacted live JSON.

On main WPO controller: refuses to run (this must run on extra-node VPS).
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener, urlopen

PIN = "f36abb6c16da7ff65538f9b662ac9ec3a7b8914e"
VIEW_URL = ("https://raw.githubusercontent.com/TonyMaster14/web-panel-online/"
            + PIN + "/src/wpo_xray_node_view.py")
NODE = Path("/opt/wpp-node-agent")
API = NODE / "wpo_node_vpn.py"
VIEW = NODE / "wpo_xray_node_view.py"
XRAY_CONFIG = Path("/etc/wpp-node-vpn/xray.json")
NODE_CONFIG = Path("/etc/wpp-node-agent/config.json")
BACKUPS = Path("/var/backups/web-panel-online")
SERVICE = "wpo-node-vpn.service"
ENDPOINT = "/wpp-api/v1/federation/xray-config"
MARK = "# WPO_NODE_READONLY_XRAY_V31"


def active(unit):
    return subprocess.run(["systemctl", "is-active", "--quiet", unit],
                          check=False).returncode == 0


def replace_once(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            "V31: исходник Node Agent отличается (" + label +
            f", совпадений {count}). Файлы не изменялись."
        )
    return source.replace(old, new, 1)


def patch(source):
    """Add route behind existing strict allowlist, Bearer auth and live check."""
    if ENDPOINT in source:
        if 'if operation == "xray-config":' not in source:
            raise RuntimeError("Node Agent содержит частичное изменение JSON API.")
        return source, False
    if 'if operation == "xray-config":' in source:
        raise RuntimeError("Node Agent содержит частичный обработчик JSON API.")
    if "def do_POST(self):" not in source or "if not self.authorized():" not in source:
        raise RuntimeError("В Node Agent не найден защищённый обработчик POST.")
    source = replace_once(
        source,
        '                             "/wpp-api/v1/federation/reality",',
        '                             "/wpp-api/v1/federation/reality",\n'
        '                             "/wpp-api/v1/federation/xray-config",',
        "список разрешённых путей"
    )
    source = replace_once(
        source,
        '            operation = self.path.rsplit("/", 1)[-1]\n'
        '            if operation == "reality":',
        '''            operation = self.path.rsplit("/", 1)[-1]
            if operation == "xray-config":
                # Existing handler already checks Bearer token and live Xray.
                # No write operations, and secrets redacted unless explicitly
                # requested by a previously authenticated controller admin.
                import wpo_xray_node_view
                try:
                    profile = wpo_reality.read_profile() if REALITY_READY else None
                except (OSError, ValueError, TypeError):
                    profile = None
                self.respond(wpo_xray_node_view.view(
                    XRAY, reveal=data.get("reveal") is True,
                    reality_profile=profile
                ))
                return
            if operation == "reality":''',
        "защищённый обработчик после проверки токена"
    )
    source += "\n" + MARK + "\n"
    compile(source, str(API), "exec")
    return source, True


def load_module():
    request = Request(VIEW_URL, headers={"User-Agent": "WPO-V31-Node-Inspector"})
    with urlopen(request, timeout=30) as response:
        raw = response.read(120001)
    if not raw or len(raw) > 120000:
        raise RuntimeError("Некорректный размер модуля Xray")
    data = raw.decode("utf-8")
    if "def view(" not in data or "HIDDEN =" not in data:
        raise RuntimeError("Загружен неизвестный модуль просмотра Xray")
    compile(data, str(VIEW), "exec")
    return data


def check_config():
    if not XRAY_CONFIG.is_file() or XRAY_CONFIG.is_symlink():
        raise RuntimeError("Xray JSON отсутствует: " + str(XRAY_CONFIG))
    size = XRAY_CONFIG.stat().st_size
    if size < 2 or size > 820000:
        raise RuntimeError("Некорректный размер рабочего Xray JSON")
    config = json.loads(XRAY_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("inbounds"), list):
        raise RuntimeError("Xray JSON не содержит списка inbounds")
    print("✓ Серверный JSON доступен; inbound:", len(config["inbounds"]))


def get_token():
    if NODE_CONFIG.is_symlink() or not NODE_CONFIG.is_file():
        raise RuntimeError("Не найден файл API-настроек ноды")
    obj = json.loads(NODE_CONFIG.read_text(encoding="utf-8"))
    token = obj.get("api_key")
    if not isinstance(token, str) or not token:
        raise RuntimeError("У ноды не найден API-токен")
    return token


def post_local():
    token = get_token()
    req = Request(
        "http://127.0.0.1:9089" + ENDPOINT,
        data=b'{"reveal":false}',
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    )
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(req, timeout=5) as response:
            raw = response.read(1048577)
            if len(raw) > 1048576:
                return False, "Ответ API превысил 1 МиБ"
            payload = json.loads(raw.decode("utf-8"))
            good = (response.status == 200 and isinstance(payload, dict)
                    and payload.get("ok") is True
                    and payload.get("secrets_visible") is False
                    and isinstance(payload.get("config"), dict)
                    and isinstance(payload["config"].get("inbounds"), list))
            return good, ("API HTTP 200, inbound: " +
                          str(len(payload["config"]["inbounds"])) +
                          ", ключи скрыты") if good else "Ответ API не прошёл проверку"
    except HTTPError as error:
        return False, "HTTP " + str(error.code)
    except (OSError, URLError, TimeoutError, ValueError, UnicodeError) as error:
        return False, type(error).__name__


def stage(path, content):
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent,
        prefix=".wpo-v31-", suffix=".py", delete=False
    ) as stream:
        stream.write(content)
        result = Path(stream.name)
    if path.exists():
        source = path.stat()
        os.chown(result, source.st_uid, source.st_gid)
        os.chmod(result, stat.S_IMODE(source.st_mode))
    else:
        os.chmod(result, 0o644)
    return result


def main():
    parser = argparse.ArgumentParser(description="Read-only Xray API for old WPO node")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Нужен sudo")
    if (Path("/opt/tproxy-panel/panel.py").is_file()
            and active("tproxy-panel.service")):
        raise RuntimeError("Это основная панель. V31 предназначен только для дополнительной ноды.")
    if not API.is_file() or API.is_symlink() or not active(SERVICE):
        raise RuntimeError("На этом VPS не найдена запущенная дополнительная VPN-нода WPO.")
    if VIEW.is_symlink():
        raise RuntimeError("Неожиданная символическая ссылка модуля просмотра.")
    check_config()
    source = API.read_text(encoding="utf-8")
    proposed, changed = patch(source)

    module_content = load_module()
    existing = None
    if VIEW.exists():
        if not VIEW.is_file():
            raise RuntimeError("Некорректный путь к модулю просмотра.")
        existing = VIEW.read_text(encoding="utf-8")
        compile(existing, str(VIEW), "exec")
        if "def view(" not in existing or "HIDDEN =" not in existing:
            raise RuntimeError("Неизвестный установленный модуль; не перезаписываем.")
    needs_module = existing is None
    if not changed and not needs_module:
        ok, result = post_local()
        print(("✓ " if ok else "✗ ") + "Проверка текущего JSON API: " + result)
        if not ok:
            raise RuntimeError("Обработчик есть, но API не работает. Нужна диагностика.")
        return

    changes = {}
    if changed:
        changes[API] = proposed
    if needs_module:
        changes[VIEW] = module_content

    print("✓ Роль: дополнительная нода; V27 не требуется.")
    print("✓ Будет обновлён только API просмотра:", ", ".join(p.name for p in changes))
    if args.check:
        print("✓ Предварительная проверка пройдена, файлы не менялись.")
        return

    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = BACKUPS / ("xray-view-v31-node-" +
                        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if backup.exists():
        raise RuntimeError("Папка резервной копии уже существует")
    backup.mkdir(mode=0o700)
    for path in changes:
        if path.exists():
            shutil.copy2(path, backup / path.name)
            os.chmod(backup / path.name, 0o600)
    print("✓ Резервная копия:", backup)

    staged = {}
    replaced = []
    try:
        for path, data in changes.items():
            staged[path] = stage(path, data)
        for path, tmp in staged.items():
            os.replace(tmp, path)
            replaced.append(path)
        subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=45)
        # Verify actual authenticated endpoint, not just 'systemctl active'.
        result = "Node Agent не готов"
        ok = False
        for attempt in range(12):
            if active(SERVICE):
                ok, result = post_local()
                if ok:
                    break
            time.sleep(1)
        if not ok:
            raise RuntimeError("JSON API не отвечает после установки: " + result)
        print("✓ V31 установлен: " + result)
        print("✓ Xray, REALITY, Hysteria2, порты, подписки не изменялись.")
    except Exception:
        for path in replaced:
            previous = backup / path.name
            if previous.exists():
                shutil.copy2(previous, path)
            else:
                path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "restart", SERVICE],
                       check=False, timeout=45)
        print("! Установка не прошла проверку; Node Agent восстановлен.")
        raise
    finally:
        for tmp in staged.values():
            tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print("ОШИБКА:", error, file=sys.stderr)
        sys.exit(1)
