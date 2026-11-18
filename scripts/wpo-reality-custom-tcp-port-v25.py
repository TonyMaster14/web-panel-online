#!/usr/bin/env python3
"""WPO V25 — configurable external REALITY TCP port, panel + existing node agent.

The original 443/TCP listener is kept for panel HTTPS and old subscriptions.
This patch never changes live listener ports or profiles until Save in WPO.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

PANEL=Path('/opt/tproxy-panel')
AGENT=Path('/opt/wpp-node-agent')
BACKUPS=Path('/var/backups/web-panel-online')
MARK='# WPO_REALITY_CUSTOM_TCP_PORT_V25'


def once(source, old, new, label):
    count=source.count(old)
    if count != 1:
        raise RuntimeError(f'V25: {label}: найдено {count} совпадений, нужно 1. Ничего не меняем.')
    return source.replace(old,new,1)


def patch_reality(source):
    if MARK in source:
        return source,False
    source=once(source,
        "    return {'preset': result['preset'], 'sni': host, 'fingerprint': result['fingerprint'], 'port': 443}",
        """    raw_port=result.get('port',443)
    if isinstance(raw_port,bool) or not str(raw_port).strip().isdigit():
        raise ValueError('Порт REALITY должен быть целым числом.')
    port=int(str(raw_port).strip())
    if port!=443 and not 1025<=port<=65535:
        raise ValueError('Укажите порт 443 или свободный TCP-порт от 1025 до 65535.')
    if port in (8090,19443,19444,19445,19446,19447,19448,19449):
        raise ValueError('Этот порт зарезервирован внутренними службами WPO.')
    return {'preset': result['preset'], 'sni': host, 'fingerprint': result['fingerprint'], 'port': port}""",
        'валидация порта')
    source=once(source,
        "    return 'vless://' + quote(secret, safe='-') + '@' + address + ':443?' + query + '#' + quote(name + ' · REALITY', safe='')",
        "    return 'vless://' + quote(secret, safe='-') + '@' + address + ':' + str(int(p.get('port',443))) + '?' + query + '#' + quote(name + ' · REALITY', safe='')",
        'порт в подписках')
    source=once(source,
        "def haproxy_config(sni):\n    routes = reality_routes({'sni': sni})",
        """def haproxy_config(sni, port=None):
    if port is None:
        port=int(read_profile().get('port',443))
    port=normalize({'preset':'custom','sni':sni,'port':port})['port']
    # Keep 443 for panel HTTPS and previously distributed links.
    extra_bind=('    bind 0.0.0.0:'+str(port)+'\\n    bind [::]:'+str(port)+' v6only\\n') if port!=443 else ''
    routes = reality_routes({'sni': sni})""",
        'HAProxy frontend definition')
    source=once(source,
        "    bind [::]:443 v6only\n    tcp-request inspect-delay 5s",
        "    bind [::]:443 v6only\n''' + extra_bind + '''    tcp-request inspect-delay 5s",
        'HAProxy binds')
    source=once(source,
        'def configure(request, apply_xray):\n    value=normalize(request)\n    check_target(value[\'sni\'])',
        """def _wpo_v25_check_port(wanted,old):
    port=int(wanted)
    if port==443 or port==int(old): return
    # Prevent reusing a port already bound by another TCP service.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        try: sock.bind(('0.0.0.0',port))
        except OSError as exc:
            raise ValueError('TCP-порт '+str(port)+' уже занят на этой ноде.') from exc


def _wpo_v25_firewall(port):
    # UFW is never enabled by this function. Only add a narrow TCP allow rule.
    import shutil
    if port==443 or not shutil.which('ufw'): return
    try: config=Path('/etc/ufw/ufw.conf').read_text()
    except OSError: return
    if not re.search(r'(?m)^\\s*ENABLED\\s*=\\s*yes\\s*$',config,re.I): return
    present=subprocess.run(['ufw','show','added'],capture_output=True,text=True,timeout=15,check=False)
    if present.returncode==0 and re.search(r'(?m)^ufw\\s+allow\\s+(?:in\\s+)?'+str(port)+r'/tcp(?:\\s|$)',present.stdout,re.I): return
    subprocess.run(['ufw','allow',str(port)+'/tcp','comment','WEB PANEL ONLINE REALITY'],check=True,capture_output=True,timeout=25)


