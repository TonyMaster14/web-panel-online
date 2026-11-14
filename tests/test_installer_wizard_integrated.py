"""Run the actual WPO interactive installer under a PTY against a fake backend.
The backend reproduces progress, success, failure and incomplete-result cases.
This test does NOT install real services, modify real panel configs or use a VPS.
"""
from pathlib import Path
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import tempfile
import termios
import time

SOURCE = Path("install.sh").read_text(encoding="utf-8")
CARD_SOURCE = Path("install-panel.sh").read_text(encoding="utf-8")
CARD_MARK = "# Final access card:"
assert CARD_SOURCE.count(CARD_MARK) == 1

MOCK_BACKEND = r"""#!/usr/bin/env bash
set -Eeuo pipefail
[[ -s "$WPO_UI_CREDENTIALS_FILE" && -f "$WPO_UI_PROGRESS_FILE" ]] || exit 31
ADMIN="$(sed -n '1p' "$WPO_UI_CREDENTIALS_FILE")"
PASS="$(sed -n '2p' "$WPO_UI_CREDENTIALS_FILE")"
[[ "$ADMIN" == WPOAdmin && "$PASS" == Secret-6789 ]] || exit 32
DOMAIN=panel.example.com
PANEL_PATH=/panel-1234567890abcdef1234567890abcdef
UPDATING=0
printf '58\tУстановка панели\n' > "$WPO_UI_PROGRESS_FILE"
sleep .4
printf '80\tУстановка нод\n' > "$WPO_UI_PROGRESS_FILE"
sleep .4
printf '99\tПроверка подключения Xray\n' > "$WPO_UI_PROGRESS_FILE"
sleep .4
case "$WPO_TEST_CASE" in
  failed)
    printf 'MOCK_BACKEND_FAILED\n' >&2
    exit 27
    ;;
  missing-card)
    exit 0
    ;;
  success)
    ;;
  *)
    exit 33
    ;;
esac
""" + "\n" + CARD_SOURCE[CARD_SOURCE.index(CARD_MARK):] + "\nprintf '100\\tУстановка завершена\\n' > \"$WPO_UI_PROGRESS_FILE\"\n"

