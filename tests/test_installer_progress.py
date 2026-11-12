"""Test WPO's thick terminal progress and stage/clock accuracy without any VPS."""
from pathlib import Path
import re
import subprocess

boot = Path("install.sh").read_text(encoding="utf-8")
final = Path("install-final.sh").read_text(encoding="utf-8")
nodes = Path("node-install.sh").read_text(encoding="utf-8")

start = boot.index("draw(){")
end = boot.index("\n# One clock for the entire installation", start)
draw_function = boot[start:end]
assert '█' in draw_function and '░' in draw_function, "Progress bar must be thick"
assert 'elapsed/3600' in draw_function and 'elapsed%60' in draw_function
assert 'shown="$target"' in boot, "Must use actual installer milestone"
assert 'shown=$((shown+1))' not in boot, "No fabricated percentage animation"
assert boot.index('started=$SECONDS') < boot.rindex('git clone --depth 1'), "Elapsed time must include wizard package download"
assert boot.count('╭──────╮') == 0, "Old separate number tiles must be removed"
assert 'ШАГ %s/4' not in boot and 'step(){' not in boot, "No extra step headings"
assert all(p in boot for p in ('Домен:${reset}', 'Email:${reset}', 'Логин:${reset}', 'Пароль (не отображается):${reset}')), "Prompts must be only label + colon"
assert 'wpp_progress 80 "Установка нод"' in final
assert 'wpp_progress 100 "Установка завершена"' in final
assert final.rindex('[[ -s "$WPO_UI_RESULT_FILE" ]]') < final.rindex('wpp_progress 100 "Установка завершена"'), "100 percent must follow the actual final access-card check"
assert 'wpo_node_stage "$version"' in nodes
assert "Ноды: этап" not in nodes, "Internal node stages must not appear in wizard"
assert "Установка нод" in nodes, "All 26 embedded modules must use the single Nodes installation label"
assert 'wpo_node_stage 12' in nodes

shell = ("set -Eeuo pipefail\n"
    "blue=''\ncyan=''\nice=''\ngray=''\nreset=''\nsuccess=''\n"
    + draw_function + "\n"
    + "draw 36 'Настройка Telegram Proxy' 114\n"
    + "printf '\\033[2B\\r\\n'\n"
    + "draw 80 'Установка нод' 263\n"
    + "printf '\\033[2B\\r\\n'\n"
    + "draw 100 'Проверки завершены' 378\n"
    + "printf '\\033[2B\\r\\n'\n"
)
run = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, timeout=10)
assert run.returncode == 0, run.stderr
plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", run.stdout)
assert "36%" in plain and "80%" in plain and "100%" in plain, plain
assert "Этап: Настройка Telegram Proxy" in plain
assert "Этап: Установка нод" in plain
assert "◷ 00:01:54" in plain
assert "◷ 00:04:23" in plain
assert "◷ 00:06:18" in plain
lines = plain.splitlines()
bars = [line for line in lines if "█" in line or "░" in line]
assert len(bars) == 3, bars
assert bars[0].count("█") < bars[1].count("█") < bars[2].count("█"), bars
assert bars[-1].count("░") == 0, "100% must have a completely filled bar"
assert "✓ Установка..." in plain and "✓ Установка завершена!" in plain, "Both progress states required"
assert "Этап: Проверки завершены" not in plain, "At 100 percent stage text must disappear"
assert "✓ Установка..." not in plain.split("100%", 1)[-1], "Active status must vanish at 100%"
assert plain.count("✓ Установка завершена!") == 1, "Completion must appear once above bar"
assert plain.rfind("✓ Установка завершена!") < plain.rfind("100%"), "Completion must stay above 100% bar"
assert plain.find("✓ Установка...") < plain.find("36%") < plain.find("Этап: Настройка Telegram Proxy"), "Active status must be above bar and current stage below"
assert "◈" in draw_function, "Live stage must use the new cyan diamond icon"
assert 'if (( pct == 100 )); then\n        printf \'\\r\\033[2K\'' in draw_function, "At 100 percent clear the whole live stage line"
assert "\\033[2A" in draw_function, "Three-line UI redraw must go up two rows"
assert "\\033[3A" not in draw_function, "Old four-line redraw must be removed"
print("PASS: blue-icon dynamic operation, cleared at 100, actual elapsed clock, no fake percent")
