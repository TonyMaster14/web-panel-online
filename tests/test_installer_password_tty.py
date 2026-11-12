"""WPO installation password prompt: interactive TTY smoke test, no VPS changes."""
from pathlib import Path
import os
import pty
import select
import subprocess
import time

source = Path("install.sh").read_text(encoding="utf-8")
start = source.index("ask_password(){")
end = source.index("\n# Classic mode remains", start)
function = source[start:end]
assert "Повторите пароль" not in function
assert "CONFIRM" not in function
assert function.count("read -r -s -p") == 1
password = "TerminalTest123"
script = (
    "set -Eeuo pipefail\n"
    "gray=''\ncyan=''\n"
    "reset=''\n"
    "step(){ :; }\n"
    + function
    + "\nask_password\n"
    + '[[ "$PASS" == "TerminalTest123" ]]\n'
    + "printf 'TEST_DONE\\n'\n"
)
master, slave = pty.openpty()
proc = subprocess.Popen(
    ["bash", "-c", script],
    stdin=slave, stdout=slave, stderr=slave,
    close_fds=True,
)
os.close(slave)
os.set_blocking(master, False)
def read_until(needle, timeout=10):
    chunks = b""
    deadline = time.monotonic() + timeout
    while needle not in chunks and time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.25)
        if readable:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            chunks += data
    return chunks
try:
    prompted = read_until("Пароль (не отображается): ".encode("utf-8"))
    assert "Пароль (не отображается): ".encode("utf-8") in prompted, "Prompt missing from terminal"
    os.write(master, (password + "\n").encode("utf-8"))
    output = read_until(b"TEST_DONE")
    assert b"TEST_DONE" in output, "Installer did not continue after one password"
    assert proc.wait(timeout=5) == 0, "Installer password handling returned error"
    combined = prompted + output
    assert password.encode() not in combined, "Terminal echoed hidden password"
    assert "Повторите пароль".encode() not in combined, "Unexpected second prompt"
    print("PASS: terminal prompt in place; one hidden password; immediate continuation")
finally:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)
    os.close(master)
