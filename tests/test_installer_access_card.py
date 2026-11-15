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
            assert '╭' in text and '╰' in text
            assert 'Логин: TestAdmin' in text
            assert text.index('Ссылка на панель:')<text.index('Логин:')<text.index('Пароль:')<text.index('Сохраните')
            assert text.index('Ссылка на панель:') < text.index('╰', text.index('WPO 3.0 — '))
            rows=text.splitlines()
            linkrow=next(i for i,row in enumerate(rows) if 'Ссылка на панель:' in row)
            loginrow=next(i for i,row in enumerate(rows) if 'Логин: TestAdmin' in row)
            passrow=next(i for i,row in enumerate(rows) if 'Пароль:' in row)
            warningrow=next(i for i,row in enumerate(rows) if 'Сохраните данные' in row)
            title_row=next(i for i,row in enumerate(rows) if 'WPO 3.0 — ' in row)
            assert 'Ссылка на панель: https://' in rows[linkrow]
            # When the terminal can fit label + URL, neither may wrap.
            if width >= len('Ссылка на панель: ')+len(url)+6:
                assert url in rows[linkrow] and rows[linkrow].count('│') == 2
                border=next(row for row in rows if row.startswith('╭') and row.endswith('╮'))
                assert len(rows[linkrow]) == len(border)
                # Exactly one empty framed row separates every value.
                indices=[title_row, linkrow, loginrow, passrow, warningrow]
                assert all(y-x == 2 for x,y in zip(indices,indices[1:])), indices
                assert all(rows[x+1].startswith('│') and not rows[x+1].strip('│ ')
                           for x in indices[:-1])
            # On narrow windows the link is not cut off, and each wrapped
            # piece remains inside the same two vertical frame borders.
            pieces=[rows[linkrow].split('Ссылка на панель: ',1)[1].split('│',1)[0].strip()]
            for row in rows[linkrow+1:loginrow]:
                if row.count('│') == 2 and row.split('│',2)[1].strip():
                    pieces.append(row.split('│',2)[1].strip())
            assert ''.join(pieces)==url, 'Full URL must be preserved in order'
            lines=[line for line in text.splitlines() if line.startswith('│')]
            assert all(line.count('│') == 2 for line in lines)
            assert ('TestSecret123' in text)==(updating=='0')
boot=Path('install.sh').read_text()
assert 'sleep 2' in boot and 'sleep 4' not in boot
assert boot.index('if [[ ! -s "$RESULT" ]]')<boot.index('sleep 2')<boot.index('cat -- "$RESULT"')
assert 'WEB_PANEL_PROXY_REF:-main' in boot
print('PASS: full-width framed login URL, narrow terminal wrapping, private secrets, upgrades, two-second hold')
