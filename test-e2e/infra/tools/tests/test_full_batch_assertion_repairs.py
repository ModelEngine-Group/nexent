"""Offline fault detection for test repairs, not live product acceptance."""
from collections import Counter
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'test-e2e/infra/automation'))
from shared.cmsr import HistoryVerificationError, verify_rejected_history
from shared.memory_mock import MemoryMock


def case_module(case_id):
    spec = importlib.util.spec_from_file_location('repair_' + case_id.replace('-', '_'),
                                                ROOT / 'test-e2e/cases' / case_id / 'test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rejected_fixture():
    events = [{'type': 'tool', 'tool_name': 'search_memory', 'content': ''},
              {'type': 'execution_logs', 'content': '[]'}, {'type': 'step_count', 'content': '1'}]
    events.extend({'type': 'model_attempt_control', 'phase': phase} for phase in ['begin', 'rollback'] * 3)
    events.append({'type': 'error'})
    parts = [dict(event) for event in events[:3]]
    return events, {'data': [{'message': [{'role': 'assistant', 'message': parts}]}]}, parts


def test_rejected_history_allows_only_observed_pre_run_logs():
    events, history, _ = rejected_fixture()
    assert verify_rejected_history(history, events, 'fixture')['rejected_action_persisted'] is False


def test_rejected_history_allows_empty_synthetic_history_view_placeholder():
    events, history, parts = rejected_fixture()
    parts.append({'type': 'final_answer', 'content': ''})
    assert verify_rejected_history(history, events, 'fixture')['rejected_action_persisted'] is False


@pytest.mark.parametrize('fault', ['stored-unit', 'whitespace', 'null', 'duplicate', 'sse-answer'])
def test_empty_answer_exception_cannot_hide_a_persisted_or_emitted_answer(fault):
    events, history, parts = rejected_fixture()
    placeholder = {'type': 'final_answer', 'content': ''}
    if fault == 'stored-unit':
        placeholder['unit_index'] = 3
    elif fault == 'whitespace':
        placeholder['content'] = ' '
    elif fault == 'null':
        placeholder['content'] = None
    elif fault == 'duplicate':
        parts.append(dict(placeholder))
    else:
        events.append(dict(placeholder))
    parts.append(placeholder)
    with pytest.raises(HistoryVerificationError):
        verify_rejected_history(history, events, 'fixture')


@pytest.mark.parametrize('mutation', [
    {'type': 'model_output_thinking', 'content': 'discarded'},
    {'type': 'model_output_code', 'content': 'discarded'},
    {'type': 'parse', 'content': 'print(1)'},
    {'type': 'execution_logs', 'content': '[]'},
    {'type': 'tool', 'content': ''},
    {'type': 'tool-call', 'content': 'action'},
    {'type': 'final_answer', 'content': 'unexpected'},
    {'type': 'error', 'content': 'CMSR_REJECTED_fixture'},
])
def test_rejected_history_detects_persisted_action_mutations(mutation):
    events, history, parts = rejected_fixture()
    parts.append(mutation)
    with pytest.raises(HistoryVerificationError):
        verify_rejected_history(history, events, 'fixture')


@pytest.mark.parametrize('mutation', ['unmatched', 'duplicate', 'missing', 'missing-step', 'extra-tool', 'reordered'])
def test_pre_run_log_exception_cannot_hide_arbitrary_history(mutation):
    events, history, parts = rejected_fixture()
    if mutation == 'unmatched':
        parts[1]['content'] = 'not observed'
    elif mutation == 'duplicate':
        parts.insert(1, dict(parts[1]))
    elif mutation == 'missing':
        parts.pop(1)
    elif mutation == 'missing-step':
        parts.pop(2)
    elif mutation == 'extra-tool':
        parts.insert(0, {'type': 'tool', 'content': ''})
    else:
        parts[:2] = reversed(parts[:2])
    with pytest.raises(HistoryVerificationError):
        verify_rejected_history(history, events, 'fixture')


@pytest.mark.asyncio
async def test_memory_observations_are_scoped_without_mutating_default_headers():
    requests = []
    async def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'counts': {'search': 1}})
    async with httpx.AsyncClient(base_url='http://fixture', headers={'X-Org-Id': 'old'},
                                transport=httpx.MockTransport(reply)) as api:
        mock = MemoryMock(api, {}, 'user', 'old')
        assert await mock.counts(org='new') == {'search': 1}
        await mock.counts()
        assert [request.headers['X-Org-Id'] for request in requests] == ['new', 'old']
        assert all(request.url.params['user_id'] == 'user' for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', [None, 'stale-org', 'no-search', 'old-answer', 'no-missing-answer',
                                 'recovery-no-search', 'recovery-wrong-answer', 'recovery-missing-seed',
                                 'recovery-internal-seed', 'recovery-polluted', 'recovery-mixed-answer'])