def configure(request, apply_xray):
    old=read_profile()
    incoming=dict(request)
    incoming.setdefault('port',old.get('port',443))
    value=normalize(incoming)
    _wpo_v25_check_port(value['port'],old.get('port',443))
    check_target(value['sni'])""",
        'REALITY configure precheck')
    source=once(source,
        "    result=wpo_reality_probe.probe(value['sni'],value['fingerprint'],__import__(__name__))\n    if request.get('check_only'): return result\n    old=read_profile()",
        """    result=wpo_reality_probe.probe(value['sni'],value['fingerprint'],__import__(__name__))
    result=dict(result,port=value['port'])
    if request.get('check_only'): return result""",
        'порт в результате проверки')
    source=once(source,
        "    atomic(config_path,haproxy_config(new['sni']))",
        "    _wpo_v25_firewall(new['port'])\n    atomic(config_path,haproxy_config(new['sni'],new['port']))",
        'HAProxy port save')
    source=source.rstrip()+'\n\n'+MARK+'\n'
    compile(source,'wpo_reality.py','exec')
    return source,True


def patch_panel(source):
    if MARK in source: return source,False
    old='"fingerprint":form.get("fingerprint","firefox"),"check_only":form.get("check_only")=="1"'
    new='"fingerprint":form.get("fingerprint","firefox"),"port":form.get("port","443"),"check_only":form.get("check_only")=="1"'
    source=once(source,old,new,'controller reality-action port')
    source=source.rstrip()+'\n\n'+MARK+'\n'
    compile(source,'panel.py','exec')
    return source,True


def patch_ui(source):
    if MARK in source: return source,False
    source=once(source,
        '''spellcheck="false"></label>
<label>Сайт для REALITY''',
        '''spellcheck="false"></label>
<label>Порт<input id="wpoRealityPort" name="port" type="text" inputmode="numeric" maxlength="5" pattern="[0-9]{1,5}" value="'''+"'''+e(profile.get('port',443))+'''"+'''" required autocomplete="off"></label>
<label>Сайт для REALITY''',
        'REALITY port input')
    source=once(source,
        'request.preset,request.sni,request.fingerprint])',
        'request.preset,request.sni,request.fingerprint,request.port])',
        'port check cache key')
    source=once(source,
        'f.elements.sni.value=p.sni;f.elements.fingerprint.value=p.fingerprint;',
        "f.elements.sni.value=p.sni;f.elements.fingerprint.value=p.fingerprint;f.elements.port.value=String(p.port||443);wpoV25Caption();",
        'port readback')
    source=once(source,
        'const request={preset:f.elements.preset.value,sni:f.elements.sni.value.trim(),fingerprint:f.elements.fingerprint.value};',
        'const request={preset:f.elements.preset.value,sni:f.elements.sni.value.trim(),fingerprint:f.elements.fingerprint.value,port:f.elements.port.value.trim()};',
        'port in Check and Save')
    source=once(source,
        "if(!isFullCheck(result))throw Error('Нода не подтвердила настоящий REALITY-туннель (HTTP 204)');",
        "if(!isFullCheck(result)||Number(result.port)!==Number(request.port))throw Error('Проверка порта REALITY не пройдена. Обновите Node Agent на этой ноде.');",
        'port verification on node')
    source=once(source,
        'if(before.sni===request.sni&&before.fingerprint===request.fingerprint){',
        'if(before.sni===request.sni&&before.fingerprint===request.fingerprint&&Number(before.port||443)===Number(request.port)){',
        'port change detection')
    source=once(source,
        "if(!isFullCheck(saved))throw Error('Нода не подтвердила REALITY при сохранении');",
        "if(!isFullCheck(saved)||Number(saved.port)!==Number(request.port))throw Error('Нода не подтвердила REALITY и новый порт при сохранении');",
        'port after save')
    source=once(source,
        'if(actual.profile?.sni!==request.sni||actual.profile?.fingerprint!==request.fingerprint)',
        'if(actual.profile?.sni!==request.sni||actual.profile?.fingerprint!==request.fingerprint||Number(actual.profile?.port||443)!==Number(request.port))',
        'port persistence confirmation')
    source=once(source,
        "await send(n.id,{preset:oldPreset,sni:old.sni,fingerprint:old.fingerprint,check_only:'0'});",
        "await send(n.id,{preset:oldPreset,sni:old.sni,fingerprint:old.fingerprint,port:String(old.port||443),check_only:'0'});",
        'port rollback')
    source=once(source,
        'if(actual.profile?.sni!==old.sni||actual.profile?.fingerprint!==old.fingerprint)',
        'if(actual.profile?.sni!==old.sni||actual.profile?.fingerprint!==old.fingerprint||Number(actual.profile?.port||443)!==Number(old.port||443))',
        'port rollback check')
    source=once(source,
        "f.querySelector('[data-reality-check]').addEventListener('click',()=>execute(false));\ndisplayPreset();",
        """f.querySelector('[data-reality-check]').addEventListener('click',()=>execute(false));
