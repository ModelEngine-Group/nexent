"""Extracted asset operations; scenario assertions remain in the test modules."""
from __future__ import annotations
from shared.http import assert_status, client
from uuid import uuid4

def _data(response):
    return response.json().get("data")


async def _create_set(identity, *, name_prefix: str = "d3-eval") -> int:
    async with client("config", token=identity.access_token) as api:
        response = await api.post(
            "/evaluation-sets",
            json={"name": f"{name_prefix}-{uuid4().hex[:8]}", "description": "D3 isolated evaluation set"},
        )
    assert_status(response, 200)
    body = _data(response) or {}
    set_id = body.get("evaluation_set_id") or body.get("id")
    if not set_id:
        raise AssertionError(f"evaluation-set creation omitted id: {response.text}")
    from shared.asset_registry import runtime_dir
    from shared.factories.ownership import register_owned_http
    if runtime_dir() is not None:
        register_owned_http(identity,'owned_evaluation_sets',set_id,f'/evaluation-sets/{set_id}')
    return int(set_id)


async def _delete_set(identity, set_id: int) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.delete(f"/evaluation-sets/{set_id}")
    assert_status(response, (200, 404))
    from shared.asset_registry import mark_asset_state
    mark_asset_state('owned_evaluation_sets',str(set_id),'DELETED')


async def prepare_completed_run(identity, *, owner='LOCAL-EVALUATION-PREP') -> int:
    """Create an isolated completed run, not execute AGT-059 as a prerequisite.

    Register cleanup immediately after each creation. Consumer assertions and
    dispatch/security regression assertions remain in their respective tests.
    """
    from .agent import _draft_agent
    from .readiness import wait_ready
    from d3.assets import model_id
    from shared.asset_registry import register_asset, mark_asset_state

    def cleanup(path):
        return {'service': 'config', 'identity': identity.id, 'method': 'DELETE',
                'path': path, 'allowed_statuses': [200, 404]}

    async with _draft_agent(identity, name_prefix='local-eval', retain_for_batch=True,
                            owner_case_id=owner, registry_role='evaluation_seed',
                            cleanup_identity=identity.id) as (agent_id, _):
        set_id = await _create_set(identity, name_prefix='local-evaluation')
        register_asset('evaluation', 'completed_set_id', set_id, owner_case_id=owner,
                       cleanup=cleanup(f'/evaluation-sets/{set_id}'))
        async with client('config', token=identity.access_token) as api:
            seeded = await api.post(f'/evaluation-sets/{set_id}/cases', json={
                'inputs': {'query': 'Only reply LOCAL_EVAL_OK'},
                'label': {'answer': 'LOCAL_EVAL_OK'},
            })
            assert_status(seeded, 200)
            created = await api.post('/agent-evaluations', json={
                'agent_id': agent_id, 'judge_model_id': await model_id('llm', identity),
                'evaluation_set_id': set_id, 'agent_version_no': 0,
            })
        if created.status_code != 200:
            await register_partial_runs(identity, agent_id, set_id, owner=owner)
        assert_status(created, 200)
        run_id = int((_data(created) or {})['agent_evaluation_id'])
        register_asset('evaluation', 'completed_run_id', run_id, owner_case_id=owner,
                       state='CREATING', cleanup=cleanup(f'/agent-evaluations/{run_id}'))
        async def read():
            async with client('config', token=identity.access_token) as api:
                detail = await api.get(f'/agent-evaluations/{run_id}')
            assert_status(detail, 200)
            body = _data(detail) or {}
            return str(body.get('status') or '').upper(), body
        try:
            await wait_ready(read, ready={'COMPLETED', 'SUCCEEDED', 'SUCCESS'},
                             failed={'FAILED', 'CANCELED', 'CANCELLED'},
                             section='evaluation', key='completed_run_id')
        except Exception:
            mark_asset_state('evaluation', 'completed_run_id', 'FAILED',
                             detail='isolated evaluation did not become ready')
            raise
        register_asset('evaluation', 'completed_run_id', run_id, owner_case_id=owner,
                       cleanup=cleanup(f'/agent-evaluations/{run_id}'))
        return run_id


async def prepare_evaluation_inputs(identity, *, owner='LOCAL-EVALUATION-INPUTS') -> dict:
    """Give one case its own draft Agent and judge model, without a producer test."""
    from .agent import _draft_agent
    from d3.assets import model_id
    from shared.asset_registry import register_asset

    async with _draft_agent(identity, name_prefix='local-eval-input', retain_for_batch=True,
                            owner_case_id=owner, registry_role='evaluation_input_agent',
                            cleanup_identity=identity.id) as (agent_id, _):
        inputs = {
            'agent_id': agent_id,
            'judge_model_id': await model_id('llm', identity),
            'agent_version_no': 0,
            'cases': [{'query': 'Only reply LOCAL_EVAL_OK', 'expected': 'LOCAL_EVAL_OK'}],
        }
        register_asset('evaluation', 'inputs', inputs, owner_case_id=owner)
        return inputs


async def register_partial_runs(identity, agent_id: int, set_id: int, *, owner: str):
    """Reconcile only this factory's newly created Agent AND set after an error.

    No name-prefix sweep and no global cleanup: both IDs come from this run.
    """
    from shared.asset_registry import register_asset
    async with client('config', token=identity.access_token) as api:
        listed = await api.get('/agent-evaluations', params={'agent_id':agent_id, 'limit':0})
    assert_status(listed, 200)
    rows = _data(listed)
    if not isinstance(rows, list):
        raise AssertionError('evaluation reconciliation expected a list')
    for row in rows:
        if str(row.get('evaluation_set_id')) != str(set_id) or str(row.get('agent_id')) != str(agent_id):
            continue
        run_id = int(row['agent_evaluation_id'])
        register_asset('evaluation', f'partial_run_{run_id}', run_id, owner_case_id=owner,
                       state='FAILED', cleanup={'service':'config', 'identity':identity.id,
                       'method':'DELETE', 'path':f'/agent-evaluations/{run_id}', 'allowed_statuses':[200,404]})
