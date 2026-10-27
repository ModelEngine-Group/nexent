# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise real page-object selection with five names across distinct services."""
import json
from pathlib import Path
import subprocess


def test_owned_service_scope_and_persisted_identity_prevent_foreign_tool_selection():
    repo = Path(__file__).resolve().parents[4]
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs'); const path = require('node:path'); const vm = require('node:vm');
const root = ROOT;
const ts = require(path.join(root,'test-e2e/infra/automation/d1/frontend/node_modules/typescript'));
const code = ts.transpileModule(fs.readFileSync(path.join(root,'test-e2e/infra/automation/d4/pages/agent.page.ts'),'utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const calls = []; let selected = false;
const row = {count:1, async getAttribute(){return selected?'true':'false';}, async click(){selected=true;calls.push('own-tool');}};
const noop = {async click(){},first(){return this;},async fill(){}};
const region = {getByRole(role,options){assert.equal(role,'option');assert.equal(options.name,'shared_tool');return row;}};
const dialog = {getByRole(role,options){
 if(role==='region'){assert.equal(options.name,'owned-service');assert.equal(options.exact,true);return region;}
 if(role==='option')return {...row,count:5};
 return noop;
}};
const expect = value => ({
 async toBeVisible(){},async toBeHidden(){},
 async toHaveCount(n){assert.equal(value.count,n);},
 async toHaveAttribute(key,v){assert.equal(await value.getAttribute(key),v);},
 toHaveLength(n){assert.equal(value.length,n);},toBe(v){assert.equal(value,v);}
});
const exported={};vm.runInNewContext(code,{exports:exported,process,URL,require(name){
 if(name==='playwright/test')return {expect};
 if(name==='../runner/runtime-config')return {appPath:x=>x};
 return require(name);
}});
const page={
 getByTestId(){return noop;},getByRole(){return dialog;},getByText(){return noop;},
 url(){return 'http://fixture/agents/42';},waitForResponse(){return Promise.resolve({ok:()=>true});},
 request:{async get(){return {ok:()=>true,json:async()=>[
  {id:7,source:'mcp',usage:'owned-service',origin_name:'raw-shared-tool',name:'shared_tool'},
  ...[1,2,3,4].map(id=>({id,source:'mcp',usage:'foreign-'+id,name:'shared_tool'}))
 ]};},async post(){return {ok:()=>true,json:async()=>({tools:[{tool_id:7}]})};}}
};
const agent=new exported.AgentPage(page);agent.openSection=async()=>{};
agent.bindToolFromService('owned-service','shared_tool').then(()=>{
 assert.equal(calls.length,1);assert.equal(calls[0],'own-tool');
}).catch(error=>{console.error(error);process.exitCode=1;});
""".replace("ROOT", json.dumps(str(repo)))
    outcome = subprocess.run(["node", "-"], input=script, text=True, capture_output=True, timeout=20)
    assert outcome.returncode == 0, outcome.stderr