function wpoV25Caption(){
 const subtitle=d.querySelector('.dialog-head small');
 if(!subtitle)return;
 const port=f.elements.port.value.trim()||'443';
 subtitle.textContent=(document.documentElement.dataset.wpoLanguage==='en'?'TCP shared external port ':'TCP общий внешний порт ')+port;
}
f.elements.port.addEventListener('input',()=>{verified=null;wpoV25Caption()});
document.addEventListener('click',e=>{if(e.target?.closest?.('button[data-wpo-lang]'))requestAnimationFrame(wpoV25Caption)});
wpoV25Caption();
displayPreset();""",
        'live port subtitle')
    source=source.rstrip()+'\n\n'+MARK+'\n'
    compile(source,'wpo_reality_ui.py','exec')
    return source,True


def active(unit):
    return subprocess.run(['systemctl','is-active','--quiet',unit],check=False).returncode==0


def main():
    parser=argparse.ArgumentParser(description='WPO V25 configurable REALITY TCP port')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true')
    mode.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0: raise RuntimeError('Нужен sudo')
    is_panel=(PANEL/'panel.py').is_file() and active('tproxy-panel.service')
    is_agent=(AGENT/'wpo_node_vpn.py').is_file() and active('wpo-node-vpn.service')
    if is_panel:
        root=PANEL;unit='tproxy-panel.service'
        targets={root/'wpo_reality.py':patch_reality,root/'wpo_reality_ui.py':patch_ui,root/'panel.py':patch_panel}
    elif is_agent:
        root=AGENT;unit='wpo-node-vpn.service'
        targets={root/'wpo_reality.py':patch_reality}
    else: raise RuntimeError('WPO Panel / WPO Node Agent не найдены в работающем состоянии')
    originals={};changed={}
    for path,transform in targets.items():
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Не найден файл WPO: '+str(path))
        originals[path]=path.read_text(encoding='utf-8')
        result,modified=transform(originals[path])
        if modified: changed[path]=result
    if not changed:
        print('✓ V25 уже установлен; изменений нет')
        return
    if args.check:
        print('✓ Проверка пройдена; можно применять. Файлы не изменены.')
        return
    BACKUPS.mkdir(parents=True,exist_ok=True)
    backup=BACKUPS/('reality-port-v25-'+('panel-' if is_panel else 'node-')+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    if backup.exists(): raise RuntimeError('Резервная копия с таким именем существует')
    backup.mkdir(mode=0o700)
    for path in changed:
        shutil.copy2(path,backup/path.name)
        os.chmod(backup/path.name,0o600)
    print('✓ Резервная копия:',backup)
    staged={};replaced=[]
    try:
        for path,src in changed.items():
            with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,prefix='.wpo-v25-',suffix='.py',delete=False) as f:
                f.write(src);staged[path]=Path(f.name)
            st=path.stat();os.chown(staged[path],st.st_uid,st.st_gid);os.chmod(staged[path],stat.S_IMODE(st.st_mode))
        for path,temporary in staged.items():
            os.replace(temporary,path)
            replaced.append(path)
        subprocess.run(['systemctl','restart',unit],check=True,timeout=45)
        for _ in range(15):
            if active(unit):
                print('✓ V25 установлен на', 'панели' if is_panel else 'ноде')
                print('✓ Профили и активный порт не менялись до нажатия Save.')
                return
            time.sleep(1)
        raise RuntimeError('Служба WPO не запустилась после установки')
    except Exception:
        for path in replaced: shutil.copy2(backup/path.name,path)
        if replaced: subprocess.run(['systemctl','restart',unit],check=False)
        print('! Выполнен откат к прежней версии')
        raise
    finally:
        for temp in staged.values(): temp.unlink(missing_ok=True)


if __name__=='__main__':
    try: main()
    except (OSError,RuntimeError,subprocess.CalledProcessError) as e:
        print('ОШИБКА:',e,file=sys.stderr)
        sys.exit(1)
