'''D3 AGENT-IT for F-137: evaluation Run scoring fans multiple LLM evaluators
out through the runtime evaluation managed lane and isolates a single failing
evaluator to 0.0 plus a reason without losing the surviving results.

Black-box: this test only talks to the config service HTTP API through the
shared helpers and never imports product internals.'''

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import pytest

from shared.asset_registry import mark_asset_state, register_asset, resolve_asset
from shared.http import assert_status, client


CASE_ID = 'AGT-AUTO-FDE36A61BCBB2572'
STAGE = 'D3'

_TERMINAL = {'COMPLETED', 'FAILED'}
_POLL_INTERVAL = 5.0
_POLL_DEADLINE = 900.0
_RUN_ID = uuid.uuid4().hex[:8]

_LLM_EVALUATOR_PROMPT = (
    'You are a strict evaluator. Compare the actual answer to the expected '
    'answer for the query. Output a single JSON object with exactly two '
    'fields: score (a float between 0.0 and 1.0) and reason (a short '
    'non-empty string explaining the score). Output nothing else. '
    'Query: {{query}} Expected: {{expected}} Actual: {{actual}}'
)

_POISON_CODE = (
'''def evaluate(query, expected, actual, runtime_events, **kwargs):
    raise ValueError('injected evaluator failure for isolation test')
'''
)


def _data(response: Any) -> Any:
    payload = response.json()
    if isinstance(payload, dict) and 'data' in payload:
        return payload['data']
    return payload


def _parse_reason(reason: Any) -> dict:
    if not isinstance(reason, str) or not reason:
        return {}
    try:
        value = json.loads(reason)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _asset(name: str) -> Any:
    return resolve_asset('evaluation', name, consumer_case_id=CASE_ID)


def _normalize_case(case: Any) -> dict | None:
    if not isinstance(case, dict):
        return None
    if isinstance(case.get('inputs'), dict):
        query = str(case['inputs'].get('query') or '')
        answer = str((case.get('label') or {}).get('answer') or '')
    else:
        query = str(case.get('query') or '')
        answer = str(case.get('expected') or case.get('answer') or '')
    if not query:
        return None
    return {'inputs': {'query': query}, 'label': {'answer': answer}}


def _load_cases(inputs: Any) -> list[dict]:
    raw = inputs.get('cases') if isinstance(inputs, dict) else None
    normalized = []
    if isinstance(raw, list):
        for item in raw:
            case = _normalize_case(item)
            if case:
                normalized.append(case)
    if normalized:
        return normalized
    return [{
        'inputs': {'query': 'Summarize why keeping a knowledge base up to date matters.'},
        'label': {'answer': ''},
    }]


async def _create_evaluator(identity, name, evaluator_type, prompt=None, code=None) -> int:
    async with client('config', token=identity.access_token) as api:
        created = await api.post('/evaluators', json={
            'name': name,
            'description': 'D3 generated evaluator for ' + CASE_ID,
            'evaluator_type': evaluator_type,
            'prompt': prompt,
            'code': code,
            'score_range_min': 0,
            'score_range_max': 1,
            'pass_threshold': 0.5,
        })
        assert_status(created, 200)
        evaluator_id = int(_data(created)['evaluator_id'])
        register_asset('owned_evaluators', str(evaluator_id), evaluator_id,
                       owner_case_id=CASE_ID, cleanup={
                           'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                           'path': f'/evaluators/{evaluator_id}', 'allowed_statuses': [200, 404],
                       })
        published = await api.post('/evaluators/' + str(evaluator_id) + '/publish', json={})
        assert_status(published, 200)
        row = _data(published)
        assert row and row.get('status') == 'PUBLISHED'
        return evaluator_id


async def _create_evaluation_set(identity, name, cases) -> int:
    async with client('config', token=identity.access_token) as api:
        created = await api.post('/evaluation-sets', json={
            'name': name,
            'description': 'D3 generated evaluation set for ' + CASE_ID,
        })
        assert_status(created, 200)
        set_id = int(_data(created)['evaluation_set_id'])
        register_asset('owned_evaluation_sets', str(set_id), set_id,
                       owner_case_id=CASE_ID, cleanup={
                           'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                           'path': f'/evaluation-sets/{set_id}', 'allowed_statuses': [200, 404],
                       })
        for case in cases:
            added = await api.post('/evaluation-sets/' + str(set_id) + '/cases', json={
                'inputs': case['inputs'],
                'label': case['label'],
            })
            assert_status(added, 200)
        return set_id


