# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Offline regressions for the October 22 test repairs; not live acceptance."""

from pathlib import Path
from contextlib import asynccontextmanager
import sys
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'automation'))
from shared.final_answers import final_answer_text, assert_rejected_answer_stream
from shared import runtime_fault
from shared import faf
from shared.a2a import A2AMock
from shared.asset_registry import AssetDependencyError
from shared.tpc import FixtureConfig

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'environment/services/test-assets'))
from fastapi import FastAPI
import tpc_provider


@pytest.mark.asyncio
async def test_faf_default_model_selection_keeps_the_configured_factory(monkeypatch):
    monkeypatch.delenv('NEXENT_FAF_MODEL_NAME', raising=False)
    monkeypatch.setattr(faf, 'client', lambda *args, **kwargs: pytest.fail('Unexpected catalog lookup'))
    assert await faf.selected_faf_model(SimpleNamespace()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('variant', ['name', 'display', 'missing', 'unavailable', 'ambiguous'])
async def test_faf_explicit_model_selection_is_unique_available_and_read_only(monkeypatch, variant):
    monkeypatch.setenv('NEXENT_FAF_MODEL_NAME', 'verified-real-model')
    row = {'model_id': 71, 'model_name': 'verified-real-model', 'display_name': 'case-profile',
           'connect_status': 'available', 'api_key': 'must-not-be-recorded'}
    if variant == 'display':
        row.update(model_name='provider-call-name', display_name='verified-real-model')
    if variant == 'unavailable':
        row['connect_status'] = 'unavailable'
    rows = [] if variant == 'missing' else [row, dict(row)] if variant == 'ambiguous' else [row]
    calls, evidence = [], []

    @asynccontextmanager
    async def api(*args, **kwargs):
        async def get(path):
            calls.append(path)
            return httpx.Response(200, json={'data': rows}, request=httpx.Request('GET', 'http://fixture/model/llm_list'))
        yield SimpleNamespace(get=get)

    monkeypatch.setattr(faf, 'client', api)
    monkeypatch.setattr(faf, 'write_case_evidence', lambda name, value: evidence.append(value))
    identity = SimpleNamespace(access_token='test-session')
    if variant in {'name', 'display'}:
        assert await faf.selected_faf_model(identity) == 71
        assert evidence[0]['model_name'] == row['model_name']
        assert 'must-not-be-recorded' not in repr(evidence)
    else:
        with pytest.raises(AssetDependencyError, match='uniquely match an available'):
            await faf.selected_faf_model(identity)
        assert not evidence
    assert calls == ['/model/llm_list']


def test_streamed_answer_closes_with_empty_completion_without_duplicate_text():
    events = [
        {'type': 'final_answer', 'content': 'Failure ', 'answer_phase': 'delta', 'step_id': 'one', 'attempt_id': 'first'},
        {'type': 'final_answer', 'content': 'MARKER', 'answer_phase': 'delta', 'step_id': 'one', 'attempt_id': 'first'},
        {'type': 'final_answer', 'content': '', 'answer_phase': 'complete', 'step_id': 'one'},
    ]
    assert final_answer_text(events) == 'Failure MARKER'
    events[-1]['content'] = 'Failure MARKER'
    assert final_answer_text(events) == 'Failure MARKER'


def test_sibling_and_rolled_back_answers_do_not_satisfy_root_answer():
    events = [
        {'type': 'final_answer', 'content': 'WRONG', 'step_id': 'one', 'attempt_id': 'bad'},
        {'type': 'model_attempt_control', 'phase': 'rollback', 'step_id': 'one', 'attempt_id': 'bad'},
        {'type': 'final_answer', 'content': 'CHILD', 'invocation_id': 'child'},
        {'type': 'final_answer', 'content': 'ROOT', 'step_id': 'two', 'attempt_id': 'good'},
    ]
    assert final_answer_text(events) == 'ROOT'
    assert final_answer_text(events, invocation_id='child') == 'CHILD'


def test_reclassified_legacy_body_is_scoped_to_its_accepted_step():
    events = [
        {'type': 'model_output_thinking', 'content': 'wrong sibling', 'step_id': 'other', 'attempt_id': 'a'},
        {'type': 'model_output_deep_thinking', 'content': 'private thought', 'step_id': 'one', 'attempt_id': 'b'},
        {'type': 'model_output_thinking', 'content': 'D3-META-', 'step_id': 'one', 'attempt_id': 'b'},
        {'type': 'model_output_thinking', 'content': '314159', 'step_id': 'one', 'attempt_id': 'b'},
        {'type': 'final_answer', 'content': '', 'answer_phase': 'complete', 'reclassify_step': True, 'step_id': 'one'},
    ]
    assert final_answer_text(events) == 'D3-META-314159'


def test_tpc_fixture_copies_keep_authentication_out_of_failure_representations():
    fixture = FixtureConfig(token='private-runtime-credential', agent_id=12)
    copied = fixture.copy()
    assert copied['agent_id'] == 12 and copied['token'] == 'private-runtime-credential'
    assert 'private-runtime-credential' not in repr(fixture)
    assert 'private-runtime-credential' not in repr(copied)


@pytest.mark.parametrize('ending', ['rollback', 'commit', 'sibling', 'incomplete', 'complete'])
def test_rejected_final_deltas_require_their_exact_attempt_rollback(ending):
    events = [
        {'type': 'model_attempt_control', 'phase': 'begin', 'step_id': 's', 'attempt_id': 'a'},
        {'type': 'final_answer', 'answer_phase': 'delta', 'content': 'rejected', 'step_id': 's', 'attempt_id': 'a'},
    ]
    if ending in {'rollback', 'commit', 'sibling'}:
        events.append({'type': 'model_attempt_control', 'phase': 'commit' if ending == 'commit' else 'rollback',
                       'step_id': 's', 'attempt_id': 'sibling' if ending == 'sibling' else 'a'})
    if ending == 'complete':
        events.append({'type': 'final_answer', 'answer_phase': 'complete', 'content': 'rejected', 'step_id': 's'})
    if ending == 'rollback':
        assert_rejected_answer_stream(events)
    else:
        with pytest.raises(AssertionError):
            assert_rejected_answer_stream(events)


@pytest.mark.asyncio
async def test_unreachable_a2a_mock_is_a_declared_dependency_failure():
    mock = object.__new__(A2AMock)
    mock.control = SimpleNamespace(get=AsyncMock(side_effect=httpx.ConnectError('fixture endpoint unavailable')))
    with pytest.raises(AssetDependencyError, match='unreachable'):
        await mock.ready()


@pytest.mark.asyncio
async def test_tpc_provider_keeps_auxiliary_calls_out_of_sequence_and_preserves_length():
    app = FastAPI()
    app.include_router(tpc_provider.router)
    nonce = uuid.uuid4().hex
    path = '/tpc/' + nonce
    transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 1234))
    async with httpx.AsyncClient(transport=transport, base_url='http://fixture.test') as api:
        assert (await api.get(path + '/__stats')).status_code == 404
        assert (await api.post(path + '/__control', json={'responses': ['<code>broken(', '<final_answer>OK</final_answer>'],
                                                        'finish_reason': 'length'})).status_code == 200
        await api.post(path + '/v1/chat/completions', json={'max_tokens': 100, 'model': 'tpc'})
        assert (await api.get(path + '/__stats')).json()['request_count'] == 0
        response = await api.post(path + '/v1/chat/completions', json={'max_tokens': 4096, 'model': 'tpc', 'stream': True})
        frames = [json.loads(line[5:]) for line in response.text.splitlines()
                  if line.startswith('data:') and line[5:].strip() != '[DONE]']
        assert ''.join(frame['choices'][0]['delta'].get('content', '') for frame in frames) == '<code>broken('
        assert frames[-1]['choices'][0]['finish_reason'] == 'length'
        second = await api.post(path + '/v1/chat/completions', json={'max_tokens': 4096, 'model': 'tpc'})
        assert second.json()['choices'][0]['message']['content'] == '<final_answer>OK</final_answer>'
        assert (await api.get(path + '/__stats')).json()['request_count'] == 2
        assert (await api.delete(path)).status_code == 200
        assert (await api.get(path + '/__stats')).status_code == 404
    remote = httpx.ASGITransport(app=app, client=('192.0.2.1', 1234))
    async with httpx.AsyncClient(transport=remote, base_url='http://fixture.test') as api:
        assert (await api.post(path + '/__control', json={'responses': ['not owned']})).status_code == 403


