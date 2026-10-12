"""Regression checks for prerequisite handling; not formal product results."""
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / 'automation'))
import run_cases
import suite
import prepare_special_assets as special
from shared.asset_registry import AssetDependencyError
from shared import preparation_evidence


def test_removed_perf04_is_not_an_executable_case_or_special_dispatch():
    import importlib.util
    assert not (REPO / 'test-e2e/cases/PERF-04/case.yaml').exists()
    assert not (REPO / 'test-e2e/cases/PERF-04/execution.yaml').exists()
    assert not (REPO / 'test-e2e/cases/PERF-04/test.py').exists()
    path = REPO / 'test-e2e/infra/automation/d5/scenarios/scenario_performance_special.py'
    spec = importlib.util.spec_from_file_location('removed_perf04_dispatch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert 'PERF-04' not in module.CASES
    assert not hasattr(special, 'prepare_vector_scale')
    feature = yaml.safe_load((REPO / 'test-e2e/features/V5-PERF-04/feature.yaml').read_text(encoding='utf-8'))
    assert feature['feature']['required_test_stages'] == []


def machine(tmp_path, monkeypatch):
    for key in run_cases.MEMORY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'daily.env').write_text('# local settings\n', encoding='utf-8')
    (config / 'secrets.env').write_text('# credentials\n', encoding='utf-8')
    (config / 'environment.yaml').write_text('base_url: http://fixture\n', encoding='utf-8')
    return config


def test_registered_memory_file_bridges_to_node_without_exporting_control_keys(tmp_path, monkeypatch):
    config = machine(tmp_path, monkeypatch)
    (config / 'memory-mock.env').write_text(
        'export NEXENT_EXTERNAL_MEMORY_PLUGIN="controlled"\n'
        'NEXENT_EXTERNAL_MEMORY_ENDPOINT=http://fixture/memory\n'
        "NEXENT_EXTERNAL_MEMORY_API_KEY='fixture-secret'\n"
        'UNREGISTERED_CONTROL_KEY=do-not-export\n', encoding='utf-8')
    env = run_cases.machine_environment(tmp_path, REPO)
    assert env['NEXENT_EXTERNAL_MEMORY_PLUGIN'] == 'controlled'
    assert env['NEXENT_EXTERNAL_MEMORY_ENDPOINT'] == 'http://fixture/memory'
    assert env['NEXENT_EXTERNAL_MEMORY_API_KEY'] == 'fixture-secret'
    assert 'UNREGISTERED_CONTROL_KEY' not in env


@pytest.mark.parametrize('source', ['process', 'daily.env', 'secrets.env'])
def test_conflicting_memory_credentials_fail_without_exposing_values(tmp_path, monkeypatch, source):
    config = machine(tmp_path, monkeypatch)
    if source == 'process':
        monkeypatch.setenv('NEXENT_EXTERNAL_MEMORY_API_KEY', 'secret-one')
    else:
        (config / source).write_text('NEXENT_EXTERNAL_MEMORY_API_KEY=secret-one\n', encoding='utf-8')
    (config / 'memory-mock.env').write_text('NEXENT_EXTERNAL_MEMORY_API_KEY=secret-two\n', encoding='utf-8')
    with pytest.raises(ValueError) as caught:
        run_cases.machine_environment(tmp_path, REPO)
    assert 'NEXENT_EXTERNAL_MEMORY_API_KEY' in str(caught.value)
    assert 'secret-one' not in str(caught.value)
    assert 'secret-two' not in str(caught.value)


def test_optional_memory_config_keeps_existing_setup_compatible(tmp_path, monkeypatch):
    machine(tmp_path, monkeypatch)
    assert 'NEXENT_EXTERNAL_MEMORY_API_KEY' not in run_cases.machine_environment(tmp_path, REPO)


def test_preparation_error_reports_dependency_and_log_before_acceptance(tmp_path, monkeypatch):
    directory = tmp_path / 'run'
    record = {'case_id': 'PERF-03', 'stage': 'D5', 'execution': {
        'preparation': {'families': ['performance_upload']}}}
    monkeypatch.setattr(suite, 'machine_environment', lambda *args: {})
    monkeypatch.setattr(suite, 'controlled_services', lambda *args: nullcontext())
    run = AsyncMock()
    monkeypatch.setattr(suite, 'run_one', run)
    def logged(*args, **kwargs):
        path = directory / 'runtime/preparation-failure.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(preparation_evidence.failure_receipt(
            AssetDependencyError('models', 'embedding', detail='dependency connectivity_false'))), encoding='utf-8')
        return 1
    monkeypatch.setattr(suite, 'logged', logged)
    assert suite.worker(REPO, tmp_path, record, directory, {'command_timeout_seconds': 30}) == 1
    receipt = json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))
    assert receipt['result'] == 'BLOCKED_BY_DEPENDENCY'
    assert 'models.embedding' in receipt['reason']
    assert 'connectivity_false' in receipt['reason']
    assert 'logs/prepare-performance_upload.log' in receipt['test_evidence']
    run.assert_not_called()


