"""Simulate the actual Bash progress ticker without touching VPS services."""
from pathlib import Path
import subprocess
import re
import unittest

SCRIPT = Path("install.sh").read_text(encoding="utf-8")
START = SCRIPT.index("wpo_progress_tick(){")
END = SCRIPT.index("\nprintf '\\033[?25l'", START)
TICKER = SCRIPT[START:END]


def simulate(seconds, duration=240):
    # Replace the terminal drawing routine with a captured numeric output.
    code = (
        "set -Eeuo pipefail\n"
        + TICKER
        + "\n"
        + 'draw() { printf "%s\\n" "$1"; }\n'
        + f'WPO_PROGRESS_TARGET_SECONDS={duration}\n'
        + "shown=1; started=0\n"
        + "for offset in " + " ".join(map(str, seconds)) + "; do\n"
        + "    SECONDS=$offset\n"
        + "    wpo_progress_tick\n"
        + "done\n"
    )
    result = subprocess.run(["bash", "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return [int(s) for s in result.stdout.splitlines()]


class SmoothProgressTests(unittest.TestCase):
    def test_4_minute_ticker_never_skips_a_percent(self):
        values = simulate(range(241))
        self.assertEqual(values[0], 1)
        self.assertEqual(values[-1], 99)
        self.assertEqual(sorted(set(values)), list(range(1, 100)))
        self.assertTrue(all(0 <= b-a <= 1 for a,b in zip(values,values[1:])))
    def test_does_not_show_100_during_slow_install(self):
        values = simulate(range(0, 650, 2))
        self.assertLessEqual(max(values), 99)
        self.assertTrue(all(a <= b for a,b in zip(values,values[1:])))
    def test_without_real_success_no_final_card(self):
        self.assertLess(SCRIPT.index('if [[ ! -s "$RESULT" ]]'), SCRIPT.index('while (( shown < 100 )); do'))
        self.assertLess(SCRIPT.index('while (( shown < 100 )); do'), SCRIPT.index('sleep 2'))
        self.assertIn('cat -- "$RESULT"', SCRIPT)
        self.assertNotIn('stage="Этап:', SCRIPT)
        self.assertNotIn('shown=$confirmed', SCRIPT)
    def test_fast_install_animates_remainder_in_sequence(self):
        values = simulate(range(0, 110, 2))
        self.assertLess(values[-1], 99)
        self.assertTrue(all(b-a <= 1 for a,b in zip(values,values[1:])))
        self.assertIn('shown=$((shown+1))\n        draw "$shown"', SCRIPT)

if __name__ == "__main__":
    unittest.main()
