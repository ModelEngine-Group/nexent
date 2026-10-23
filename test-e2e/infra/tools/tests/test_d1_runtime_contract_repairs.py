"""Controlled mutations prove the repaired formal D1 assertions reject regressions.

Run as an infrastructure test with pytest --noconftest. These are not new
registered Cases and never change product files or live Redis/services.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[4]
for source in (REPO / 'backend', REPO / 'sdk'):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


def _load_case(case_id):
    name = 'contract_probe_' + case_id.replace('-', '_')
    spec = importlib.util.spec_from_file_location(name, REPO / 'test-e2e' / 'cases' / case_id / 'test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime_case(monkeypatch):
    case = _load_case('UT-BE-AUTO-2862BAF58D3E695E')
    client = case.FakeRedisClient()
    monkeypatch.setattr(case.rss, 'RUNTIME_STATE_REDIS_URL', 'redis://fake:6379/0')
    monkeypatch.setattr(case.rss, 'redis', case._FakeRedisModule(client))
    return case, case.RuntimeStateService(), client


@pytest.mark.asyncio
async def test_cancellation_lifecycle_accepts_correct_managed_and_direct_paths(runtime_case):
    case, service, client = runtime_case
    await case._check_cancellation_lifecycle(service, client)


@pytest.mark.asyncio
@pytest.mark.parametrize('defect', ['old_stop_not_cleared', 'new_stop_lost', 'foreign_state_deleted'])
async def test_cancellation_lifecycle_rejects_controlled_regressions(runtime_case, monkeypatch, defect):
    case, service, client = runtime_case
    if defect == 'new_stop_lost':
        original = service.register_run

        def broken_register(user_id, conversation_id, message_id=None):
            original(user_id, conversation_id, message_id)
            client.delete(service._cancel_key(user_id, conversation_id))

        monkeypatch.setattr(service, 'register_run', broken_register)
    else:
        original = service.reset_stream

        def broken_reset(user_id, conversation_id):
            original(user_id, conversation_id)
            if defect == 'old_stop_not_cleared':
                client.store[service._cancel_key(user_id, conversation_id)] = 'stale-stop'
            else:
                client.store.pop(service._cancel_key('other-user', conversation_id))

        monkeypatch.setattr(service, 'reset_stream', broken_reset)
    with pytest.raises(AssertionError):
        await case._check_cancellation_lifecycle(service, client)


@pytest.mark.asyncio
@pytest.mark.parametrize('defect', ['missing_model_lane', 'wrong_capacity'])
async def test_exact_northbound_policies_reject_controlled_regressions(monkeypatch, defect):
    case = _load_case('UT-BE-AUTO-A5E5C8329C318684')
    policies = case.northbound_thread_manager._policies
    if defect == 'missing_model_lane':
        monkeypatch.delitem(policies, 'model-tool-io')
    else:
        monkeypatch.setitem(policies, 'model-tool-io', replace(policies['model-tool-io'], max_workers=5))
    with pytest.raises(AssertionError):
        await case.test_thread_lifecycle_configured_policies_and_isolation(SimpleNamespace(text=''))


@pytest.mark.asyncio
async def test_model_lane_probe_rejects_swallowed_errors(monkeypatch):
    case = _load_case('UT-BE-AUTO-A5E5C8329C318684')
    manager = case.ThreadManager('mutation-probe', case.northbound_thread_manager._policies)
    original = manager.run

    async def swallowing_run(lane, spec, fn, *args, **kwargs):
        try:
            return await original(lane, spec, fn, *args, **kwargs)
        except ValueError:
            return None

    monkeypatch.setattr(manager, 'run', swallowing_run)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        await case._check_northbound_model_lane_isolation(manager)
    assert manager.state is case.ManagerState.CLOSED
    assert manager.snapshot().active_count == 0
