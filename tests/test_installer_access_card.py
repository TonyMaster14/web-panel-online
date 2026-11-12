"""Smoke test the final access card, without touching any VPS or live secrets."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

source = Path("install-panel.sh").read_text(encoding="utf-8")
marker = "# Финальная карточка: подпись и значение рядом, разные цвета, без выравнивающих отступов."
assert marker in source
card = source[source.index(marker):]
assert card.lstrip().startswith(marker)
assert 'Node API token:' not in card and 'NODE_API_TOKEN=' not in card

with tempfile.TemporaryDirectory(prefix="wpo-access-card-") as folder:
    for updating in ("0", "1"):
        destination = Path(folder) / ("fresh.txt" if updating == "0" else "upgrade.txt")
        env = os.environ.copy()
        env.update({
            "DOMAIN": "panel.example.test",
            "PANEL_PATH": "/panel-sample-id",
            "ADMIN": "TestAdmin",
            "PASS": "DemoSecret123",
            "UPDATING": updating,
            "WPO_UI_RESULT_FILE": str(destination)
        })
        completed = subprocess.run(
            ["bash", "-c", "set -Eeuo pipefail\n" + card],
            env=env, capture_output=True, text=True, timeout=8
        )
        assert completed.returncode == 0, completed.stderr
        assert "DemoSecret123" not in (completed.stdout + completed.stderr), "Secret printed to logs"
        raw = destination.read_text(encoding="utf-8")
        # Test the actual ANSI-colored terminal result and its visible layout.
        assert "\x1b[38;5;153m" in raw, "Blue labels missing"
        assert "\x1b[38;5;51m" in raw, "Contrasting cyan values missing"
        text = re.sub(r"\x1b\[[0-9;]*m", "", raw)
        rows = [line for line in text.splitlines() if line.startswith("  Ссылка на панель:") or line.startswith("  Логин :") or line.startswith("  Пароль :")]
        assert len(rows) == 3, f"Expected exactly three entries: {rows}"
        assert rows[0] == "  Ссылка на панель: https://panel.example.test/panel-sample-id/login", rows[0]
        assert rows[1] == "  Логин : TestAdmin", rows[1]
        assert rows[2] == ("  Пароль : DemoSecret123" if updating == "0" else "  Пароль : сохранён (без изменений)"), rows[2]
        assert "Сохраните данные,что бы не потерять!" in text
        assert "Node API" not in text and "Token" not in text
        assert all(english not in text for english in ("Panel URL:", "Administrator login:", "Administrator password:"))
        if updating == "0":
            assert "Пароль : DemoSecret123" in text
        else:
            assert "сохранён (без изменений)" in rows[2]
            assert "DemoSecret123" not in text
        assert text.index("Ссылка на панель:") < text.index("Логин :") < text.index("Пароль :") < text.index("Сохраните данные")
        assert "\n\n  Логин :" in text and "\n\n  Пароль :" in text, "Expected blank separators"
        assert "\n\n  Сохраните данные,что бы не потерять!" in text

print("PASS: Russian labels followed by exactly one space and values, ANSI colors, no leaked secrets")
