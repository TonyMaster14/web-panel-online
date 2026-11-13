"""PTY integration test of the actual WPO wizard without installing services."""
from pathlib import Path
import fcntl
import os
import pty
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time

ENTRY = Path("install.sh").resolve()
FAKE = r"""#!/usr/bin/env bash
set -Eeuo pipefail
[[ -s "$WPO_UI_CREDENTIALS_FILE" ]] || exit 8
[[ "$WEB_PANEL_PROXY_DOMAIN" == "panel.example.test" ]] || exit 9
[[ "$WEB_PANEL_PROXY_ACME_EMAIL" == "test@example.test" ]] || exit 10
[[ "$(head -n1 "$WPO_UI_CREDENTIALS_FILE")" == "Admin" ]] || exit 11
[[ "$(tail -n1 "$WPO_UI_CREDENTIALS_FILE")" == "DemoSecret123" ]] || exit 12
printf '10\tПодготовка сервера\n' > "$WPO_UI_PROGRESS_FILE"
sleep 0.3
printf '80\tУстановка нод\n' > "$WPO_UI_PROGRESS_FILE"
sleep 0.3
printf '99\tПроверка подключения Xray\n' > "$WPO_UI_PROGRESS_FILE"
sleep 0.3
case "$WPO_TTY_TEST_CASE" in
    fail) exit 19;;
    empty) exit 0;;
esac
printf '\n  ╭────────────────────────────╮\n  │ WPO 3.0 — УСТАНОВЛЕНО      │\n  ╰────────────────────────────╯\n\n  Ссылка на панель: https://panel.example.test/panel-xyz/login\n  Логин : Admin\n  Пароль : DemoSecret123\n' > "$WPO_UI_RESULT_FILE"
"""

def read_until(master, output, marker):
    deadline=time.monotonic()+15
    while marker not in output and time.monotonic()<deadline:
        ready,_,_=select.select([master],[],[],0.3)
        if ready:
            try: data=os.read(master,32768)
            except OSError: break
            if not data: break
            output+=data
    assert marker in output, ("Missing prompt",marker,output[-800:])
    return output

def check(mode):
    with tempfile.TemporaryDirectory(prefix="wpo-pty-check-") as folder:
        root=Path(folder)
        shutil.copyfile(ENTRY,root/"install.sh")
        (root/"install-final.sh").write_text(FAKE)
        (root/"node-install.sh").write_text("# fake node\n")
        (root/"wpp_subscriptions.py").write_text("# fake subscriptions\n")
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack("HHHH",35,90,0,0))
        env=os.environ.copy()
        env.update({"TERM":"xterm-256color","WPO_TTY_TEST_CASE":mode})
        cmd=["bash",str(root/"install.sh")]
        if os.geteuid()!=0:
            cmd=["sudo","-n"]+cmd
        proc=subprocess.Popen(cmd,stdin=slave,stdout=slave,stderr=slave,env=env,start_new_session=True)
        os.close(slave)
        raw=b""
        try:
            for prompt,answer in [
                ("Ваш выбор:".encode(),b"\n"),
                ("Домен:".encode(),b"panel.example.test\n"),
                (b"Email:",b"test@example.test\n"),
                ("Логин:".encode(),b"Admin\n"),
                ("Пароль (не отображается):".encode(),b"DemoSecret123\n"),
            ]:
                raw=read_until(master,raw,prompt)
                os.write(master,answer)
            deadline=time.monotonic()+25
            while proc.poll() is None and time.monotonic()<deadline:
                ready,_,_=select.select([master],[],[],0.3)
                if ready:
                    try: raw+=os.read(master,32768)
                    except OSError: break
            proc.wait(timeout=3)
            while True:
                ready,_,_=select.select([master],[],[],0.05)
                if not ready: break
                try: data=os.read(master,32768)
                except OSError: break
                if not data: break
                raw+=data
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=3)
            os.close(master)
        text=raw.decode("utf-8","replace")
        assert "WEB PANEL ONLINE 3.0" in text and "МАСТЕР УСТАНОВКИ" in text
        assert "Домен:" in text and "Пароль (не отображается):" in text
        if mode=="ok":
            assert proc.returncode==0,(proc.returncode,text[-1500:])
            assert "✓ Установка завершена!" in text and "100%" in text
            assert text.count("DemoSecret123")==1,"Password must not echo during input"
            before,after=text.rsplit("\x1b[H",1)
            assert "100%" in before and "✓ Установка завершена!" in before
            assert "Ссылка на панель: https://panel.example.test/panel-xyz/login" in after
            assert "Логин : Admin" in after and "Пароль : DemoSecret123" in after
            assert all(s not in after for s in ("Домен:","Email:","Установка нод","100%","◷"))
            assert "\x1b[J" in after,"Must erase the old wizard area without wiping terminal"
        else:
            assert proc.returncode!=0,(mode,text[-1500:])
            assert "✓ Установка завершена!" not in text and "100%" not in text
            assert "Ссылка на панель:" not in text and "DemoSecret123" not in text
        print("PASS: final TTY case",mode,"exit",proc.returncode)

for mode in ("ok","fail","empty"):
    check(mode)
