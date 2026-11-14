"""Installer fast-path invariants: do not delay access details for optional updates.

The checks deliberately avoid VPS/network changes; real installation validation
remains in the existing system and PTY integration tests.
"""
from pathlib import Path

launcher = Path("install.sh").read_text(encoding="utf-8")
final = Path("install-final.sh").read_text(encoding="utf-8")

# Backend milestones stay available for diagnostics, but the visual
# display does not jump to them or fake an early 100%.
assert 'WPO_PROGRESS_TARGET_SECONDS=240' in launcher
assert 'wpo_progress_tick(){' in launcher
assert 'if (( shown < expected )); then shown=$((shown+1)); fi' in launcher
assert 'while (( shown < 100 )); do' in launcher
assert 'shown=$confirmed' not in launcher
assert 'stage="Этап:' not in launcher
assert 'sleep 0.10' in launcher

# Credentials only appear after a successful backend and an existing access
# card. Keep the approved two-second final hold.
assert 'if [[ ! -s "$RESULT" ]]' in launcher
assert launcher.index('if [[ ! -s "$RESULT" ]]') < launcher.index('while (( shown < 100 )); do')
assert launcher.index('while (( shown < 100 )); do') < launcher.index('sleep 2') < launcher.index('cat -- "$RESULT"')

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
print("PASS: smooth gated progress, mandatory setup awaited, optional release updates nonblocking")
