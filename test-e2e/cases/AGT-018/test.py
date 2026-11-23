"""Live stop proves convergence independently of optional acknowledgment flags."""
import pytest

from d3.assets import get_test_asset, temporary_conversation
from d3.scenarios.scenario_agent_runtime_scenarios import _stop_stream_then_stop
from shared.case_evidence import write_case_evidence
from shared.http import assert_status, client
from shared.stop_observation import StopObservation, assert_stop_ack, owned_history, conversation_total

CASE_ID = 'AGT-018'


async def stop_owned_stream(identity, observer, *, agent_id, conversation_id):
    async def before_stop(target):
        state = observer.read(target)
        observer.record('before_stop', target, state)
        assert state['run_status'] == 'running', 'Probe did not stop a registered active run'

    events, first, headers = await _stop_stream_then_stop(
        identity, payload={
            'query': 'Run the two configured children concurrently and aggregate both markers.',
            'agent_id': agent_id, 'conversation_id': conversation_id,
            'history': [], 'is_debug': conversation_id is None,
        }, stop_target=str(conversation_id) if conversation_id is not None else None,
        before_stop=before_stop,
    )
    target = str(conversation_id) if conversation_id is not None else headers['run_id']
    assert events, 'Stopped run emitted no SSE data'
    assert_stop_ack(first)
    stopped = await observer.wait_stopped(target)
    async with client('runtime', token=identity.access_token) as api:
        repeated = await api.get(f'/agent/stop/{target}')
    assert_status(repeated, 200)
    assert_stop_ack(repeated.json())
    stable = await observer.wait_stopped(target)
    assert stable == stopped, 'Repeated stop changed the finished run or appended stream data'
    write_case_evidence(CASE_ID + ('-debug-ack' if conversation_id is None else '-normal-ack'), {
        'first': first, 'repeat': repeated.json(), 'observed_events': len(events),
    }, secrets=(identity.access_token, identity.refresh_token))


async def verify_stop_mode(tenant_a_user, mode):
    observer = StopObservation(tenant_a_user, CASE_ID)
    try:
        agent_id = int(get_test_asset('agents', 'parallel_id'))
        if mode == 'normal':
            async with temporary_conversation(tenant_a_user, 'D3 owned stop') as conversation_id:
                await stop_owned_stream(tenant_a_user, observer, agent_id=agent_id, conversation_id=conversation_id)
                async with client('runtime', token=tenant_a_user.access_token) as api:
                    history = await api.get(f'/conversation/{conversation_id}')
                assert_status(history, 200)
                payload = history.json().get('data')
                write_case_evidence(CASE_ID + '-history', {'conversation_id': conversation_id, 'data': payload},
                                    secrets=(tenant_a_user.access_token, tenant_a_user.refresh_token))
                messages = owned_history(history.json(), conversation_id)['message']
                assistant = [m for m in messages if m.get('role') == 'assistant']
                assert assistant and assistant[-1].get('status') == 'stopped', 'Persisted cancellation did not finalize as stopped'
            return

        async with temporary_conversation(tenant_a_user, 'D3 debug persistence canary') as canary:
            async with client('runtime', token=tenant_a_user.access_token) as api:
                before = await api.get(f'/conversation/{canary}')
                before_list = await api.get('/conversation/list', params={
                    'today_start_ms': 0, 'week_start_ms': 0, 'offset': 0, 'limit': 100,
                })
            assert_status(before, 200)
            assert_status(before_list, 200)
            owned_history(before.json(), canary)
            before_total = conversation_total(before_list.json())
            await stop_owned_stream(tenant_a_user, observer, agent_id=agent_id, conversation_id=None)
            async with client('runtime', token=tenant_a_user.access_token) as api:
                after = await api.get(f'/conversation/{canary}')
                after_list = await api.get('/conversation/list', params={
                    'today_start_ms': 0, 'week_start_ms': 0, 'offset': 0, 'limit': 100,
                })
            assert_status(after, 200)
            assert_status(after_list, 200)
            owned_history(after.json(), canary)
            assert after.json() == before.json(), 'Debug stop modified the unrelated owned conversation'
            after_total = conversation_total(after_list.json())
            write_case_evidence(CASE_ID + '-debug-persistence', {
                'before_total': before_total, 'after_total': after_total, 'canary_unchanged': True,
            }, secrets=(tenant_a_user.access_token, tenant_a_user.refresh_token))
            assert after_total == before_total, 'Debug run persisted a new conversation'
    finally:
        observer.close()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_agt_018(tenant_a_user):
    failures = []
    for mode in ('normal', 'debug'):
        try:
            await verify_stop_mode(tenant_a_user, mode)
        except AssertionError as exc:
            failures.append(f'{mode}: {exc}')
    assert not failures, '; '.join(failures)