def test_timeout_cannot_be_rescued_by_dependency_receipt(tmp_path, monkeypatch):
    directory = tmp_path / 'run'
    record = {'case_id': 'PERF-03', 'stage': 'D5', 'execution': {'preparation': {'families': ['performance_upload']}}}
    monkeypatch.setattr(suite, 'machine_environment', lambda *args: {})
    monkeypatch.setattr(suite, 'controlled_services', lambda *args: nullcontext())
    monkeypatch.setattr(suite, 'logged', lambda *a, **kw: 124)
    suite.worker(REPO, tmp_path, record, directory, {'command_timeout_seconds': 30})
    assert json.loads((directory / 'receipt.json').read_text())['result'] == 'TIMEOUT'


def test_receipt_redacts_dependency_details(tmp_path, monkeypatch):
    machine(tmp_path, monkeypatch)
    monkeypatch.setenv('NEXENT_TEST_HOME', str(tmp_path))
    monkeypatch.setenv('NEXENT_EXTERNAL_MEMORY_API_KEY', 'sensitive-key')
    receipt = preparation_evidence.failure_receipt(AssetDependencyError('models', 'embedding', detail='sensitive-key'))
    assert 'sensitive-key' not in json.dumps(receipt)
    assert '[REDACTED]' in receipt['reason']
    assert preparation_evidence.failure_receipt(RuntimeError('secret arbitrary body'))['reason'] == 'RuntimeError'


@pytest.mark.asyncio
async def test_empty_upload_target_never_becomes_large_vector_fixture(monkeypatch):
    monkeypatch.setattr(special, 'resolve_asset', lambda section, key, **kw: 'empty-upload' if key == 'upload_kb_index' else None)
    register = AsyncMock()
    monkeypatch.setattr(special, 'register_asset', register)
    await special.prepare_knowledge(SimpleNamespace())
    register.assert_not_called()
    assert not hasattr(special, 'prepare_vector_scale')


@pytest.mark.asyncio
async def test_special_preparation_does_not_return_success_after_failure(monkeypatch):
    monkeypatch.setattr(special, 'register_asset_failure', lambda *a, **kw: None)
    monkeypatch.setattr(special, 'record_failure', lambda *a: None)
    async def failed():
        raise AssetDependencyError('models', 'embedding')
    assert await special.guarded('PERF-03', 'performance', 'upload_kb_index', failed()) is False


@pytest.mark.asyncio
async def test_performance_model_preserves_configuration_and_registers_cleanup_before_listing(monkeypatch):
    from contextlib import asynccontextmanager
    import httpx
    requests, registered = [], []
    configured = {'model_name': 'configured-vector', 'model_type': 'embedding',
                  'base_url': 'http://fixture/v1', 'expected_chunk_size': 2560}
    monkeypatch.setattr(special, 'resolve_asset', lambda *a, **kw: None)
    monkeypatch.setattr(special, 'model_request', lambda kind, display_name: {**configured, 'display_name': display_name})
    monkeypatch.setattr(special, 'register_asset', lambda *a, **kw: registered.append((a, kw)))
    created = AsyncMock()
    monkeypatch.setattr(special, 'create_configured_model_dependency', created)
    @asynccontextmanager
    async def client(*args, **kwargs):
        class API:
            async def get(self, path):
                assert registered, 'Cleanup must be recorded before model-list resolution can fail'
                requests.append(path)
                name = created.await_args.args[1]['display_name']
                return httpx.Response(200, json={'data': [{'model_id': 9, 'display_name': name}]},
                                      request=httpx.Request('GET', 'http://fixture/model/list'))
        yield API()
    monkeypatch.setattr(special, 'client', client)
    assert await special.prepare_performance_embedding(SimpleNamespace(id='local-admin', access_token='session')) == 9
    payload = created.await_args.args[1]
    assert payload['base_url'] == configured['base_url']
    assert payload['expected_chunk_size'] == 2560
    assert payload['skip_default_backfill'] is True
    assert registered[0][1]['cleanup']['identity'] == 'local-admin'
    assert registered[0][1]['cleanup']['params']['display_name'] == payload['display_name']
    assert requests == ['/model/list']


