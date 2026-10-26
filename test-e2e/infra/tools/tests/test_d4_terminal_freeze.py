# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the real TypeScript contract against controlled late browser events."""
import json
from pathlib import Path
import subprocess

import pytest

def test_late_events_cannot_overwrite_terminal_and_prior_5xx_is_not_accepted():
    repo = Path(__file__).resolve().parents[4]
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = ROOT;
const ts = require(path.join(root, 'test-e2e/infra/automation/d1/frontend/node_modules/typescript'));
const text = fs.readFileSync(path.join(root, 'test-e2e/infra/automation/d4/runner/journey.ts'), 'utf8');
const code = ts.transpileModule(text, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const writes = new Map();
const fakeFs = {
  mkdirSync(){}, appendFileSync(){}, writeFileSync(){}, existsSync(){return true;},
  readFileSync(){return JSON.stringify({preconditions:[],steps:[],assertions:[],
    cleanup:{status:'PASS'},console_errors:[],unexpected_5xx:[]});}
};
const exported = {};
vm.runInNewContext(code, {exports:exported, process:{env:{RESULT_DIR:'/fixture',NEXENT_REPO:root,D4_QUEUE:'/queue'},pid:123},
  setInterval,clearInterval,require(name){
    if (name === 'playwright/test') return {};
    if (name === 'node:fs') return fakeFs;
    if (name === './atomic-file') return {atomicJson(file,value){writes.set(file,JSON.parse(JSON.stringify(value)));}};
    if (name === 'node:child_process') return {spawnSync(){return {status:0};}};
    return require(name);
  }});
const item = {precondition_items:[],step_items:[],assertion_items:[]};
const contract = new exported.ContractExecution('fixture',item);
contract.complete();
// Reproduce a 500 arriving during asynchronous cleanup, after the first complete().
contract.addUnexpected5xx('500 http://fixture/conversation/generate_title');
assert.throws(() => contract.complete(), /unexpected 5xx/);
contract.finish('FAIL','unexpected 5xx');
const finalEvidence = JSON.stringify(writes.get(contract.evidencePath));
contract.addConsoleError('late console error');
contract.addUnexpected5xx('500 http://fixture/late');
assert.equal(writes.get(contract.statusPath).status,'FAIL');
assert.equal(JSON.stringify(writes.get(contract.evidencePath)),finalEvidence);
// Terminal success must also remain terminal after late observational callbacks.
const success = new exported.ContractExecution('success',item);
success.complete(); success.finish('PASS'); success.addConsoleError('late');
assert.equal(writes.get(success.statusPath).status,'PASS');
assert.ok(text.indexOf('contract.complete();',text.indexOf('await page.context().tracing.stop({ path: traceZip });')) < text.indexOf('contract.finish("PASS")'));
""".replace("ROOT", json.dumps(str(repo)))
    outcome = subprocess.run(["node", "-"], input=script, text=True, capture_output=True, timeout=20)
    assert outcome.returncode == 0, outcome.stderr


@pytest.mark.parametrize("late_at", ["cleanup", "tracing", "none"])
def test_journey_preserves_late_failure_trace_and_executes_cleanup_once(late_at):
    repo = Path(__file__).resolve().parents[4]
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const root = ROOT, lateAt = LATE_AT;
const ts = require(path.join(root,'test-e2e/infra/automation/d1/frontend/node_modules/typescript'));
const source = fs.readFileSync(path.join(root,'test-e2e/infra/automation/d4/runner/journey.ts'),'utf8');
const code = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const item = {id:'fixture',contract_hash:'fixture-hash',precondition_items:[],step_items:[],
  assertion_items:[{id:'assert-1',text:'business assertion'}]};
const files = new Set(), writes = new Map(), records = [], listeners = {};
let registered, cleanups = 0, stopped = false;
const fakeFs = {
  mkdirSync(){},appendFileSync(){},
  writeFileSync(file){files.add(file);},existsSync(file){return files.has(file);},
  unlinkSync(file){assert.ok(files.delete(file));},
  readFileSync(file){return JSON.stringify(file==='/queue'?{items:[item]}:{preconditions:[],steps:[],
    assertions:[{id:'assert-1',status:'PENDING'}],cleanup:{status:'PENDING'},console_errors:[],unexpected_5xx:[]});}
};
const lateResponse = () => listeners.response({
  request:()=>({method:()=> 'POST',resourceType:()=> 'fetch'}),
  status:()=>500,url:()=> 'http://fixture/conversation/generate_title'
});
const tracing = {async start(){},async stop(options){
  if(stopped)throw new Error('tracing already stopped');
  stopped = true;
  if(lateAt==='tracing')lateResponse();
  if(options?.path)files.add(options.path);
}};
const page = {context:()=>({tracing}),on(event,fn){listeners[event]=fn;},
  url:()=> 'http://fixture/chat',async screenshot(options){files.add(options.path);}};
const exported = {};
vm.runInNewContext(code,{exports:exported,Error,process:{pid:123,env:{RESULT_DIR:'/fixture',
  NEXENT_REPO:root,D4_QUEUE:'/queue',D4_RESULTS:'/results'}},setInterval,clearInterval,require(name){
  if(name==='playwright/test')return {test:(id,body)=>{registered=body;},expect:{}};
  if(name==='node:fs')return fakeFs;
  if(name==='./atomic-file')return {atomicJson(file,value){files.add(file);writes.set(file,JSON.parse(JSON.stringify(value)));}};
  if(name==='node:child_process')return {spawnSync(exe,args){records.push(args);return {status:0};}};
  return require(name);
}});
exported.journey('fixture',async({contract})=>{
  contract.deferCleanup(async()=>{cleanups++;if(lateAt==='cleanup')lateResponse();});
  await contract.assertion('assert-1',async()=> 'business assertion passed');
});
(async()=>{
  let error;
  try {await registered({page});} catch(value){error=value;}
  const finalRecord = records.find(args=>args.includes('record'));
  assert.ok(finalRecord);
  const result = finalRecord[finalRecord.indexOf('--result')+1];
  const trace = path.join('/fixture','d4','fixture','trace.zip');
  assert.equal(cleanups,1,'A post-cleanup failure must not delete owned resources twice');
  if(lateAt==='none'){
    assert.equal(error,undefined);assert.equal(result,'PASS');assert.equal(files.has(trace),false);
  }else{
    assert.match(error.message,/FAIL/);assert.equal(result,'FAIL');
    assert.equal(files.has(trace),true,'The final 5xx check must not discard the failure trace');
    assert.ok(finalRecord.some(arg=>arg.endsWith('trace.zip')));
    const evidence = writes.get(path.join('/fixture','d4','fixture','assertions.json'));
    assert.equal(evidence.status,'FAIL');assert.equal(evidence.cleanup.status,'PASS');
    assert.equal(evidence.unexpected_5xx.length,1);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
""".replace("ROOT", json.dumps(str(repo))).replace("LATE_AT", json.dumps(late_at))
    outcome = subprocess.run(["node", "-"], input=script, text=True, capture_output=True, timeout=20)
    assert outcome.returncode == 0, outcome.stderr
