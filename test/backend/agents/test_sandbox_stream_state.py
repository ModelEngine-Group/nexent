# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from dataclasses import replace
from unittest.mock import Mock

import pytest

from runtime.sandbox_coordination import SandboxRunReference
from runtime.sandbox_journal import SandboxCoordinationUnknown
from runtime.sandbox_stream_state import SandboxStreamState


@pytest.fixture
def state():
    coordinator = Mock()
    coordinator.redis_key.side_effect = lambda key: 'runtime:ksm:lease:' + key
    coordinator.client.eval.return_value = 1
    adapter = SandboxStreamState(coordinator, run_ttl=60, completed_ttl=20, stream_ttl=30,
                                 cancel_ttl=10, max_stream_length=100)
    ref = SandboxRunReference('a' * 32, 'b' * 64, 'tenant', 'user', 1, 'uid', 'epoch', 'c' * 64, 'ACTIVE')
    return adapter, coordinator, ref


def test_different_runs_never_share_stream_done_or_cancel_keys(state):
    adapter, _, ref = state
    old, new = adapter.keys(ref), adapter.keys(replace(ref, run_id='d' * 32))
    assert old[0] == new[0]
    assert all(left != right for left, right in zip(old[1:], new[1:]))


def test_server_write_requires_explicit_matching_identity(state):
    adapter, coordinator, ref = state
    for candidate in (None, replace(ref, user_id='other'), replace(ref, conversation_id=2)):
        with pytest.raises(SandboxCoordinationUnknown):
            adapter.append_stream_event('user', 1, 'chunk', run_ref=candidate)
    coordinator.client.eval.assert_not_called()


def test_reset_and_registration_reject_a_lost_generation(state):
    adapter, coordinator, ref = state
    coordinator.client.eval.return_value = 0
    with pytest.raises(SandboxCoordinationUnknown, match='generation'):
        adapter.reset_stream('user', 1, run_ref=ref)
    with pytest.raises(SandboxCoordinationUnknown, match='generation'):
        adapter.register_run('user', 1, run_ref=ref)


def test_redis_failure_is_visible_and_signals_lost_coordination(state):
    adapter, coordinator, ref = state
    coordinator.client.xrange.side_effect = OSError('unavailable')
    with pytest.raises(SandboxCoordinationUnknown, match='unavailable'):
        adapter.read_stream_events('user', 1, run_ref=ref)
    coordinator.signal_lost.assert_called_once()


def test_cancel_polls_are_bound_to_exact_run_value(state):
    adapter, coordinator, ref = state
    coordinator.client.get.return_value = 'other-run'
    assert not adapter.is_cancelled('user', 1, run_ref=ref)
    coordinator.client.get.return_value = ref.run_id
    assert adapter.is_cancelled('user', 1, run_ref=ref)
    coordinator.client.get.assert_called_with(adapter.keys(ref)[4])


def test_stale_append_zero_is_not_an_event_id(state):
    adapter, coordinator, ref = state
    coordinator.client.eval.return_value = 0
    assert adapter.append_stream_event('user', 1, 'late', run_ref=ref) is None


def test_expired_terminal_state_differs_from_missing_active_state(state):
    adapter, coordinator, ref = state
    coordinator.client.hgetall.return_value = {}
    with pytest.raises(SandboxCoordinationUnknown, match='missing'):
        adapter.get_run_state('user', 1, run_ref=ref)
    assert adapter.get_run_state('user', 1, run_ref=replace(ref, phase='TERMINAL')) == {}
