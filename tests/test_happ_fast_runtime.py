import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import wpp_subscriptions as subs
import wpo_xray_live as live

class HappPreparationTests(unittest.TestCase):
    def create(self, limit=2):
        data,result=subs.mutate({'users':[],'subscriptions':[]},{'operation':'create','name':'test','max_devices':limit,'protocols':['vless','reality']})
        return data,data['subscriptions'][0]
    def test_first_import_claims_keys_without_runtime_change(self):
        data,sub=self.create()
        self.assertEqual(len(data['users']),4)
        self.assertTrue(all(d.get('preallocated') for d in sub['devices']))
        before=copy.deepcopy(data['users'])
        after,result=subs.issue(data,{'token':sub['token'],'hwid':'test-device-123','device_name':'Mac'})
        strip=lambda users:[{k:v for k,v in u.items() if k!='name'} for u in users]
        self.assertEqual(strip(before),strip(after['users']))
        self.assertEqual(len(result['users']),2)
        again,result2=subs.issue(after,{'token':sub['token'],'hwid':'test-device-123'})
        self.assertEqual([u['secret'] for u in result['users']],[u['secret'] for u in result2['users']])
    def test_limit_counts_claimed_slots_and_revocation_blocks_old_hwid(self):
        data,sub=self.create(1)
        data,result=subs.issue(data,{'token':sub['token'],'hwid':'first-device'})
        with self.assertRaises(subs.SubscriptionError):subs.issue(data,{'token':sub['token'],'hwid':'second-device'})
        device=data['subscriptions'][0]['devices'][0]
        data,_=subs.mutate(data,{'operation':'revoke','id':sub['id'],'device_id':device['id']})
        with self.assertRaises(subs.SubscriptionError):subs.issue(data,{'token':sub['token'],'hwid':'first-device'})
        _,result=subs.issue(data,{'token':sub['token'],'hwid':'second-device'})
        self.assertEqual(len(result['users']),2)
    def test_unlimited_shared_subscription_is_prepared(self):
        data,sub=self.create(0)
        old=[u['secret'] for u in data['users']]
        after,result=subs.issue(data,{'token':sub['token']})
        self.assertEqual([u['secret'] for u in result['users']],old)
        self.assertFalse(result['limited'])
    def test_deleting_account_removes_all_reserved_and_claimed_keys(self):
        data,sub=self.create(2)
        data,_=subs.mutate(data,{'operation':'delete','id':sub['id']})
        self.assertEqual(data['users'],[]);self.assertEqual(data['subscriptions'],[])

class LiveCredentialsTests(unittest.TestCase):
    def config(self):
        return {'api':{'services':['HandlerService']},'inbounds':[{'tag':'test','protocol':'vless','settings':{'clients':[{'id':'one','email':'one@test'}]}}]}
    def test_addition_only_delta_and_revocation_requires_activation(self):
        old=self.config();new=copy.deepcopy(old)
        new['inbounds'][0]['settings']['clients'].append({'id':'two','email':'two@test'})
        delta=live.additions(old,new)
        self.assertEqual(delta[0]['settings']['clients'],[{'id':'two','email':'two@test'}])
        self.assertIsNone(live.additions(new,old))
        self.assertEqual(len(old['inbounds'][0]['settings']['clients']),1)
        changed=copy.deepcopy(new);changed['inbounds'][0]['port']=1234
        self.assertIsNone(live.additions(old,changed))
    def test_api_zero_success_is_not_accepted_or_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'xray.json';old=self.config();p.write_text(json.dumps(old))
            candidate=copy.deepcopy(old);candidate['inbounds'][0]['settings']['clients'].append({'id':'two','email':'two@test'})
            def cmd(args,**kwargs):return subprocess.CompletedProcess(args,0,stdout='Added 0 user(s) in total.',stderr='')
            with patch.object(live.subprocess,'run',side_effect=cmd):
                self.assertFalse(live.try_apply(candidate,p,'xray','unit','127.0.0.1:8080'))
            self.assertEqual(json.loads(p.read_text()),old)

if __name__=='__main__':unittest.main()
