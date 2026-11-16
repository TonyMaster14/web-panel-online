"""Apply additive Xray credentials through HandlerService without dropping sessions.

Revocation and transport changes deliberately use the caller's full activation,
which also disconnects already authenticated sessions. Failed partial API work
falls back to the validated full configuration, never reports false success.
"""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def additions(previous, candidate):
    old=copy.deepcopy(previous);new=copy.deepcopy(candidate)
    old_in={i.get('tag'):i for i in old.get('inbounds',[])}
    new_in={i.get('tag'):i for i in new.get('inbounds',[])}
    if set(old_in)!=set(new_in): return None
    changes=[]
    for tag,after in new_in.items():
        before=old_in[tag]
        if before==after: continue
        if before.get('protocol') not in ('vless','hysteria'): return None
        old_clients=before.get('settings',{}).pop('clients',[])
        new_clients=after.get('settings',{}).pop('clients',[])
        if before!=after: return None
        old_by={c.get('email'):c for c in old_clients}
        new_by={c.get('email'):c for c in new_clients}
        if (None in old_by or None in new_by or '' in new_by
                or len(old_by)!=len(old_clients) or len(new_by)!=len(new_clients)
                or any(new_by.get(k)!=v for k,v in old_by.items())): return None
        added=[c for c in new_clients if c['email'] not in old_by]
        if added:
            delta=copy.deepcopy(after);delta.setdefault('settings',{})['clients']=added;changes.append(delta)
    # Exclude client arrays from both copies to compare all other settings.
    for item in old.get('inbounds',[]):item.get('settings',{}).pop('clients',None)
    for item in new.get('inbounds',[]):item.get('settings',{}).pop('clients',None)
    return changes if old==new else None


def try_apply(candidate, config_path, binary, unit, api):
    path=Path(config_path)
    try:
        previous=json.loads(path.read_text())
        if subprocess.run(['systemctl','is-active','--quiet',unit],capture_output=True,timeout=3).returncode:return False
        if previous==candidate:return True
        delta=additions(previous,candidate)
        if delta is None or 'HandlerService' not in previous.get('api',{}).get('services',[]):return False
        fd,temp=tempfile.mkstemp(prefix='.wpo-live-',suffix='.json',dir=path.parent)
        try:
            with os.fdopen(fd,'w') as f:json.dump({'inbounds':delta},f)
            if delta:
                result=subprocess.run([binary,'api','adu','--server='+api,'--timeout=3',temp],
                                      capture_output=True,text=True,timeout=8)
                count=sum(len(i['settings']['clients']) for i in delta)
                match=re.search(r'Added\s+(\d+)\s+user\(s\) in total',result.stdout)
                if result.returncode or not match or int(match[1])!=count:return False
            stat=path.stat()
            with open(temp,'w') as f:
                json.dump(candidate,f);f.flush();os.fsync(f.fileno())
            os.chmod(temp,stat.st_mode & 0o777)
            os.chown(temp,stat.st_uid,stat.st_gid)
            os.replace(temp,path)
            return True
        finally:
            if os.path.exists(temp):os.unlink(temp)
    except (OSError,ValueError,subprocess.SubprocessError):
        return False