async def _create_run(identity, agent_id, agent_version_no, judge_model_id, set_id, evaluator_ids) -> int:
    payload = {
        'agent_id': int(agent_id),
        'judge_model_id': int(judge_model_id),
        'evaluation_set_id': int(set_id),
        'evaluator_ids': [int(eid) for eid in evaluator_ids],
    }
    if agent_version_no is not None:
        payload['agent_version_no'] = int(agent_version_no)
    async with client('config', token=identity.access_token) as api:
        created = await api.post('/agent-evaluations', json=payload)
        assert_status(created, 200)
        run_id = int(_data(created)['agent_evaluation_id'])
        register_asset('owned_evaluation_runs', str(run_id), run_id,
                       owner_case_id=CASE_ID, cleanup={
                           'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                           'path': f'/agent-evaluations/{run_id}', 'allowed_statuses': [200, 404],
                       })
        return run_id


async def _wait_terminal(identity, run_id) -> dict:
    deadline = time.monotonic() + _POLL_DEADLINE
    while True:
        # Poll intervals can coincide with the server's idle keep-alive limit.
        # Each read uses a fresh connection; HTTP errors remain test failures.
        async with client('config', token=identity.access_token) as api:
            fetched = await api.get('/agent-evaluations/' + str(run_id))
        assert_status(fetched, 200)
        run = _data(fetched)
        status = run.get('status')
        if status in _TERMINAL:
            return run
        if time.monotonic() > deadline:
            raise TimeoutError('evaluation run never reached a terminal state: last=' + str(status))
        await asyncio.sleep(_POLL_INTERVAL)


async def _fetch_cases(identity, run_id) -> list[dict]:
    async with client('config', token=identity.access_token) as api:
        fetched = await api.get('/agent-evaluations/' + str(run_id) + '/cases', params={'limit': 200})
        assert_status(fetched, 200)
        data = _data(fetched)
        if isinstance(data, dict):
            return data.get('items') or []
        return data if isinstance(data, list) else []


async def _fetch_stats(identity, run_id) -> dict:
    async with client('config', token=identity.access_token) as api:
        fetched = await api.get('/agent-evaluations/' + str(run_id) + '/stats')
        assert_status(fetched, 200)
        return _data(fetched)


async def _cleanup(identity, run_id=None, set_id=None, evaluator_ids=()) -> None:
    async with client('config', token=identity.access_token) as api:
        if run_id is not None:
            try:
                deleted = await api.delete('/agent-evaluations/' + str(run_id))
                if deleted.status_code in (200, 404):
                    mark_asset_state('owned_evaluation_runs', str(run_id), 'DELETED')
            except Exception:
                pass
        if set_id is not None:
            try:
                deleted = await api.delete('/evaluation-sets/' + str(set_id))
                if deleted.status_code in (200, 404):
                    mark_asset_state('owned_evaluation_sets', str(set_id), 'DELETED')
            except Exception:
                pass
        # A set can retain evaluator references. The registry performs the
        # authoritative retry and partial-run recovery after this best-effort
        # cleanup, so never delete evaluators before the owned set.
        for eid in evaluator_ids:
            try:
                deleted = await api.delete('/evaluators/' + str(eid))
                if deleted.status_code in (200, 404):
                    mark_asset_state('owned_evaluators', str(eid), 'DELETED')
            except Exception:
                pass


