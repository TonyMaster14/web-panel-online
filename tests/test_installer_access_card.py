"""Check real final-card output at multiple widths and on upgrades."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
source=Path('install-panel.sh').read_text()
card=source[source.index('# Final access card:'):]
url='https://panel.example.test/panel-'+'a'*32+'/login'
with tempfile.TemporaryDirectory() as folder:
    for width in (40,80,120):
        for updating in ('0','1'):
            dest=Path(folder)/'result'
            env=dict(os.environ,DOMAIN='panel.example.test',PANEL_PATH='/panel-'+'a'*32,ADMIN='TestAdmin',PASS='TestSecret123',UPDATING=updating,WPO_UI_RESULT_FILE=str(dest),WPO_CARD_COLUMNS=str(width))
            run=subprocess.run(['bash','-c','set -Eeuo pipefail\n'+card],env=env,capture_output=True,text=True,timeout=8)
            assert run.returncode==0,run.stderr
            assert 'TestSecret123' not in run.stdout+run.stderr
            text=re.sub(r'\x1b\[[0-9;]*m','',dest.read_text())
            assert url in text, 'Installer must never split URL with a hard newline'
            assert '╭' in text and '╰' in text
            assert 'Логин: TestAdmin' in text
            assert text.index(url)<text.index('Логин:')<text.index('Пароль:')<text.index('Сохраните')
            assert ('TestSecret123' in text)==(updating=='0')
boot=Path('install.sh').read_text()
assert 'sleep 4' in boot
assert boot.index('if [[ ! -s "$RESULT" ]]')<boot.index('sleep 4')<boot.index('cat -- "$RESULT"')
assert 'WEB_PANEL_PROXY_REF:-main' in boot
print('PASS: final card, intact URL, private secrets, upgrade preservation, verified completion hold')
