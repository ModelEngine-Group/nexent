"""Unknown stop IDs acknowledge cancellation without creating execution state."""
import pytest

from d3.assets import temporary_conversation
from shared.case_evidence import write_case_evidence
from shared.http import assert_status, client
from shared.resource_ids import absent_numeric_id, _assert_absent_everywhere
from shared.stop_observation import StopObservation, assert_stop_ack, owned_history

CASE_ID = 'AGT-019'


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
@pytest.mark.asyncio
async def test_agt_019(tenant_a_user):
    target = absent_numeric_id(CASE_ID)
    observer = StopObservation(tenant_a_user, CASE_ID)
    try:
        empty = observer.read(target)
        observer.record('before_missing_stop', target, empty)
        assert empty == {'run_status': None, 'stream_status': None,
                         'stream_length': 0, 'last_event_id': None}
        async with temporary_conversation(tenant_a_user, 'D3 unknown stop canary') as canary:
            async with client('runtime', token=tenant_a_user.access_token) as api:
                before = await api.get(f'/conversation/{canary}')
                assert_status(before, 200)
                owned_history(before.json(), canary)
                replies = []
                for _ in range(2):
                    response = await api.get(f'/agent/stop/{target}')
                    assert_status(response, 200)
                    assert_stop_ack(response.json())
                    replies.append(response.json())
                    state = observer.read(target)
                    observer.record('after_missing_stop', target, state)
                    assert state == empty, 'Unknown stop created runtime execution or persisted stream state'
                after = await api.get(f'/conversation/{canary}')
            assert_status(after, 200)
            owned_history(after.json(), canary)
            assert after.json() == before.json(), 'Unknown stop changed an unrelated owned conversation'
            _assert_absent_everywhere(target)
            write_case_evidence(CASE_ID + '-ack', {'replies': replies, 'canary_unchanged': True},
                                secrets=(tenant_a_user.access_token, tenant_a_user.refresh_token))
    finally:
        observer.close()