async def _scenario_parallel_scoring(identity, agent_id, agent_version_no, judge_model_id, cases) -> None:
    names = ['eval-' + _RUN_ID + '-a', 'eval-' + _RUN_ID + '-b']
    evaluator_ids = []
    set_id = None
    run_id = None
    try:
        for name in names:
            evaluator_ids.append(await _create_evaluator(identity, name, 'llm', prompt=_LLM_EVALUATOR_PROMPT))
        assert evaluator_ids[0] != evaluator_ids[1]
        set_id = await _create_evaluation_set(identity, 'agt-' + _RUN_ID + '-scoring', cases)
        run_id = await _create_run(identity, agent_id, agent_version_no, judge_model_id, set_id, evaluator_ids)
        run = await _wait_terminal(identity, run_id)
        assert run.get('status') == 'COMPLETED', 'main run should complete: ' + str(run.get('error_message'))

        items = await _fetch_cases(identity, run_id)
        assert items, 'evaluation run produced no case rows'
        expected = set(names)
        for item in items:
            score = item.get('score')
            assert isinstance(score, dict), 'per-case score must be keyed by evaluator name: ' + repr(score)
            assert expected.issubset(set(score)), 'missing evaluator scores: ' + repr(score)
            reasons = _parse_reason(item.get('reason'))
            assert expected.issubset(set(reasons)), 'missing evaluator reasons: ' + repr(item.get('reason'))
            for name in names:
                assert isinstance(score.get(name), (int, float)), name + ' score is not numeric'
                assert isinstance(reasons.get(name), str) and reasons.get(name).strip(), name + ' reason is not a non-empty string'

        stats = await _fetch_stats(identity, run_id)
        stat_names = {row.get('name') for row in (stats.get('per_evaluator') or [])}
        assert expected.issubset(stat_names), 'stats do not cover every evaluator: ' + repr(stat_names)
    finally:
        await _cleanup(identity, run_id=run_id, set_id=set_id, evaluator_ids=evaluator_ids)


async def _scenario_failure_isolation(identity, agent_id, agent_version_no, judge_model_id, cases) -> None:
    good_name = 'eval-' + _RUN_ID + '-good'
    poison_name = 'eval-' + _RUN_ID + '-poison'
    evaluator_ids = []
    set_id = None
    run_id = None
    try:
        good_id = await _create_evaluator(identity, good_name, 'llm', prompt=_LLM_EVALUATOR_PROMPT)
        poison_id = await _create_evaluator(identity, poison_name, 'code', code=_POISON_CODE)
        evaluator_ids = [good_id, poison_id]
        set_id = await _create_evaluation_set(identity, 'agt-' + _RUN_ID + '-isolation', cases)
        run_id = await _create_run(identity, agent_id, agent_version_no, judge_model_id, set_id, evaluator_ids)
        run = await _wait_terminal(identity, run_id)
        assert run.get('status') == 'COMPLETED', 'isolation run should not be interrupted by one evaluator failure: ' + repr(run)

        items = await _fetch_cases(identity, run_id)
        assert items, 'isolation run produced no case rows'
        for item in items:
            score = item.get('score')
            assert isinstance(score, dict), 'per-case score must be keyed by evaluator name: ' + repr(score)
            assert poison_name in score, 'poison evaluator missing from score: ' + repr(score)
            assert float(score.get(poison_name)) == 0.0, 'poison evaluator should be isolated to 0.0: ' + repr(score)
            assert good_name in score, 'surviving evaluator missing from score: ' + repr(score)
            assert isinstance(score.get(good_name), (int, float)), 'surviving evaluator score is not numeric'
            reasons = _parse_reason(item.get('reason'))
            poison_reason = str(reasons.get(poison_name) or '')
            assert poison_reason, 'poison evaluator should carry a failure reason'
            lowered = poison_reason.lower()
            assert 'error' in lowered or 'exception' in lowered or 'raise' in lowered, 'poison reason does not explain failure: ' + poison_reason
            good_reason = reasons.get(good_name)
            assert isinstance(good_reason, str), 'surviving evaluator reason must be a string'
    finally:
        await _cleanup(identity, run_id=run_id, set_id=set_id, evaluator_ids=evaluator_ids)


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage(STAGE)
async def test_multi_llm_evaluator_parallel_scoring_and_failure_isolation(tenant_a_admin) -> None:
    identity = tenant_a_admin
    inputs = _asset('inputs')
    if not isinstance(inputs, dict):
        raise AssertionError('evaluation.inputs asset must be a mapping: ' + repr(inputs))
    agent_id = int(inputs['agent_id'])
    judge_model_id = int(inputs['judge_model_id'])
    agent_version_no = inputs.get('agent_version_no')
    assert agent_id > 0 and judge_model_id > 0

    cases = _load_cases(inputs)
    await _scenario_parallel_scoring(identity, agent_id, agent_version_no, judge_model_id, cases)
    await _scenario_failure_isolation(identity, agent_id, agent_version_no, judge_model_id, cases)