async def test_memory_hot_update_isolated_inputs_and_wire_guards(monkeypatch, fault):
    module = case_module('AGT-071')
    writes, counts = [], Counter()
    mock = SimpleNamespace(settings={'api_key': 'offline-fixture'}, org='old')
    mock.provider_params = lambda org=None: {'plugin.org_id': org or 'old'}
    async def observed(org=None):
        return {'search': counts[org or 'old']}
    mock.counts = observed
    mock.fault = AsyncMock()
    state = {'org': 'old', 'ingested': False}
    def response(body, status=200):
        return httpx.Response(status, json=body, request=httpx.Request('POST', 'http://fixture'))
    class API:
        async def post(self, path, json):
            writes.append(path)
            if path.endswith('/publish') or path in {'/agent/update', '/memory/config/set'}:
                return response({})
            if path == '/memory/long-term/user/versions':
                assert state.get('hot_checked'), 'Local long-term memory polluted the empty-scope acceptance'
                state['local_marker'] = json['content'].split()[-1]
                state['local_lookup'] = json['content'].split()[2]
                return response({}, 201)
            if path == '/memory/providers':
                return response({'provider_config_id': 1})
            if path.endswith('/test-ingest'):
                content = json['units'][0]['unit_content']
                if state.get('hot_checked'):
                    state['recovery_seeded'] = True
                    assert content.split()[2] != state['lookup']
                    assert content.split()[-1] not in (state['marker'], state['local_marker'])
                    assert not mock.fault.await_args.args, 'Recovery must remove the scoped fault first'
                state['lookup'], state['marker'] = content.split()[2], content.split()[-1]
                state['ingested'] = True
                return response({'accepted_count': 1, 'rejected_count': 0})
            if path.endswith('/test-search'):
                if mock.fault.await_args and mock.fault.await_args.args:
                    return response({}, 400)
                if state.get('recovery_seeded'):
                    assert json['query'] == state['lookup']
                    if fault == 'recovery-missing-seed':
                        return response({'items': []})
                    if fault == 'recovery-internal-seed':
                        return response({'items': [{'content': state['marker'], 'is_external': False}]})
                    if fault == 'recovery-polluted':
                        return response({'items': [{'content': state['marker'] + ' ' + state['local_marker'],
                                                    'is_external': True}]})
                return response({'items': [{'content': state['marker'], 'is_external': True}]
                                 if state['ingested'] and state['org'] == 'old' else []})
            raise AssertionError(path)
        async def put(self, path, json):
            state['org'] = json['params']['plugin.org_id']
            return response({})
        async def get(self, path, params=None):
            if path == '/memory/long-term/user':
                return response({'empty': False, 'version': {'content': state['local_marker']}})
            if path == '/memory/context':
                assert params == {'layers': 'user'}
                return response({'user_long_term': [{'content': state['local_marker']}]})
            code = ('timeout' if mock.fault.await_args.args[1] else 'provider_error') if mock.fault.await_args else None
            return response({'timeout_seconds': 2, 'last_error_code': code})
    async def run(identity, agent, query, phase, *, expected_external=None):
        assert state['marker'] not in query, 'Answer must never be supplied by the question'
        if phase == 'hot-update':
            assert '/memory/long-term/user/versions' not in writes
            counts['old' if fault == 'stale-org' else state['org']] += fault != 'no-search'
            state['hot_checked'] = True
            return state['marker'] if fault == 'old-answer' else 'wrong' if fault == 'no-missing-answer' else 'NOT_FOUND'
        if phase == 'recovery':
            assert expected_external == state['marker']
            assert state['recovery_seeded'] and query == state['lookup']
            assert state['org'] == 'old' and writes.count('/memory/providers') == 1
            assert state['local_lookup'].split('-', 1)[1] != query.split('-', 1)[1]
            if fault == 'recovery-wrong-answer':
                return state['local_marker']
        if not (phase == 'recovery' and fault == 'recovery-no-search'):
            counts[state['org']] += 1
        if phase == 'recovery' and fault == 'recovery-mixed-answer':
            return state['marker'] + ' ' + state['local_marker']
        return state['local_marker'] if phase.startswith('local-') else state['marker']
    @asynccontextmanager
    async def model(*args, **kwargs): yield 1
    @asynccontextmanager
    async def draft(*args, **kwargs): yield 1, {}
    monkeypatch.setattr(module, 'owned_configured_model', model)
    monkeypatch.setattr(module, '_draft_agent', draft)
    monkeypatch.setattr(module, 'run_memory_agent', run)
    monkeypatch.setattr(module, 'write_case_evidence', lambda *a, **kw: None)
    if fault:
        with pytest.raises(AssertionError):
            await module.exercise_external_memory(SimpleNamespace(), mock, API())
        if not fault.startswith('recovery-'):
            assert '/memory/long-term/user/versions' not in writes
    else:
        await module.exercise_external_memory(SimpleNamespace(), mock, API())
        assert writes.count('/memory/long-term/user/versions') == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('statuses', [[409, 200], [409, 404], [200], [404]])
