"""Exercise the REAL adaptive Bash ticker with virtual 4/5/6.5-min installs.

Milestones come from the same progress file that install-final.sh writes.
No privileged filesystem, GitHub download or real VPS installation is used.
"""
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path("install.sh").read_text(encoding="utf-8")
START = SCRIPT.index("wpo_progress_tick(){")
END = SCRIPT.index("\nprintf '\\033[?25l'", START)
TICKER = SCRIPT[START:END]

# Values are the real reporting checkpoints (not invented fractional phases).
STAGES = [
    (0.00, 1), (0.02, 5), (0.05, 10), (0.09, 14),
    (0.21, 20), (0.25, 26), (0.32, 33), (0.37, 36),
    (0.72, 48), (0.78, 55), (0.82, 58), (0.88, 73),
    (0.91, 77), (0.94, 80), (0.97, 99)
]


def simulate(duration, schedule=None):
    if schedule is None:
        schedule = [(round(duration * fraction), val) for fraction, val in STAGES]
    updates = {}
    for elapsed, milestone in schedule:
        updates[int(elapsed)] = int(milestone)
    branches = "\n".join(
        f'{time}) printf "%d\\tverified\\n" {value} > "$PROGRESS" ;;'
        for time, value in sorted(updates.items())
    )
    code = (
        "set -Eeuo pipefail\n"
        + TICKER + "\n"
        + 'draw() { printf "%s\\n" "$1"; }\n'
        + "WPO_PROGRESS_REFERENCE_SECONDS=240\n"
        + "WPO_CONFIRMED=1; WPO_LAST_INCREMENT_SECOND=-1\n"
        + "shown=1; started=0\n"
        + 'PROGRESS="$(mktemp)"\ntrap \'rm -f "$PROGRESS"\' EXIT\n'
        + 'printf "1\\tbegin\\n" > "$PROGRESS"\n'
        + f'for offset in $(seq 0 {duration}); do\n'
        + '    SECONDS="$offset"\n'
        + '    case "$offset" in\n' + branches + '\n    esac\n'
        + '    wpo_progress_tick\n'
        + 'done\n'
    )
    result = subprocess.run(["bash", "-c", code],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return [int(x) for x in result.stdout.splitlines()]


class AdaptiveProgressTests(unittest.TestCase):
    def test_variable_real_world_durations_are_monotone_without_jumps(self):
        for duration in (240, 307, 390):
            with self.subTest(seconds=duration):
                result = simulate(duration)
                self.assertEqual(len(result), duration + 1)
                self.assertEqual(result[0], 1)
                self.assertTrue(all(0 <= b-a <= 1 for a,b in zip(result,result[1:])))
                self.assertLessEqual(max(result), 98)  # 100 requires a real success
                self.assertGreater(result[-1], 85)
                self.assertLess(result[-1], 99)
                # This isn't locked to four minutes, even on a slower VPS.
                self.assertLess(result[90], result[170])
                self.assertLess(result[170], result[min(duration,250)])
    def test_backend_jumps_are_smoothed_not_rendered_as_large_leaps(self):
        result = simulate(260, [(0,1),(30,14),(100,36),(105,80),(250,99)])
        self.assertTrue(all(0 <= b-a <= 1 for a,b in zip(result,result[1:])))
        self.assertGreater(result[140], result[105])
    def test_very_slow_stage_keeps_estimate_alive(self):
        result = simulate(650, [(0,1),(12,5),(25,14),(600,36),(645,99)])
        self.assertTrue(all(0 <= b-a <= 1 for a,b in zip(result,result[1:])))
        self.assertLess(result[180], result[320])
        self.assertLess(result[320], result[450])
        self.assertLessEqual(max(result), 98)
    def test_percent_100_only_follows_verified_success_and_private_card(self):
        self.assertLess(SCRIPT.index('if [[ ! -s "$RESULT" ]]'),SCRIPT.index('while (( shown < 100 )); do'))
        self.assertLess(SCRIPT.index('while (( shown < 100 )); do'),SCRIPT.index('sleep 2'))
        self.assertIn('cat -- "$RESULT"',SCRIPT)
        self.assertNotIn('stage="Этап:',SCRIPT)
        self.assertIn('WPO_CONFIRMED="$real_percent"',SCRIPT)
        self.assertIn('read -r real_percent real_stage < "$PROGRESS"',SCRIPT)

if __name__ == "__main__":
    unittest.main()
