"""Verify wizard reveals each prompt only after the previous answer.
Runs the REAL Bash ask_* functions under a pseudo-terminal; never installs anything.
"""
from pathlib import Path
import os
import pty
import select
import subprocess
import time

source = Path("install.sh").read_text(encoding="utf-8")
begin = source.index("valid_domain(){")
end = source.index("\n# Classic mode remains", begin)
functions = source[begin:end]
assert functions.index("ask_domain(){") < functions.index("ask_email(){") < functions.index("ask_admin(){") < functions.index("ask_password(){")
assert "Повторите пароль" not in functions
assert functions.count("read -r -s -p") == 1
assert "ШАГ " not in functions, "No standalone step heading allowed"
assert all(prompt in functions for prompt in ("'  Домен: '", "'  Email: '", "'  Логин: '", "'  Пароль (не отображается): '"))

shell = (
    "set -Eeuo pipefail\n"
    "gray=''\nreset=''\n"
    + functions
    + "\nask_domain\nask_email\nask_admin\nask_password\n"
    + '[[ "$DOMAIN" == "panel.example.com" && "$EMAIL" == "admin@example.com" && "$ADMIN" == "admin" && "$PASS" == "SecretTest123" ]]\n'
    + "printf 'INSTALL_STARTED\\n'\n"
)

master, slave = pty.openpty()
process = subprocess.Popen(["bash", "-c", shell], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
os.close(slave)
os.set_blocking(master, False)


def wait_for(needle: str, seconds: float = 7.0):
    data = b""
    until = time.monotonic() + seconds
    needle = needle.encode("utf-8")
    while needle not in data and time.monotonic() < until:
        if select.select([master], [], [], 0.2)[0]:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            data += chunk
    assert needle in data, f"Expected wizard message missing: {needle!r}; received {data!r}"
    return data.decode("utf-8")


try:
    # Prompts must arrive one by one, never before their own step.
    first = wait_for("Домен: ")
    assert "Email:" not in first and "Логин:" not in first
    assert "ШАГ" not in first
    os.write(master, b"panel.example.com\n")

    second = wait_for("Email: ")
    assert "Логин:" not in second and "Пароль (не отображается)" not in second
    assert "ШАГ" not in second
    os.write(master, b"admin@example.com\n")

    third = wait_for("Логин: ")
    assert "Пароль (не отображается)" not in third
    os.write(master, b"admin\n")

    fourth = wait_for("Пароль (не отображается): ")
    assert "Повторите пароль" not in fourth and "INSTALL_STARTED" not in fourth
    os.write(master, b"SecretTest123\n")

    completed = wait_for("INSTALL_STARTED")
    assert process.wait(timeout=5) == 0, "Wizard failed before starting the installer"
    assert "SecretTest123" not in (fourth + completed), "Password echoed in terminal"
    assert "Повторите пароль" not in completed, "Unexpected confirmation request"
    print("PASS: domain -> email -> login -> one hidden password -> immediate install")
finally:
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
    os.close(master)
