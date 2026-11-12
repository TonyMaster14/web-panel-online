"""Smoke test the final access card, without touching any VPS or live secrets."""
from pathlib import Path
import os
import subprocess
import tempfile

source = Path("install-panel.sh").read_text(encoding="utf-8")
marker = "# Финальная карточка: только ссылка, логин и пароль."
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
        text = destination.read_text(encoding="utf-8")
        assert "Ссылка: https://panel.example.test/panel-sample-id/login" in text
        assert "Логин:  TestAdmin" in text
        assert "Сохраните данные, чтобы не потерять." in text
        assert "Node API" not in text and "Token" not in text
        assert all(english not in text for english in ("Panel URL:", "Administrator login:", "Administrator password:"))
        if updating == "0":
            assert "Пароль: DemoSecret123" in text
        else:
            assert "Пароль: сохранён (без изменений)" in text
            assert "DemoSecret123" not in text
        assert text.index("Ссылка:") < text.index("Логин:") < text.index("Пароль:") < text.index("Сохраните данные")
print("PASS: Russian access card, correct order, save reminder, no token, no credential log leak")
