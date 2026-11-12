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
assert 'ШАГ %s/4' in boot, "A single heading is required per form step"
assert 'wpp_progress 80 "Установка Nodes Lab v26"' in final
assert 'wpp_progress 100 "Установка завершена"' in final
assert final.rindex('[[ -s "$WPO_UI_RESULT_FILE" ]]') < final.rindex('wpp_progress 100 "Установка завершена"'), "100 percent must follow the actual final access-card check"
assert 'wpo_node_stage "$version"' in nodes
assert 'wpo_node_stage 12' in nodes

shell = ("set -Eeuo pipefail\n"
    "blue=''\ncyan=''\nice=''\ngray=''\nreset=''\n"
    + draw_function + "\n"
    + "draw 36 'Настройка Telegram Proxy' 114\n"
    + "printf '\\033[3B\\r\\n'\n"
    + "draw 80 'Установка Nodes Lab v26' 263\n"
    + "printf '\\033[3B\\r\\n'\n"
    + "draw 100 'Установка завершена' 378\n"
    + "printf '\\033[3B\\r\\n'\n"
)
run = subprocess.run(["bash", "-c", shell], capture_output=True, text=True, timeout=10)
assert run.returncode == 0, run.stderr
plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", run.stdout)
assert "36%" in plain and "80%" in plain and "100%" in plain, plain
assert "Этап: Настройка Telegram Proxy" in plain
assert "Этап: Установка Nodes Lab v26" in plain
assert "Прошло: 00:01:54" in plain
assert "Прошло: 00:04:23" in plain
assert "Прошло: 00:06:18" in plain
lines = plain.splitlines()
bars = [line for line in lines if "█" in line or "░" in line]
assert len(bars) == 3, bars
assert bars[0].count("█") < bars[1].count("█") < bars[2].count("█"), bars
assert bars[-1].count("░") == 0, "100% must have a completely filled bar"
print("PASS: thick stage-driven bar, actual elapsed clock, no fake percentage or step tiles")
