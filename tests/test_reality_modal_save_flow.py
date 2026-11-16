"""Exercise REALITY modal JS saving and cancelling without a live VPS.

Run extracted browser's actual execute(save) function in Node with controlled
fake API. The UI must not repeat all prechecks after a successful Check click;
on mid-save cancellation it must roll back the already-touched node.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class RealityModalSaveTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"),"node not installed")
    def test_real_browser_handler_reuses_check_then_saves_and_rolls_back_cancel(self):
        source=(ROOT/"src/wpo_reality_ui.py").read_text()
        match=re.search(r"async function execute\(save\)\{.*?\n\}\nf\.addEventListener\('submit'",source,re.S)
        self.assertIsNotNone(match)
        body=match.group().rsplit("\nf.addEventListener",1)[0]
        js=r'''
const assert=require('node:assert/strict');
const handlerSource=SOURCE_JS;
function setup(cancelDuringSave){
 const entries=[{id:'local',name:'Основная нода'},{id:'node1',name:'Нидерланды'}];
 const store={local:{preset:'nvidia',sni:'www.nvidia.com',fingerprint:'firefox'},
              node1:{preset:'nvidia',sni:'www.nvidia.com',fingerprint:'firefox'}};
 const calls={preflight:0,save:0,read:0,rollback:0,events:[]};
 const ctx={
   running:false,cancelRequested:false,closeAfterStop:false,restoreFailed:false,
   activeAbort:null,phase:'idle',verified:null,
   presets:{nvidia:['NVIDIA','www.nvidia.com'],apple:['Apple','www.apple.com']},
   area:{hidden:true},out:{textContent:''},d:{close(){calls.events.push('closed')}},
   f:{elements:{preset:{value:'apple'},sni:{value:'www.apple.com'},
                 fingerprint:{value:'firefox'}}},
   currentNodes(){return entries},
   nodeRow(name){return {row:{},details:{},name}},
   update(row,status,message){calls.events.push(row.name+':'+status+':'+message)},
   resetChecks(){ctx.area.hidden=true;ctx.out.textContent=''},
   togglePicker(){},
   requestKey(nodes,request){return JSON.stringify([nodes.map(n=>n.id),
                    request.preset,request.sni,request.fingerprint])},
   ensureActive(){if(ctx.cancelRequested)throw Error('Операция отменена пользователем')},
   setRunning(value){ctx.running=value;if(!value){ctx.phase='idle';ctx.activeAbort=null}},
   isFullCheck(j){return j.checks?.some(x=>x.name==='REALITY Vision'&&x.status==='ok')&&
                          j.checks?.some(x=>x.name==='HTTPS через туннель'&&x.status==='ok')},
   async send(id,data){
      if(data.read_only==='1'){calls.read++;return {ok:true,profile:{...store[id]}}},
      check=undefined;
   }
 };
 ctx.send=async (id,data)=>{
  if(data.read_only==='1'){calls.read++;return {ok:true,profile:{...store[id]}}}
  if(data.check_only==='1'){
    calls.preflight++;
    return {ok:true,checks:[{name:'REALITY Vision',status:'ok'},
                             {name:'HTTPS через туннель',status:'ok'}],latency_ms:62};
  }
  if(data.check_only==='0'){
    calls.save++;
    if(data.sni==='www.nvidia.com')calls.rollback++;
    store[id]={preset:data.preset,sni:data.sni,fingerprint:data.fingerprint};
    if(cancelDuringSave&&data.sni==='www.apple.com'&&id==='local')
       ctx.cancelRequested=true,ctx.closeAfterStop=true;
    return {ok:true,checks:[{name:'REALITY Vision',status:'ok'},
                             {name:'HTTPS через туннель',status:'ok'}]};
  }
  throw Error('Unexpected API request');
 };
 const execute=new Function('ctx',"with(ctx){"+handlerSource+"; return execute;}")(ctx);
 return {execute,ctx,store,calls};
}
(async ()=>{
 const a=setup(false);
 await a.execute(false);
 assert.equal(a.calls.preflight,2,'Check must test both nodes');
 assert.equal(a.calls.save,0,'Check cannot save');
 assert.ok(a.ctx.out.textContent.includes('можно нажать'));
 await a.execute(true);
 assert.equal(a.calls.preflight,2,'Save must reuse successful preflight');
 assert.equal(a.calls.save,2,'Save must write both changed nodes');
 assert.equal(a.store.local.sni,'www.apple.com');
 assert.equal(a.store.node1.sni,'www.apple.com');
 assert.ok(a.ctx.out.textContent.includes('Сохранено на всех'));
 assert.equal(a.ctx.running,false);
 const b=setup(true);
 await b.execute(false);
 await b.execute(true);
 assert.equal(b.calls.preflight,2);
 assert.equal(b.calls.save,2,'One attempted change and one rollback');
 assert.equal(b.calls.rollback,1);
 assert.equal(b.store.local.sni,'www.nvidia.com');
 assert.equal(b.store.node1.sni,'www.nvidia.com');
 assert.equal(b.calls.events.at(-1),'closed','Close after safe rollback');
 assert.equal(b.ctx.running,false);
 console.log('REALITY UI: Save and cancellation state machine passed');
})().catch(e=>{console.error(e);process.exit(1)});
''';
        # The mock uses the same network API surface but deliberately no DOM.
        # Remove an unused placeholder from the stub before evaluating.
        js=js.replace("""   async send(id,data){
      if(data.read_only==='1'){calls.read++;return {ok:true,profile:{...store[id]}}},
      check=undefined;
   }
""","")
        js=js.replace("SOURCE_JS",json.dumps(body,ensure_ascii=False))
        result=subprocess.run(["node","-e",js],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr[:2500])
        self.assertIn("state machine passed",result.stdout)

if __name__=="__main__":
    unittest.main()