def test_generation_watcher_detects_terminal_failure_not_reasoning(tmp_path):
    # Compile the actual TypeScript helper and exercise its async polling,
    # rather than duplicating the implementation in a Python fake.
    helper = REPO / 'test-e2e/infra/automation/d4/runner/generation-progress.ts'
    ts = REPO / 'frontend/node_modules/typescript/lib/typescript.js'
    script = r'''
const assert = require('node:assert/strict');
const ts = require(TS);
const mod = {exports: {}};
const source = ts.transpileModule(require('node:fs').readFileSync(HELPER, 'utf8'), {
 compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
}).outputText;
new Function('require', 'module', 'exports', source)(require, mod, mod.exports);
const {generationFailure, waitForGenerationProgress, watchGeneration} = mod.exports;
const event = (type, content) => 'data: '+JSON.stringify({type,content})+'\n\n';
assert.match(generationFailure(500,''), /HTTP 500/);
assert.match(generationFailure(200,event('final_answer','*模型返回了空内容。*')), /empty model/);
assert.equal(generationFailure(200,event('reasoning','模型返回了空内容。')),null);
assert.equal(generationFailure(200,event('final_answer','正常回答')),null);
assert.match(generationFailure(200,event('error','private secret')), /SSE error/);
assert.equal(generationFailure(200,'data: [DONE]\n\n'),null);
(async () => {
 let waits = 0;
 await assert.rejects(waitForGenerationProgress({waitForTimeout: async()=>{waits++;}},
  {check:()=>{throw new Error('terminal failure');}}, async()=>false,300000), /terminal failure/);
 assert.equal(waits,0);
 await waitForGenerationProgress({}, {check:()=>{}},async()=>true,100);
 await assert.rejects(waitForGenerationProgress({}, {check:()=>{}},async()=>false,0), {name:'TimeoutError'});
 let listener; let detached = false;
 const page = {on:(name,fn)=>listener=fn,off:()=>detached=true};
 const watcher=watchGeneration(page,EVIDENCE);
 await listener({url:()=> 'http://fixture/api/agent/run', request:()=>({method:()=> 'POST'}),
  status:()=>200,text:async()=>event('error','private secret')});
 assert.throws(()=>watcher.check(), {name:'ProductFailure'});
 assert(!require('node:fs').readFileSync(EVIDENCE,'utf8').includes('private secret'));
 watcher.close(); assert(detached);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    for key, value in [('TS', ts), ('HELPER', helper), ('EVIDENCE', tmp_path / 'failure.json')]:
        script = script.replace(key, json.dumps(str(value)))
    result = subprocess.run(['node', '-'], input=script, text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_actual_browser_metadata_and_paginated_model_locator(tmp_path):
    package = REPO / 'test-e2e/infra/automation/d4/node_modules/playwright'
    ts = REPO / 'frontend/node_modules/typescript/lib/typescript.js'
    script = r'''
