#!/usr/bin/env python3
"""Reattach an installed WPO node if a stale controller refresh lost its entry.

Run on the NODE VPS as root. Paste a newly generated one-line installer command
at the hidden prompt. It is parsed as data, never executed, and the existing
Node Agent/API keys, profiles, services and ACME certificates are not modified.
"""
import getpass
import json
from pathlib import Path
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request

CONFIG=Path("/etc/wpp-node-agent/config.json")
RECEIPT=Path("/etc/wpp-node-agent/registered.json")

class ReattachError(Exception):
    pass

def parse_command(command):
    try:
        outer=shlex.split(command.strip())
        if outer[:4]!=["sudo","-i","bash","-c"] or len(outer)!=5:
            raise ReattachError("Нужна команда установки, скопированная из WPO.")
        inner=outer[4]
        pattern=(r'curl -4fsSL "([^"\s]+/node-agent-installer\.sh)" '
                 r'-o /tmp/wpo-node-install\.sh && bash /tmp/wpo-node-install\.sh '
                 r'"([A-Za-z0-9_-]{40,60})"; code=\$\?; '
                 r'rm -f /tmp/wpo-node-install\.sh; exit \$code')
        matched=re.fullmatch(pattern,inner)
        if not matched:
            raise ReattachError("Неподдерживаемая команда. Создайте новый установщик в WPO.")
        url,token=matched.groups()
        parts=urllib.parse.urlsplit(url)
        if (parts.scheme!="https" or not parts.hostname or
            parts.port not in (None,443) or parts.username or parts.password or
            parts.fragment or parts.query or not parts.path.endswith("/node-agent-installer.sh")):
            raise ReattachError("Некорректный HTTPS-адрес панели.")
        enroll=url[:-len("/node-agent-installer.sh")]+"/node-enroll"
        return enroll,token
    except ValueError as exc:
        raise ReattachError("Некорректная команда установки.") from exc

def request_json(url, method, headers=None, payload=None):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       urllib.request.HTTPHandler(),
                                       urllib.request.HTTPSHandler())
    body=None if payload is None else json.dumps(payload).encode("utf-8")
    req=urllib.request.Request(url,data=body,method=method,headers=headers or {})
    try:
        with opener.open(req,timeout=20) as response:
            if response.geturl()!=url:
                raise ReattachError("Запрещено перенаправление HTTPS.")
            response_body=response.read(32769)
            if len(response_body)>32768:
                raise ReattachError("Ответ сервера слишком большой.")
            return json.loads(response_body)
    except urllib.error.HTTPError as exc:
        if exc.code==400:
            raise ReattachError("Панель отклонила подключение (возможно, нода уже существует).") from exc
        if exc.code==403:
            raise ReattachError("Одноразовый ключ недействителен. Создайте новый.") from exc
        raise ReattachError(f"Панель вернула HTTP {exc.code}.") from exc
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise ReattachError("Сервер недоступен по HTTPS или возникла ошибка TLS.") from exc
    except (ValueError,UnicodeError) as exc:
        raise ReattachError("Сервер вернул некорректный JSON.") from exc

def reattach(config, receipt, installer_command, transport=request_json):
    domain=config.get("domain","")
    key=config.get("api_key","")
    if not isinstance(domain,str) or not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",domain
    ) or not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}",key):
        raise ReattachError("Настройки Node Agent повреждены.")
    if not isinstance(receipt,dict) or receipt.get("registered") is not True or receipt.get("domain")!=domain:
        raise ReattachError("Нода ещё не завершила установку. Повторное подключение запрещено.")
    endpoint,token=parse_command(installer_command)
    status=transport("https://"+domain+"/wpp-api/v1/status","GET",
                     {"Authorization":"Bearer "+key})
    if not isinstance(status,dict) or status.get("ok") is not True or status.get("domain")!=domain:
        raise ReattachError("Node Agent не подтвердил правильный домен и ключ.")
    data=transport(endpoint,"POST",{"Content-Type":"application/json"},{
        "token":token,"url":"https://"+domain,"api_key":key,
        "name":domain.split(".")[0],
    })
    if not isinstance(data,dict) or data.get("ok") is not True or not data.get("node_id"):
        raise ReattachError("Панель не подтвердила повторную регистрацию.")
    return domain

def main():
    if not hasattr(sys,"real_prefix") and hasattr(__import__("os"),"geteuid") and __import__("os").geteuid()!=0:
        print("Запустите от root на VPS ноды.",file=sys.stderr)
        return 2
    if not CONFIG.is_file() or not RECEIPT.is_file():
        print("Успешно установленный Node Agent не найден. Ничего не изменено.",file=sys.stderr)
        return 2
    try:
        config=json.loads(CONFIG.read_text(encoding="utf-8"))
        receipt=json.loads(RECEIPT.read_text(encoding="utf-8"))
        print("WPO — безопасное повторное подключение уже установленной ноды.")
        print("В основной панели: «Добавить ноду» → «Сгенерировать установщик».")
        print("Вставьте НОВУЮ полную команду сюда. Она НЕ будет запущена.")
        command=getpass.getpass("Команда WPO (ввод скрыт): ")
        domain=reattach(config,receipt,command)
        print("✓ Нода "+domain+" повторно зарегистрирована.")
        print("Существующие профили, сертификаты и сервисы не изменены.")
        print("Обновите страницу «Ноды» в панели.")
        return 0
    except (ReattachError,ValueError,TypeError,OSError) as exc:
        print("Ошибка: "+str(exc),file=sys.stderr)
        return 4

if __name__=="__main__":
    sys.exit(main())