@pytest.mark.parametrize('events', [[], [{'type': 'final_answer', 'content': 'partial', 'answer_phase': 'delta'}],
                                  [{'type': 'final_answer', 'content': '', 'answer_phase': 'complete'}],
                                  [{'type': 'final_answer', 'content': 'child', 'invocation_id': 'child'}],
                                  [{'type': 'final_answer', 'content': 'answer'}, {'type': 'error', 'content': 'failed'}]])
def test_missing_unfinished_and_empty_answers_stay_failures(events):
    with pytest.raises(AssertionError):
        final_answer_text(events)


@pytest.mark.asyncio
@pytest.mark.parametrize('catalog_status', ['available', 'not_detected'])
async def test_fault_model_reaches_inference_only_after_catalog_admission(monkeypatch, catalog_status):
    writes = []

    def response(body):
        return httpx.Response(200, json=body, request=httpx.Request('POST', 'http://fixture.test'))

    @asynccontextmanager
    async def api(*args, **kwargs):
        async def post(path, **values):
            writes.append((path, values))
            return response({})

        async def get(path):
            created = writes[0][1]['json']
            return response({'data': [{'display_name': created['display_name'], 'model_id': 71,
                                       'connect_status': catalog_status}]})
        yield SimpleNamespace(post=post, get=get)

    monkeypatch.setattr(runtime_fault, 'client', api)
    monkeypatch.setattr(runtime_fault, 'fault_control', AsyncMock(return_value={'calls': 0}))
    monkeypatch.setattr(runtime_fault, 'controlled_asset_url', lambda suffix: 'http://fixture.test' + suffix)
    monkeypatch.setattr(runtime_fault, 'register_asset', lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_fault, 'mark_asset_state', lambda *args, **kwargs: None)
    owner = SimpleNamespace(id='owner', access_token='test-session')
    if catalog_status == 'available':
        async with runtime_fault.owned_failure_model(owner, 'AGT-015') as (model_id, nonce):
            assert model_id == 71
            assert writes[0][1]['json']['connect_status'] == 'available'
    else:
        with pytest.raises(AssertionError, match='catalog preflight'):
            async with runtime_fault.owned_failure_model(owner, 'AGT-015'):
                pytest.fail('Unadmitted fixture reached inference')
    assert writes[-1][0] == '/model/delete'
