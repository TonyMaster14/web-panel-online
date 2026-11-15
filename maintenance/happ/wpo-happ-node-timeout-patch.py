#!/usr/bin/env python3
"""Primary WPO only: classify remote federation HTTP errors and allow one-time setup.

The controller used an opaque 20-second timeout for POST federation/sync.
A newly provisioned node may need longer, and losing the HTTP status made
remote Xray failures indistinguishable from a broken API token. Do not echo
arbitrary backend response text: it could contain secrets.
"""
import argparse
import ast
from pathlib import Path

BEFORE_TIMEOUT="""    }, timeout=20)


def delete_profile(node, external_id):"""
AFTER_TIMEOUT="""    }, timeout=90)


def delete_profile(node, external_id):"""
OLD_EXCEPTION="""    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise NodeError('Нода не отвечает или отклонила API-токен.') from exc"""
NEW_EXCEPTION="""    except urllib.error.HTTPError as exc:
        # Distinguish a failing VPN-profile POST from bad credentials or a
        # timeout, without exposing remote user secrets or raw error bodies.
        reason = ''
        if path == API_PREFIX + '/federation/sync':
            try:
                remote = json.loads(exc.read(4096).decode('utf-8'))
                message = remote.get('message', '') if isinstance(remote, dict) else ''
                if isinstance(message, str):
                    if 'Xray configuration validation failed' in message:
                        reason = ' (конфигурация Xray отклонена)'
                    elif 'Xray did not become ready' in message:
                        reason = ' (Xray не запустился)'
                    elif 'VPN service is not ready' in message:
                        reason = ' (VPN-служба не готова)'
                    elif 'Node engine command failed' in message:
                        reason = ' (ошибка запуска серверной службы)'
                    elif 'Node protocols not ready' in message:
                        reason = ' (VPN-протокол недоступен)'
            except (OSError, TypeError, ValueError, UnicodeError):
                pass
        raise NodeError('Нода вернула HTTP ' + str(exc.code) + reason) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        cause = getattr(exc, 'reason', None)
        is_timeout = isinstance(exc, TimeoutError) or isinstance(cause, TimeoutError)
        if is_timeout:
            raise NodeError('Превышено время ожидания ответа VPN-ноды.') from exc
        raise NodeError('Ошибка соединения с VPN-нодой.') from exc
    except json.JSONDecodeError as exc:
        raise NodeError('Нода вернула некорректный JSON.') from exc"""


def patch(source):
    if source.count(BEFORE_TIMEOUT) == 1:
        source = source.replace(BEFORE_TIMEOUT, AFTER_TIMEOUT, 1)
    elif source.count(AFTER_TIMEOUT) != 1:
        raise ValueError('Ожидаемый обработчик sync_profile не найден')
    if source.count(OLD_EXCEPTION) == 1:
        source = source.replace(OLD_EXCEPTION, NEW_EXCEPTION, 1)
    elif source.count(NEW_EXCEPTION) != 1:
        raise ValueError('Ожидаемый обработчик Node API не найден')
    if 'timeout=90' not in source or 'raise NodeError(\'Нода вернула HTTP \'' not in source:
        raise ValueError('Проверка нового обработчика не прошла')
    ast.parse(source, filename='wpp_nodes.py')
    return source


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    content = args.input.read_text(encoding='utf-8')
    args.output.write_text(patch(content), encoding='utf-8')
    print('✓ Node API: ожидание первого VPN-профиля до 90 секунд')
    print('✓ Сбой Xray / HTTP 503 / тайм-аут теперь различаются без вывода ключей')


if __name__ == '__main__':
    main()