async def test_owned_kb_cleanup_waits_then_marks_deleted(monkeypatch, statuses):
    module = case_module('API-AUTO-FCA0909EFA632CC7')
    calls, states, evidence = [], [], []
    @asynccontextmanager
    async def client(*args, **kwargs):
        class API:
            async def delete(self, path):
                calls.append(path)
                return httpx.Response(statuses[len(calls) - 1], json={'code': '060109'})
        yield API()
    monkeypatch.setattr(module, 'client', client)
    monkeypatch.setattr(module.asyncio, 'sleep', AsyncMock())
    monkeypatch.setattr(module, 'mark_asset_state', lambda *args: states.append(args))
    monkeypatch.setattr(module, 'write_case_evidence', lambda name, body: evidence.append(body))
    await module._cleanup_kb(SimpleNamespace(access_token='fixture'), 'owned-index')
    assert calls == ['/indices/owned-index'] * len(statuses)
    assert states == [('owned_knowledge_bases', 'owned-index', 'DELETED')]
    assert evidence[-1]['result'] == 'DELETED'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code,timeout', [(409, 'other', 180), (500, '060109', 180), (409, '060109', 0)])
async def test_cleanup_errors_cannot_pass_or_retry_unrelated_failures(monkeypatch, status, code, timeout):
    module = case_module('API-AUTO-FCA0909EFA632CC7')
    calls, evidence = [], []
    @asynccontextmanager
    async def client(*args, **kwargs):
        class API:
            async def delete(self, path):
                calls.append(path)
                return httpx.Response(status, json={'code': code})
        yield API()
    monkeypatch.setattr(module, 'client', client)
    mark = SimpleNamespace(fn=lambda *a: pytest.fail('Unsuccessful cleanup cannot mark deletion'))
    monkeypatch.setattr(module, 'mark_asset_state', mark.fn)
    monkeypatch.setattr(module, 'write_case_evidence', lambda name, body: evidence.append(body))
    with pytest.raises((RuntimeError, TimeoutError)):
        await module._cleanup_kb(SimpleNamespace(access_token='fixture'), 'owned-index', timeout=timeout)
    assert len(calls) == 1 and evidence[-1]['result'] == 'ORPHANED'


@pytest.mark.asyncio
async def test_cleanup_failure_preserves_the_original_business_failure(monkeypatch):
    module = case_module('API-AUTO-FCA0909EFA632CC7')
    identity = SimpleNamespace()
    monkeypatch.setattr(module, '_create_knowledge_base', AsyncMock(return_value='owned-index'))
    monkeypatch.setattr(module, '_upload_and_process', AsyncMock(side_effect=AssertionError('primary business failure')))
    cleanup = AsyncMock(side_effect=TimeoutError('cleanup did not drain'))
    monkeypatch.setattr(module, '_cleanup_kb', cleanup)
    with pytest.raises(AssertionError, match='primary business failure') as captured:
        await module.test_delete_document_by_scope(identity)
    cleanup.assert_awaited_once_with(identity, 'owned-index')
    assert 'Owned KB cleanup failed: TimeoutError' in captured.value.__notes__


