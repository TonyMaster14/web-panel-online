"""Fast controller actions: touch only the engines involved in a change."""
import copy
import fcntl
import json
import os
import time

XRAY=frozenset(('vless','reality','hysteria'))


def changed_records(before,after,key='id'):
    old={x.get(key):x for x in before};new={x.get(key):x for x in after}
    return [x for uid in old.keys()|new.keys() if old.get(uid)!=new.get(uid)
            for x in (old.get(uid),new.get(uid)) if x is not None]


def install(ns):
    original_refresh=ns['refresh_connections']
    original_collect=ns['collect_traffic']
    original_delete=ns['delete']
    original_subscription=ns['subscription_command']

    def snapshot(data=None):
        """Sample Xray counters before restart, without polling other engines."""
        data=data or ns['load']()
        os.makedirs(os.path.dirname(ns['TRAFFIC_LOCK']),mode=0o700,exist_ok=True)
        with open(ns['TRAFFIC_LOCK'],'a+',encoding='ascii') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            current=ns['_xray_traffic']()
            state=ns['_load_traffic']();now=int(time.time())
            for user in data.get('users',[]):
                uid=user['id']
                if user.get('protocol') not in XRAY or uid not in current:continue
                entry=state.setdefault(uid,{'up':0,'down':0,'raw_up':0,'raw_down':0,'last_change':0})
                for direction in ('up','down'):
                    value=max(0,int(current[uid].get(direction,0)))
                    previous=max(0,int(entry.get('raw_'+direction,0)))
                    delta=value-previous if value>=previous else value
                    entry[direction]=max(0,int(entry.get(direction,0)))+delta
                    entry['raw_'+direction]=value
                    if delta:entry['last_change']=now
                entry['updated_at']=now
            ns['_save_traffic'](state)
            return state

    def delete(uid):
        user=next((u for u in ns['load']()['users'] if u.get('id')==uid),None)
        if not user or user.get('protocol') not in XRAY:return original_delete(uid)
        ns['collect_traffic']=snapshot
        try:return original_delete(uid)
        finally:ns['collect_traffic']=original_collect

    def subscription():
        # Subscription profiles are Xray-only. Native accounts use their own
        # handlers and retain full accounting/activation checks.
        ns['collect_traffic']=snapshot
        try:return original_subscription()
        finally:ns['collect_traffic']=original_collect

    def refresh(request=None):
        old=(request or {}).get('previous_registry')
        if not isinstance(old,dict) or not isinstance(old.get('connections'),list):
            return original_refresh()
        before=ns['load']();after=copy.deepcopy(before)
        registry=ns['wpp_connections'].ensure(ns['CONNECTIONS'],after['users'])
        changes=changed_records(old['connections'],registry['connections'])
        if any(c.get('protocol') not in XRAY for c in changes):return original_refresh()
        ns['wpp_connections'].sync_users(registry,after['users'])
        ns['wpp_connections'].sync_subscriptions(registry,after.get('subscriptions',[]))
        users_changed=changed_records(before['users'],after['users'])
        if any(u.get('protocol') not in XRAY for u in users_changed):return original_refresh()
        # Hysteria ports may require firewall changes; VLESS always uses 443.
        firewall=any(x.get('protocol')=='hysteria' for x in changes+users_changed)
        try:
            if users_changed:snapshot(before)
            if firewall:ns['sync_firewall'](after)
            ns['sync_xray'](after)
            if before!=after:ns['save'](after)
        except Exception:
            if firewall:ns['sync_firewall'](before)
            # The caller restores the previous connection registry, then calls
            # the normal refresh to restore its runtime. Never report success.
            raise
        print(json.dumps({'ok':True}))

    ns['delete']=delete
    ns['subscription_command']=subscription
    ns['refresh_connections']=refresh
