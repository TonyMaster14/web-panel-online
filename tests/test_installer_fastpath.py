"""Installer fast-path invariants: do not delay access details for optional updates.

The checks deliberately avoid VPS/network changes; real installation validation
remains in the existing system and PTY integration tests.
"""
from pathlib import Path

launcher = Path("install.sh").read_text(encoding="utf-8")
final = Path("install-final.sh").read_text(encoding="utf-8")

# Only completed backend checks may advance the progress, and no artificial
# one-second-per-point loops can hold an already finished installation.
assert 'if (( shown < confirmed )); then shown=$confirmed; fi' in launcher
assert 'shown=100\n    draw "$shown" "$label" "$((SECONDS-started))"' in launcher
assert 'while (( shown < 100 ))' not in launcher
assert 'while (( shown < 7 ))' not in launcher

# The final access card must remain private and must still have its approved
# exactly-two-second visible success hold before rendering.
assert 'if [[ ! -s "$RESULT" ]]' in launcher
assert launcher.index('if [[ ! -s "$RESULT" ]]') < launcher.index('shown=100')
assert launcher.index('shown=100') < launcher.index('sleep 2') < launcher.index('cat -- "$RESULT"')

# Release discovery/download is optional maintenance: it can be queued after
# nodes and local Xray checks, but cannot block the initial installation.
node_setup = final.index('bash "$BASE/node-install.sh"')
xray_check = final.index('xray run -test -config')
version_written = final.index("printf '%s\\n' '3.0.0'")
unlock = final.index('flock -u 9')
queued = final.index('systemctl start --no-block web-panel-proxy-component-auto-update.service')
completed = final.index('wpp_progress 100 "Установка завершена"', queued)
assert node_setup < xray_check < version_written < unlock < queued < completed
assert final.count('flock -u 9') == 1
assert 'systemctl start web-panel-proxy-component-auto-update.service' not in final
assert 'web-panel-proxy-component-auto-update.timer' in Path("install-panel.sh").read_text(encoding="utf-8")
print("PASS: verified milestones are immediate, mandatory setup is awaited, release updates are nonblocking")
