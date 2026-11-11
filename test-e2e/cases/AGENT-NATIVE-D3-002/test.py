# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual model/agent protocol integration with a case-owned HTTP/SSE provider."""

import importlib.util
import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from smolagents.tools import Tool

from nexent.core.agents.native_runtime import NativeToolCallingAgent
from nexent.core.utils.observer import MessageObserver
from shared.case_evidence import write_case_evidence

CASE_ID = 'AGENT-NATIVE-D3-002'


class EffectTool(Tool):
    name = 'effect'
    description = 'Return the controlled observation.'
    inputs = {}
    output_type = 'string'

    def __init__(self):
        super().__init__()
        self.executions = 0

    def forward(self):
        self.executions += 1
        return getattr(self, 'result', 'ACTUAL_OBSERVATION')


@pytest.fixture
def provider():
    requests = []
    config = {'calls':False,'finish':'stop','refusal':None,'mixed':False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            if config.get('overflow_after_tool') and body.get('tools') and any(m.get('role') == 'tool' for m in body['messages']) and not config.get('overflow_sent'):
                config['overflow_sent'] = True
                payload = json.dumps({'error': {'code': 'context_length_exceeded', 'message': 'controlled input overflow'}}).encode()
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            tool_turn = bool(body.get('tools')) and config['calls'] and not any(m.get('role') == 'tool' for m in body['messages'])
            delta = {'role':'assistant','content':'Checking now.' if tool_turn else 'FINAL_OBSERVED'}
            if tool_turn:
                delta['tool_calls'] = [{'index':0,'id':'actual-call','type':'function',
                    'function':{'name':'effect','arguments':'{}'}}]
            if config.get('context') and not body.get('tools'):
                delta['content'] = 'SUMMARY-SENTINEL: completed observed action.'
            if config.get('reasoning') or config.get('reasoning_only'):
                delta['reasoning_content'] = 'Provider reasoning.'
            if config.get('reasoning_only'):
                delta.pop('content', None)
            if config['refusal']:
                delta['refusal'] = config['refusal']
            finish = ('tool_calls' if tool_turn else 'stop') if config['mixed'] else config['finish']
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            packets = [{'choices':[{'index':0,'delta':delta,'finish_reason':None}]}]
            if finish is not None:
                packets.append({'choices':[{'index':0,'delta':{},'finish_reason':finish}]})
            for packet in packets:
                self.wfile.write(('data: '+json.dumps(packet)+'\n\n').encode())
            if not config.get('reasoning_only'):
                self.wfile.write(('data: '+json.dumps({'choices':[], 'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})+'\n\n').encode())
            if config.get('reasoning_only'):
                self.wfile.write(('data: '+json.dumps({'choices':[], 'usage':{'prompt_tokens':10,'completion_tokens':64,'total_tokens':74,'completion_tokens_details':{'reasoning_tokens':64}}})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    models = []
    try:
        def create():
            kwargs = dict(model_id='qwen3.8-flash',api_base=f'http://127.0.0.1:{server.server_port}/v1',
                          api_key='controlled-provider-placeholder',observer=MessageObserver(lang='en'),
                          max_output_tokens=64,timeout_seconds=5)
            if importlib.util.find_spec('nexent.core.agents.native_model_service'):
                from shared.native_model_service import create_service_model
                model = create_service_model(**kwargs)
            else:
                from nexent.core.models.openai_llm import OpenAIModel
                model = OpenAIModel(**kwargs)
            models.append(model)
            return model
        yield config, requests, create
    finally:
        pending = []
        for model in models:
            model.cancellation_scope.cancel()
            client = getattr(model,'client',None)
            if client is not None:
                client.close()
            pending.append(len(model.cancellation_scope._closers))
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not any(pending)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
def test_normal_mixed_generation_then_stop(provider):
    config, requests, create = provider
    config.update(calls=True,mixed=True,reasoning=True)
    tool = EffectTool()
    model = create()
    agent = NativeToolCallingAgent(tools=[tool],model=model,observer=model.observer,verbosity_level=0,max_steps=2)
    assert str(agent.run('Use effect then report the observation.')) == 'FINAL_OBSERVED'
    assert tool.executions == 1
    events = [json.loads(value) for value in model.observer.message_query]
    public = [value['content'] for value in events if value['type']=='model_output_thinking']
    assert ''.join(public) == 'Checking now.FINAL_OBSERVED'
    assert not any(value['type']=='model_output' for value in events)
    assert ''.join(value['content'] for value in events if value['type']=='model_output_deep_thinking') == 'Provider reasoning.Provider reasoning.'
    assert all(value.get('attempt_id') for value in events if value['type']=='model_output_deep_thinking')
    assert len(requests) == 2
    history = requests[1]['messages']
    assert history[-2]['content'] == 'Checking now.'
    assert history[-2]['tool_calls'][0]['id'] == 'actual-call'
    assert history[-1]['role'] == 'tool'
    assert history[-1]['tool_call_id'] == 'actual-call'
    assert history[-1]['content'] == 'ACTUAL_OBSERVATION'
    write_case_evidence('normal-mixed',{'requests':2,'tool_effects':1,'normal_completion':True})


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.parametrize('finish',['length','content_filter',None,'pause','stop'])
def test_invalid_tool_generation_has_no_effect(provider,finish):
    config, requests, create = provider
    config.update(calls=True,finish=finish)
    tool = EffectTool()
    model = create()
    agent = NativeToolCallingAgent(tools=[tool],model=model,observer=model.observer,verbosity_level=0,max_steps=2)
    with pytest.raises(Exception):
        agent.run('Use effect.')
    assert requests
    assert tool.executions == 0
    assert not any(m['role']=='tool' for m in agent.native_messages)
    write_case_evidence('invalid-tool-'+str(finish),{'finish_reason':finish,'tool_effects':0,'normal_completion':False})


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.parametrize('finish,refusal',[('length',None),('content_filter',None),(None,None),('stop','Filtered')])
def test_incomplete_or_refused_text_is_not_final(provider,finish,refusal):
    config, requests, create = provider
    config.update(finish=finish,refusal=refusal,reasoning_only=finish=='length')
    model = create()
    agent = NativeToolCallingAgent(tools=[],model=model,observer=model.observer,verbosity_level=0,max_steps=2)
    with pytest.raises(Exception) as error:
        agent.run('Return text.')
    if finish == 'length':
        assert 'reasoning_tokens=64' in str(error.value)
        assert 'output-token limit' in str(error.value)
    assert not any(json.loads(value).get('type')=='final_answer' for value in model.observer.message_query)
    assert requests
    write_case_evidence('incomplete-text-'+str(finish)+('-refusal' if refusal else ''),
                        {'finish_reason':finish,'normal_completion':False,'refusal_present':bool(refusal)})


sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_cases import (  # noqa: E402,F401 - Case-local collected contracts.
    test_native_estimated_excess_continues_over_http,
    test_native_overflow_rebuild_preserves_completed_effect,
    test_native_result_offload_preserves_correlated_http_history,
)
