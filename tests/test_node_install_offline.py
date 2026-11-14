"""Apply the complete node installer twice to a disposable controller.
System services and the final HTTP probe are mocked; no VPS claim is implied.
All patch payloads and local helper resolution run, with networking denied.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='wpo-node-offline-') as folder:
    temp=Path(folder); app=temp/'app'; data=temp/'data'; package=temp/'package'; bins=temp/'bin'
    for directory in (app,data,package,bins): directory.mkdir()
    source=(root/'install-panel.sh').read_text()
    panel=source.split('cat > "$APP_FILE" <<\'PY\'\n',1)[1].split('\nPY\n',1)[0]
    (app/'panel.py').write_text(panel.replace('/opt/tproxy-panel',str(app)).replace('/var/lib/tproxy-panel',str(data)))
    for path in root.glob('wpp_*.py'): shutil.copyfile(path,app/path.name)
    service=temp/'panel.service'; service.write_text('Environment=WEBPROXY_PANEL_PATH=/panel-offline\n')
    manager=temp/'manager.py'
    manager.write_text(source.split('cat > "$MANAGER" <<\'PY\'\n',1)[1].split('\nPY\n',1)[0])
    for name in ('install-final.sh','wpo-node-agent-install-v2.sh','wpo-node-geo-v13.py','wpo-node-autotemplate-v20.py',
                 'wpo-node-controller-vpn.sh','wpo_user_v28.py','wpo_v28_apply.py'):
        shutil.copyfile(root/name,package/name)
    bridge=package/'wpo-node-controller-vpn.sh'
    bridge.write_text(bridge.read_text().replace('/opt/tproxy-panel',str(app))
                      .replace('/var/lib/tproxy-panel',str(data))
                      .replace('[[ $EUID -eq 0 ]]','true'))
    src=(root/'node-install.sh').read_text().replace('/opt/tproxy-panel',str(app)).replace('/var/lib/tproxy-panel',str(data)).replace('/etc/systemd/system/tproxy-panel.service',str(service)).replace('/usr/local/sbin/web-proxy-panelctl',str(manager)).replace('[[ $EUID -eq 0 ]]','true')
    (package/'node-install.sh').write_text(src)
    mocks={'systemctl':'exit 0', 'chown':'exit 0', 'sleep':'exit 0',
        'curl': 'case "$*" in *http://127.0.0.1:8090/panel-offline/__health*) exit 0;; *) echo "Unexpected network: $*" >&2; exit 92;; esac',
        'install': 'args=(); while (($#)); do case "$1" in -o|-g) shift 2;; *) args+=("$1"); shift;; esac; done; exec /usr/bin/install "${args[@]}"'}
    for name,body in mocks.items():
        p=bins/name; p.write_text('#!/bin/bash\n'+body+'\n'); p.chmod(0o755)
    env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'],WPO_NODES_LOCAL_SOURCE='1',WPO_NODES_BATCH_RESTART='1')
    for attempt in range(2):
        result=subprocess.run(['bash',str(package/'node-install.sh')],env=env,capture_output=True,text=True,timeout=90)
        assert result.returncode==0, result.stdout[-5000:]+'\n'+result.stderr[-5000:]
    for name in ('panel.py','wpp_ui.py','wpp_nodes.py','wpp_subscriptions.py','wpo_node_geo.py','wpo_node_autotemplate.py'):
        compile((app/name).read_text(),name,'exec')
    assert '# wpo-v28-new-user' in (app/'wpp_ui.py').read_text()
    assert '# wpo-v28-new-user' in (app/'panel.py').read_text()
    assert '# wpo-v28-new-user' in (app/'wpp_subscriptions.py').read_text()
    assert '# wpo-v28-new-user' in manager.read_text()
    assert (app/'wpo_user_v28.py').is_file()
    for name in ('wpp_ui.py','panel.py','wpp_subscriptions.py','wpo_user_v28.py'):
        compile((app/name).read_text(),name,'exec')
    assert '# wpo-node-country-v13' in (app/'panel.py').read_text()
    assert '__WPO_CONTROLLER_ENROLL_URL__' in (app/'wpp-node-agent-install.sh').read_text()
print('PASS: complete bundled node installation and repeat run, without legacy files or external downloads')