def run_case(case):
    with tempfile.TemporaryDirectory(prefix="wpo-wizard-pty-") as temporary:
        directory = Path(temporary)
        # Only privilege/host paths and timing are substituted; real rendering runs.
        source=SOURCE.replace('[[ $EUID -eq 0 ]]', 'true').replace('/run/', str(directory)+'/').replace('/var/log/web-panel-online', str(directory)+'/logs')
        source=source.replace('-o root -g root ', '').replace('</dev/tty','<&0')
        source=source.replace('sleep 1', 'sleep .01').replace('sleep 2', 'sleep .02')
        (directory / "install.sh").write_text(source, encoding="utf-8")
        (directory / "install-final.sh").write_text(MOCK_BACKEND, encoding="utf-8")
        (directory / "node-install.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (directory / "wpp_subscriptions.py").write_text("# mock dependency\n", encoding="utf-8")

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 38, 90, 0, 0))
        env = dict(os.environ, TERM="xterm-256color", WPO_TEST_CASE=case)
        process = subprocess.Popen(
            ["bash", str(directory / "install.sh")],
            stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
        )
        os.close(slave)
        buffer = bytearray()
        offset = 0

        def receive(needle, timeout=20):
            nonlocal offset
            expected = needle.encode("utf-8")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                position = bytes(buffer).find(expected, offset)
                if position >= 0:
                    offset = position + len(expected)
                    return
                if select.select([master], [], [], 0.2)[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    buffer.extend(data)
            raise AssertionError(f"{case}: missing {needle!r}; output tail={bytes(buffer[-2000:])!r}")

        def drain():
            for _ in range(12):
                if not select.select([master], [], [], 0.05)[0]:
                    return
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return
                if not data:
                    return
                buffer.extend(data)

        try:
            receive("q — выход")
            os.write(master, b"\n")
            receive("Домен:")
            os.write(master, b"panel.example.com\n")
            receive("Email:")
            os.write(master, b"admin@example.com\n")
            receive("Логин:")
            os.write(master, b"WPOAdmin\n")
            receive("Пароль (не отображается):")
            os.write(master, b"Secret-6789\n")
            receive("УСТАНОВКА")
            deadline=time.monotonic()+35
            while process.poll() is None and time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try: buffer.extend(os.read(master,65536))
                    except OSError: break
            rc = process.wait(timeout=5)
            drain()
            raw = bytes(buffer)
            decoded = raw.decode("utf-8", errors="replace")
            plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", decoded)
            assert "Secret-6789" not in decoded[:decoded.find("УСТАНОВКА")], "Password echoed in input section"
            if case == "success":
                assert rc == 0, (rc, decoded[-4000:])
                assert "УСТАНОВКА ЗАВЕРШЕНА!" in decoded, decoded[-4000:]
                assert "100%" in decoded, decoded[-4000:]
                assert "Этап:" in plain, plain[-4000:]
                # After 1 sec, the cursor returns to the wizard header, then
                # everything below it is erased, leaving only the real access card.
                parts = raw.split(b"\x1b[H")
                assert len(parts) >= 2, "The final same-window cursor-home transition did not run"
                final_screen = parts[-1].decode("utf-8", errors="replace")
                final_plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", final_screen)
                assert "\x1b[2J" in decoded
                assert "WEB PANEL ONLINE 3.0" in final_plain
                assert "WPO 3.0 — УСТАНОВЛЕНО" in final_plain
                assert "Сохраните данные, чтобы не потерять!" in final_plain
                assert "Ссылка на панель:" in final_plain
                assert "https://panel.example.com/panel-1234567890abcdef1234567890abcdef/login" in final_plain
                # The full link appears INSIDE the frame, before its bottom border.
                card_tail=final_plain.split('WPO 3.0 — УСТАНОВЛЕНО',1)[1]
                assert card_tail.index('Ссылка на панель:') < card_tail.index('╰')
                assert any('https://panel.example.com/panel-1234567890abcdef1234567890abcdef/login' in line and line.count('│') == 2 for line in final_plain.splitlines())
                assert "Логин: WPOAdmin" in final_plain
                assert "Пароль: Secret-6789" in final_plain
                # Final title banner and credentials frame have exactly the
                # same horizontal length; both headings are centered in it.
                final_rows=final_plain.splitlines()
                opening_frames=[line for line in final_rows if line.startswith('╭') and line.endswith('╮')]
                assert len(opening_frames)==2, opening_frames
                assert opening_frames[0]==opening_frames[1], opening_frames
                assert len(opening_frames[0])>64, "Long URLs must extend the banner past its old 62-column limit"
                for heading in ("WEB PANEL ONLINE 3.0", "МАСТЕР УСТАНОВКИ"):
                    row=next(line for line in final_rows if heading in line and line.startswith('│'))
                    assert len(row)==len(opening_frames[0]), (heading,len(row),len(opening_frames[0]))
                    interior=row[1:-1]
                    left=len(interior)-len(interior.lstrip(' '))
                    right=len(interior)-len(interior.rstrip(' '))
                    assert abs(left-right)<=1, (heading,left,right)
                for unwanted in ("Домен:", "Email:", "ХОД УСТАНОВКИ", "УСТАНОВКА ЗАВЕРШЕНА!", "100%", "◷ 00:"):
                    assert unwanted not in final_plain, (unwanted, final_plain)
            elif case == "failed":
                assert rc == 27, (rc, decoded[-2000:])
                assert "Установка прервана" in decoded
                assert "УСТАНОВКА ЗАВЕРШЕНА!" not in decoded, "False success after backend failure"
                assert "Ссылка на панель:" not in decoded, "Credentials printed after backend failure"
            elif case == "missing-card":
                assert rc != 0, "Installation must fail if result is absent"
                assert "Нет итоговой карточки доступа" in decoded
                assert "УСТАНОВКА ЗАВЕРШЕНА!" not in decoded, "False success after missing result"
            print("PASS", case, "real Bash wizard + simulated backend, correct terminal result")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            os.close(master)

if __name__ == "__main__":
    for mode in ("success", "failed", "missing-card"):
        run_case(mode)