def test_actual_debug_helper_and_failure_classification(tmp_path):
    script = r'''
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ts=require(TS);
const {chromium}=require(PACKAGE);
function load(file) {
 const mod={exports:{}};
 const source=ts.transpileModule(fs.readFileSync(ROOT+'/'+file,'utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const resolve=(name)=>name==='playwright/test'?require(PACKAGE+'/test'):
  name.includes('runtime-config')?{appPath:x=>x}:require(name);
 new Function('require','module','exports',source)(resolve,mod,mod.exports);
 return mod.exports;
}
(async()=>{
 const {ContractExecution}=load('test-e2e/infra/automation/d4/runner/journey.ts');
 const kind=ContractExecution.prototype.failKind;
 assert.equal(kind.call({currentKind:'steps'},Object.assign(new Error('mismatch'),{matcherResult:{}})),'FAIL');
 assert.equal(kind.call({currentKind:'steps'},new Error('broken script')),'AUTOMATION_ERROR');
 assert.equal(kind.call({},Object.assign(new Error('dependency'),{name:'DependencyFailure'})),'BLOCKED_BY_DEPENDENCY');
 const browser=await chromium.launch({headless:true});
 let phase='setup';
 const deadline=setTimeout(()=>{console.error('debug fixture stalled: '+phase);void browser.close();},18000);
 const server=require('node:http').createServer((request,response)=>{
  response.writeHead(200,{'Content-Type':request.url.startsWith('/api/')?'text/event-stream':'text/html'});
  if(request.url==='/api/agent/run'){
   response.write('data: {"type":"model_output_thinking","content":"not an answer"}\n\n');
   setTimeout(()=>response.end('data: [DONE]\n\n'),250);
  } else response.end(request.url.startsWith('/api/')?'data: [DONE]\n\n':'<html><body></body></html>');
 });
 try {
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const page=await browser.newPage();
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.setContent(`<style>.hidden{display:none}</style><section><h3>Debug</h3><textarea placeholder="发送消息..."></textarea><button>发送</button>
   <div id="normal"></div><div class="hidden"><div data-slot="aui_assistant-message-root"><div data-citation-index-map><div class="aui-md">OLD_COMPARE</div></div></div></div></section>
   <script>document.querySelector('textarea').oninput=()=>{
    document.querySelector('button').disabled=!document.querySelector('textarea').value;
   };
   document.querySelector('button').onclick=async()=>{
    const button=document.querySelector('button'); button.disabled=true;
    const answer=document.querySelector('textarea').value==='empty'?'':'REAL_RESULT';
    document.querySelector('textarea').value='';
    document.querySelector('#normal').insertAdjacentHTML('beforeend',
     "<div data-slot='aui_assistant-message-root'><div data-citation-index-map><div class='aui-md'></div></div></div>");
    await (await fetch('/api/agent/search_info',{method:'POST'})).text();
    await (await fetch('/api/agent/run',{method:'POST'})).text();
    setTimeout(()=>{document.querySelector('#normal [data-slot=aui_assistant-message-root]:last-of-type .aui-md').textContent=answer;},100);
   };</script>`);
  const {AgentPage}=load('test-e2e/infra/automation/d4/pages/agent.page.ts');
  const agents=new AgentPage(page);
  phase='successful answer';
  assert.equal(await agents.sendDebug('question','REAL_RESULT'),'REAL_RESULT');
  phase='wrong answer';
  const start=Date.now();
  await assert.rejects(agents.sendDebug('another question','MISSING'),{name:'ProductFailure'});
  assert(Date.now()-start<10000,'Completed wrong answer must not poll for five minutes');
  const emptyStart=Date.now();
  phase='empty answer';
  await assert.rejects(agents.sendDebug('empty','MISSING'),{name:'ProductFailure'});
  assert(Date.now()-emptyStart<10000,'Completed empty answer must not poll for five minutes');
 } finally { phase='cleanup'; await browser.close(); await new Promise(resolve=>server.close(resolve)); clearTimeout(deadline); }
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    for name, value in [('TS', ROOT / 'frontend/node_modules/typescript/lib/typescript.js'),
                        ('PACKAGE', ROOT / 'test-e2e/infra/automation/d4/node_modules/playwright'), ('ROOT', ROOT)]:
        script = script.replace(name, json.dumps(str(value)))
    result = subprocess.run(['node', '-'], input=script, text=True, encoding='utf-8', capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('create_ok', [True, False])
def test_resource_model_preparation_does_not_occupy_admin_browser(create_ok):
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),ts=require(__TS_PATH__);
let body,handlers,cleanup,closed=0,health=0,registered=0;
const main={};
const owner={request:{post:async(path,options)=>{
 assert.equal(path,'/api/model/create'); body=options.data;
 return {ok:()=>CREATE_OK};
}}};
const expect=value=>({toBe:wanted=>assert.equal(value,wanted)});
const modules={
 'journey':{journey:(id,fn)=>{assert.equal(id,'PW-RESOURCE-04');body=fn({page:main,expect,contract:{deferCleanup:fn=>cleanup=fn}})}},
 'scenario':{executeFixedScenario:async(context,value)=>{handlers=value;}},
 'runtime-config':{runToken:()=> 'fixture',configuredModel:()=>({provider:'fixture-provider',model:'fixture-model',baseUrl:'http://fixture.invalid',secret:'synthetic',maxTokens:32768})},
 'sessions':{loginCurrent:()=>{throw new Error('setup must not occupy the shared admin browser');},loginIsolated:async(source,id)=>{
  assert.equal(source,main);assert.equal(id,'tenant_a_admin');return {page:owner,context:{close:async()=>closed++}};
 }},
 'assets':{resolveReadyAsset:()=> 'ready',registerReadyAsset:(section,key,value,id,rule)=>{
  registered++;assert.equal(rule.identity,'tenant_a_admin');assert.equal(rule.path,'/model/delete');
 }},
 'resource.page':{ResourcePage:class{}},'chat.page':{ChatPage:class{}},
 'model.page':{ModelPage:class{constructor(page){assert.equal(page,owner);}
  async verifyPersistedModel(alias,capability,dependency){health++;assert.equal(capability,'llm');assert.equal(dependency,true);}
  async deleteModel(alias){assert.equal(alias,'resource-model-fixture');}
 }},
};
const mod={exports:{}};
const source=ts.transpileModule(fs.readFileSync(__SOURCE_PATH__,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
new Function('require','module','exports',source)(name=>modules[name.split('/').pop()]||require(name),mod,mod.exports);
(async()=>{
 await body;
 if(CREATE_OK) await handlers.preconditions[0]();
 else await assert.rejects(handlers.preconditions[0]());
 assert.equal(body.max_tokens,32768);assert.equal(body.skip_default_backfill,true);
 assert.equal(body.display_name,'resource-model-fixture');
 assert.equal(body.api_key,'synthetic');assert.equal(closed,1);
 assert.equal(health,CREATE_OK?1:0);assert.equal(registered,CREATE_OK?1:0);
 await cleanup();assert.equal(closed,2);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    for name, value in [('__TS_PATH__', ROOT / 'frontend/node_modules/typescript/lib/typescript.js'),
                        ('__SOURCE_PATH__', ROOT / 'test-e2e/cases/PW-RESOURCE-04/test.spec.ts')]:
        script = script.replace(name, json.dumps(str(value)))
    script = script.replace('CREATE_OK', str(create_ok).lower())
    result = subprocess.run(['node', '-'], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('json_format', [False, True])
def test_configured_model_preserves_existing_output_budget(tmp_path, monkeypatch, json_format):
    (tmp_path / 'config').mkdir()
    configured = {'models': [{
        'id': 'synthetic', 'capability': 'llm', 'provider': 'fixture-provider',
        'base_url': 'http://fixture.invalid', 'model': 'old,new',
        'preferred_model': 'new', 'max_tokens': 32768,
        'secret_env_key': 'D4_SYNTHETIC_MODEL_SECRET',
    }]}
    (tmp_path / 'config/models.yaml').write_text(
        json.dumps(configured) if json_format else yaml.safe_dump(configured), encoding='utf-8')
    monkeypatch.setenv('TEST_ROOT', str(tmp_path))
    monkeypatch.setenv('NEXENT_TEST_HOME', str(tmp_path))
    monkeypatch.setenv('NEXENT_REPO', str(ROOT))
    monkeypatch.setenv('FIXED_TEST_PYTHON', sys.executable)
    monkeypatch.setenv('D4_SYNTHETIC_MODEL_SECRET', 'synthetic')
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),ts=require(__TS_PATH__);
const mod={exports:{}};
const source=ts.transpileModule(fs.readFileSync(__CONFIG_PATH__,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
new Function('require','module','exports',source)(require,mod,mod.exports);
const asset=mod.exports.configuredModel('llm');
assert.equal(asset.maxTokens,32768);assert.equal(asset.model,'new');
assert.equal(asset.provider,'fixture-provider');assert.equal(asset.secret,'synthetic');
'''
    for name, value in [('__TS_PATH__', ROOT / 'frontend/node_modules/typescript/lib/typescript.js'),
                        ('__CONFIG_PATH__', ROOT / 'test-e2e/infra/automation/d4/runner/runtime-config.ts')]:
        script = script.replace(name, json.dumps(str(value)))
    result = subprocess.run(['node', '-'], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'synthetic' not in result.stdout


def test_chart_restore_uses_only_its_owned_conversation_label():
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),ts=require(__TS_PATH__);
let pending,handlers,cleanup,title,seeded=false,opened=false,deleted=false;
const page={request:{post:async(path,options)=>{
 assert.equal(path,'/api/conversation/rename');assert.equal(options.data.conversation_id,7);
 title=options.data.name;assert.equal(title,'chart-fixture');return {ok:()=>true,json:async()=>({code:0})};
},get:async(path)=>{
 assert.equal(path,'/api/conversation/7');return {ok:()=>true,json:async()=>({data:[
  {conversation_id:8,message:[{role:'assistant',message_id:88}]},
  {conversation_id:7,message:[{role:'assistant',message_id:90}]},
 ]})};
}},on:()=>{},reload:async()=>{assert.equal(seeded,true);}};
const expect=value=>({toBe:other=>assert.equal(value,other),toBeGreaterThan:other=>assert(value>other)});
const modules={
 'journey':{journey:(id,fn)=>pending=fn({page,expect,contract:{deferCleanup:fn=>cleanup=fn}})},
 'scenario':{executeFixedScenario:async(context,value)=>{handlers=value;}},
 'runtime-config':{runToken:()=> 'fixture'},'sessions':{},'assets':{},
 'chat.page':{ChatPage:class{
  async sendAndWait(){} currentConversationId(){return 7;}
  currentThreadTitle(){throw new Error('duplicate default titles must not select shared history');}
  async persistedThreadTitle(id){assert.equal(id,7);return title;}
  async openThread(label,occurrence){assert.equal(label,title);assert.equal(occurrence,undefined);opened=true;}
  async deleteConversationById(id){assert.equal(id,7);deleted=true;}
 }},
};
const mod={exports:{}};
const source=ts.transpileModule(fs.readFileSync(__SOURCE_PATH__,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
new Function('require','module','exports',source)(name=>name==='node:child_process'?{
 execFileSync:(python,args)=>{assert.equal(args[args.indexOf('--conversation-id')+1],'7');assert.equal(args[args.indexOf('--message-id')+1],'90');seeded=true;}
}:modules[name.split('/').pop()]||require(name),mod,mod.exports);
(async()=>{await pending;await handlers.steps[9]();assert.equal(opened,true);await cleanup();assert.equal(deleted,true);})()
 .catch(error=>{console.error(error);process.exitCode=1;});
'''
    for name, value in [('__TS_PATH__', ROOT / 'frontend/node_modules/typescript/lib/typescript.js'),
                        ('__SOURCE_PATH__', ROOT / 'test-e2e/cases/PW-CHART-01/test.spec.ts')]:
        script = script.replace(name, json.dumps(str(value)))
    result = subprocess.run(['node', '-'], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_skill_journey_actions_cover_every_contract_row():
    script = r'''
const ts=require(__TYPESCRIPT_PATH__);
const file=ts.createSourceFile('test.spec.ts',require('node:fs').readFileSync(SOURCE,'utf8'),
 ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
let counts;
function visit(node) {
 if(ts.isCallExpression(node)&&node.expression.getText(file)==='executeFixedScenario') {
  counts={};
  for(const property of node.arguments[1].properties)
   if(ts.isPropertyAssignment(property)&&ts.isArrayLiteralExpression(property.initializer))
    counts[property.name.getText(file)]=property.initializer.elements.length;
 }
 ts.forEachChild(node,visit);
}
visit(file); process.stdout.write(JSON.stringify(counts));
'''
    for name, value in [('__TYPESCRIPT_PATH__', ROOT / 'frontend/node_modules/typescript/lib/typescript.js'),
                        ('SOURCE', ROOT / 'test-e2e/cases/PW-AGENT-03/test.spec.ts')]:
        script = script.replace(name, json.dumps(str(value)))
    result = subprocess.run(['node', '-'], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    counts = json.loads(result.stdout)
    case = yaml.safe_load((ROOT / 'test-e2e/cases/PW-AGENT-03/case.yaml').read_text(encoding='utf-8'))['case']
    assert counts == {'preconditions': len(case['preconditions']), 'steps': len(case['steps']),
                      'assertions': len(case['expected_results'])}
