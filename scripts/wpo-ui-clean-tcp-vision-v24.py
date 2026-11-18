#!/usr/bin/env python3
"""WPO UI-only: remove the word Vision and its surrounding separators after TCP.

This does not change protocol configuration, VLESS REALITY titles, node IDs,
or the actual REALITY Vision technology. It only edits text in UI source literals.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

APP = Path("/opt/tproxy-panel")
SERVICE = "tproxy-panel.service"
BACKUP_ROOT = Path("/var/backups/web-panel-online")
MARK = "# WPO_UI_TCP_VISION_CAPTIONS_V24"
# Match displayed text such as:
#   TCP · Vision · общий внешний порт 443
#   TCP · Vision · shared external port 443
#   TCP 443 · Vision · выбранные ноды
#   TCP 443 Vision selected nodes
# but NOT 'VLESS TCP REALITY Vision' (the protocol name).
CAPTION = re.compile(
    r"(TCP(?:[ \t]+443)?)[ \t]*(?:[·•][ \t]*)?Vision"
    r"(?:[ \t]*[·•][ \t]*|[ \t]+|(?=[<\"']|$))"
)

def clean(text):
    return CAPTION.sub(lambda m: m.group(1) + (
        " " if m.group(0).endswith((" ", "\t")) else ""
    ), text)

def active():
    return subprocess.run(["systemctl", "is-active", "--quiet", SERVICE], check=False).returncode == 0

def main():
    parser = argparse.ArgumentParser(description="WPO V24: shorten TCP captions, UI only")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("Запускайте через sudo")
    if not APP.is_dir() or not (APP / "panel.py").is_file() or not (APP / "wpp_ui.py").is_file():
        raise RuntimeError("Установленная WPO не найдена; изменений нет")
    if (APP / "panel.py").is_symlink() or (APP / "wpp_ui.py").is_symlink():
        raise RuntimeError("Неожиданные ссылки в установке WPO; изменений нет")
    # Only Python source files in the WPO application directory, never files
    # in virtual environments, node agents, or configuration directories.
    source_files = sorted(p for p in APP.glob("*.py") if p.is_file() and not p.is_symlink())
    changes = {}
    for path in source_files:
        src = path.read_text(encoding="utf-8")
        dst = clean(src)
        if dst != src:
            compile(dst, str(path), "exec")
            changes[path] = dst
    if not changes:
        print("✓ Подписи TCP уже очищены. Изменений нет.")
        return
    print("✓ Будут изменены только подписи:", ", ".join(p.name for p in changes))
    if args.check:
        print("✓ Проверка завершена, файлы не изменены.")
        return
    if not active():
        raise RuntimeError("WPO была остановлена до обновления; изменений нет")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    backup_dir = BACKUP_ROOT / ("ui-vision-v24-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if backup_dir.exists():
        raise RuntimeError("Резервная копия с таким именем уже существует")
    backup_dir.mkdir(mode=0o700)
    os.chmod(backup_dir, 0o700)
    for path in changes:
        shutil.copy2(path, backup_dir / path.name)
        os.chmod(backup_dir / path.name, 0o600)
    print("✓ Резервная копия:", backup_dir)
    staged = {}
    replaced = []
    try:
        for path, dst in changes.items():
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, prefix=".wpo-v24-",
                suffix=".py", delete=False
            ) as stream:
                stream.write(dst)
                staged[path] = Path(stream.name)
            old = path.stat()
            os.chown(staged[path], old.st_uid, old.st_gid)
            os.chmod(staged[path], stat.S_IMODE(old.st_mode))
        for path, tmp in staged.items():
            os.replace(tmp, path)
            replaced.append(path)
        subprocess.run(["systemctl", "restart", SERVICE], check=True, timeout=45)
        for _ in range(15):
            if active():
                print("✓ WPO работает. Подписи 'TCP ... Vision ...' очищены.")
                print("✓ VLESS REALITY, ноды, подключения, ключи и конфигурации не менялись.")
                return
            time.sleep(1)
        raise RuntimeError("WPO не запустилась после обновления")
    except Exception:
        if replaced:
            for path in replaced:
                shutil.copy2(backup_dir / path.name, path)
            subprocess.run(["systemctl", "restart", SERVICE], check=False)
            print("! Выполнен откат к прежним файлам WPO")
        raise
    finally:
        for tmp in staged.values():
            tmp.unlink(missing_ok=True)

if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("ОШИБКА:", exc, file=sys.stderr)
        sys.exit(1)