const assert = require('node:assert/strict');
const {chromium} = require(PACKAGE);
const ts = require(TS);
const fs = require('node:fs');
function load(relative) {
 const mod={exports:{}};
 const src=ts.transpileModule(fs.readFileSync(REPO+'/'+relative,'utf8'), {
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const localRequire=(name)=> name==='playwright/test' ? require(PACKAGE+'/test') :
  name.includes('runtime-config') ? {appPath:x=>x} : require(name);
 new Function('require','module','exports',src)(localRequire,mod,mod.exports);
 return mod.exports;
}
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage();
  const {ChatPage}=load('test-e2e/infra/automation/d4/pages/chat.page.ts');
  const mockHistory=(data,code=0,status=200)=>new ChatPage({request:{get:async(path)=>{
   assert.equal(path,'/api/conversation/7');
   return {status:()=>status,json:async()=>({code,data})};
  }}});
  assert.equal(await mockHistory([{conversation_id:'7',conversation_title:'manual'}]).persistedThreadTitle(7),'manual');
  await assert.rejects(mockHistory({conversation_title:'manual'}).persistedThreadTitle(7));
  await assert.rejects(mockHistory([]).persistedThreadTitle(7));
  await assert.rejects(mockHistory([{conversation_id:'8',conversation_title:'manual'}]).persistedThreadTitle(7));
  await assert.rejects(mockHistory([{conversation_id:'7',conversation_title:'manual'}],1).persistedThreadTitle(7));
  await page.setContent(`<button id="history">Metadata检索与回复</button>
    <button id="exact-history">Metadata</button>
    <button id="composer"><svg class="lucide-braces"></svg>Metadata</button>
    <div role="dialog" aria-label="Metadata" hidden><textarea></textarea>
     <button id="save">确定</button><button id="cancel">取消</button></div>
    <script>const dialog=document.querySelector('[role=dialog]');
    document.querySelector('#history').onclick=()=>document.body.dataset.wrong='true';
    document.querySelector('#exact-history').onclick=()=>document.body.dataset.wrong='true';
    document.querySelector('#composer').onclick=()=>dialog.hidden=false;
    document.getElementById('save').onclick=()=>{dialog.hidden=true;
      document.getElementById('composer').innerHTML='<svg class="lucide-braces"></svg>Metadata (1)';};
    document.getElementById('cancel').onclick=()=>dialog.hidden=true;</script>`);
  assert.equal(await page.getByRole('button',{name:/Metadata/}).count(),3);
  const chat=new ChatPage(page);
  await chat.setRuntimeMetadata({test_run_id:'unique'});
  assert.equal(await page.getByRole('button',{name:'Metadata',exact:true}).count(),1);
  await chat.assertRuntimeMetadata({test_run_id:'unique'});
  assert.equal(await page.locator('body').getAttribute('data-wrong'),null);
  await page.setContent(`<button>chat.[manual]+</button>
    <div class="group/item" data-active="false"><button id="thread">
     <span title="已完成">已完成</span><span class="truncate">chat.[manual]+</span></button>
     <button id="menu">菜单</button></div>
    <div class="group/item"><button><span class="truncate">chat.[manual]+-wrong</span></button></div>
    <script>document.getElementById('thread').onclick=()=>
      document.querySelector('[class="group/item"]').dataset.active='true';</script>`);
  // The old accessible-name selector misses the real item and selects the
  // unrelated button. Status must not weaken exact title or history scoping.
  assert.equal(await page.getByRole('button',{name:'chat.[manual]+',exact:true}).count(),1);
  assert.equal(await chat.threadButton('chat.[manual]+').count(),1);
  assert.equal(await chat.threadButton('chat.[manual]+').getAttribute('id'),'thread');
  assert.equal(await chat.threadButton('missing-title').count(),0);
  assert.equal(await chat.threadButton('chat.').count(),0);
  await chat.openThread('chat.[manual]+');
  assert.equal(await chat.currentThreadTitle(),'chat.[manual]+');
  await page.locator('#thread span[title]').evaluate(node=>node.remove());
  assert.equal(await chat.threadButton('chat.[manual]+').count(),1);
  const {ModelPage}=load('test-e2e/infra/automation/d4/pages/model.page.ts');
  await page.setContent(`<section><h2>模型库</h2>
   <input placeholder="搜索模型名 / 自定义名称 / API 地址"><div id="rows"></div></section>
   <div role="dialog" aria-label="编辑模型" hidden>编辑模型</div>
   <script>const names=Array.from({length:9},(_,i)=>'other-'+i).concat('target-page-two');
   function render(query=''){const rows=document.querySelector('#rows');rows.replaceChildren();
    for(const name of names.filter(n=>n.includes(query)).slice(0,8)){
     const row=document.createElement('div');const text=document.createElement('span');text.textContent=name;
     const button=document.createElement('button');button.textContent='编辑';
     button.onclick=()=>document.querySelector('[role=dialog]').hidden=false;
     row.append(text,button);rows.append(row);}}
   document.querySelector('input').oninput=e=>render(e.target.value);render();</script>`);
  assert.equal(await page.getByText('target-page-two',{exact:true}).count(),0);
  await new ModelPage(page).openEditDialog('target-page-two','大语言模型');
  assert.equal(await page.getByText('target-page-two',{exact:true}).count(),1);
  await page.route('http://fixture/**',async(route)=>{
   if(route.request().url().includes('abort=true'))return route.abort();
   return route.fulfill({status:200,contentType:'text/html',body:'OK'});
  });
  await page.goto('http://fixture/');
  const {watchTitleRequests}=load('test-e2e/infra/automation/d4/runner/title-requests.ts');
  const titles=watchTitleRequests(page,EVIDENCE);
  await page.evaluate(()=>fetch('/api/conversation/generate_title?private=hidden').then(r=>r.text()));
  await titles.settle(2000);
  await page.evaluate(()=>fetch('/api/conversation/generate_title?abort=true').catch(()=>null));
  await titles.settle(2000);
  const states=JSON.parse(fs.readFileSync(EVIDENCE,'utf8')).requests;
  assert.deepEqual(states.map(x=>x.state),['finished','failed']);
  assert.equal(states[0].status,200);
  assert(!fs.readFileSync(EVIDENCE,'utf8').includes('hidden'));
  titles.close();
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    for key, value in [('PACKAGE', package), ('TS', ts), ('REPO', REPO),
                       ('EVIDENCE', tmp_path / 'actual-browser-title-requests.json')]:
        script = script.replace(key, json.dumps(str(value)))
    env = dict(os.environ)
    browsers = Path(sys.prefix).parent / 'playwright-browsers'
    if browsers.is_dir():
        env['PLAYWRIGHT_BROWSERS_PATH'] = str(browsers)
    result = subprocess.run(['node', '-'], input=script, text=True, encoding='utf-8', env=env,
                            capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr


def test_chat_has_one_real_action_for_each_expected_assertion():
    case = yaml.safe_load((REPO / 'test-e2e/cases/PW-CHAT-01/case.yaml').read_text(encoding='utf-8'))['case']
    source = (REPO / 'test-e2e/cases/PW-CHAT-01/test.spec.ts').read_text(encoding='utf-8')
    actions = source.split('assertions: [', 1)[1]
    assert actions.count('async () =>') == len(case['expected_results']) == 4
    assert 'persistedThreadTitle(firstConversationId)).toBe(firstTitle)' in actions
    assert 'await page.reload' in actions
    assert 'secondTitleVerified = true' in source
    assert 'Promise.all(titleRequests)' not in source
    assert source.count('await titleRequests.settle()') == 2


def test_title_request_lifecycle_bounds_waiting_and_redacts_evidence(tmp_path):
    helper = REPO / 'test-e2e/infra/automation/d4/runner/title-requests.ts'
    ts = REPO / 'frontend/node_modules/typescript/lib/typescript.js'
    script = r'''
const assert = require('node:assert/strict');
const {EventEmitter}=require('node:events');
const fs=require('node:fs');
const ts=require(TS);
const mod={exports:{}};
new Function('require','module','exports',ts.transpileModule(fs.readFileSync(HELPER,'utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
}).outputText)(require,mod,mod.exports);
(async()=>{
 const page=new EventEmitter();
 page.waitForTimeout=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 const tracker=mod.exports.watchTitleRequests(page,EVIDENCE);
 const request={url:()=> 'http://fixture/api/conversation/generate_title?secret=hidden',
  response:()=>{throw Error('Must not depend on response promises');}};
 page.emit('request',{url:()=> 'http://fixture/api/other'});
 await tracker.settle(0);
 assert.deepEqual(JSON.parse(fs.readFileSync(EVIDENCE)).requests,[]);
 page.emit('request',request);
 page.emit('response',{request:()=>request,status:()=>200});
 await assert.rejects(tracker.settle(0),{name:'TimeoutError'});
 assert.equal(JSON.parse(fs.readFileSync(EVIDENCE)).requests[0].state,'pending');
 page.emit('requestfinished',request);
 await tracker.settle(0);
 assert.equal(JSON.parse(fs.readFileSync(EVIDENCE)).requests[0].state,'finished');
 const failed={...request};
 page.emit('request',failed);
 page.emit('requestfailed',failed);
 await tracker.settle(0);
 assert.equal(JSON.parse(fs.readFileSync(EVIDENCE)).requests[1].state,'failed');
 const late={...request};
 page.emit('request',late);
 setTimeout(()=>page.emit('requestfinished',late),10);
 await tracker.settle(1000);
 assert.equal(JSON.parse(fs.readFileSync(EVIDENCE)).requests[2].state,'finished');
 assert(!fs.readFileSync(EVIDENCE,'utf8').includes('hidden'));
 tracker.close();
 for(const name of ['request','response','requestfinished','requestfailed'])
  assert.equal(page.listenerCount(name),0);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    for key, value in [('TS', ts), ('HELPER', helper), ('EVIDENCE', tmp_path / 'title-requests.json')]:
        script = script.replace(key, json.dumps(str(value)))
    result = subprocess.run(['node', '-'], input=script, text=True, encoding='utf-8',
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
