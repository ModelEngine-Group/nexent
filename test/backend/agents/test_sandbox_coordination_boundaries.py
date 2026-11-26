# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Lease-loss and publication races preserve durable exclusion and cancellation."""

from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock

import fakeredis
import pytest
from management.services.agent.replay import CompactReplay
from runtime.sandbox_coordination import SandboxRunBusy, SandboxRunCoordinator, SandboxRunLifecycle
from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal
from runtime.sandbox_stream_state import SandboxStreamState
from runtime.sandbox_workspace import KubernetesWorkspace

from nexent.core.agents.sandbox_contracts import SandboxOwner


@pytest.fixture
def coordinator(tmp_path):
    client = Mock()
    client.eval.return_value = 1
    owner = SandboxOwner('release', 'ns', 'runtime', 'uid', '10.0.0.1', 'epoch')
    return SandboxRunCoordinator(client, SandboxRunJournal(tmp_path / 'control'), owner,
                                 workspace_root=tmp_path / 'work')


@pytest.mark.parametrize('seconds', [True, 2, 3.5])
def test_invalid_lease_duration_is_rejected(coordinator, seconds):
    with pytest.raises(ValueError):
        SandboxRunCoordinator(coordinator.client, coordinator.journal, coordinator.owner, lease_seconds=seconds)


def test_existing_exact_owner_heartbeat_is_renewed_without_changing_identity(coordinator):
    coordinator.claim_owner()
    lease = coordinator._owner_lease
    coordinator.client.eval.side_effect = [0, 1]
    coordinator.claim_owner()
    assert coordinator._owner_lease == lease
    assert not coordinator.lost_coordination.is_set()
    assert coordinator.client.eval.call_args.args[-5:] == coordinator._args(lease)


@pytest.mark.parametrize('responses', [[0, 0], [OSError('offline')]])
def test_unproved_owner_claim_closes_admission(coordinator, responses):
    coordinator.client.eval.side_effect = responses
    with pytest.raises(SandboxCoordinationUnknown, match='heartbeat could not'):
        coordinator.claim_owner()
    with pytest.raises(SandboxCoordinationUnknown, match='closed'):
        coordinator.reserve('tenant', 'user', 7, 'a' * 32)


def test_redis_busy_does_not_publish_or_poison_local_coordinator(coordinator):
    coordinator.client.eval.return_value = 0
    with pytest.raises(SandboxRunBusy, match='Redis reservation'):
        coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    assert coordinator.active_count == 0
    assert not coordinator.lost_coordination.is_set()
    assert not list((coordinator.journal.root / 'current').iterdir())


@pytest.mark.parametrize('release_fails', [False, True])
def test_publication_failure_never_returns_admission(coordinator, monkeypatch, release_fails):
    monkeypatch.setattr(coordinator.journal, 'publish', Mock(side_effect=OSError('PVC unavailable')))
    coordinator.client.eval.side_effect = [1, OSError('Redis unavailable') if release_fails else 1]
    with pytest.raises(OSError, match='PVC unavailable'):
        coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    assert coordinator.active_count == 0
    assert coordinator.lost_coordination.is_set() is release_fails
    assert coordinator.client.eval.call_count == 2


def test_admission_closed_during_publication_retires_exact_unused_run(coordinator, monkeypatch):
    publish = coordinator.journal.publish
    def close_after_publish(record):
        publish(record)
        coordinator.cancel_active()
    monkeypatch.setattr(coordinator.journal, 'publish', close_after_publish)
    cancelled = Mock()
    with pytest.raises(SandboxCoordinationUnknown, match='during admission'):
        coordinator.reserve('tenant', 'user', 7, 'a' * 32, cancel=cancelled)
    assert coordinator.journal.read_run('a' * 32).phase == 'TERMINAL'
    assert coordinator.active_count == 0
    cancelled.assert_called_once()


def test_admission_closed_while_waiting_for_lock_never_claims_redis(coordinator, monkeypatch):
    @contextmanager
    def close_before_lock(key):
        coordinator.cancel_active()
        yield
    monkeypatch.setattr(coordinator.journal, 'locked', close_before_lock)
    with pytest.raises(SandboxCoordinationUnknown, match='before admission'):
        coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    coordinator.client.eval.assert_not_called()


def test_cancellation_composes_even_if_previous_handler_raises(coordinator):
    previous, current = Mock(side_effect=RuntimeError('old callback')), Mock()
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32, cancel=previous)
    coordinator.bind_cancellation(lease, current)
    coordinator.signal_lost()
    coordinator.signal_lost()
    previous.assert_called_once()
    current.assert_called_once()
    with pytest.raises(SandboxCoordinationUnknown):
        coordinator.bind_cancellation(replace(lease, token='wrong'), Mock())


def test_references_and_workspace_are_bound_to_admitted_business_identity(coordinator, tmp_path):
    assert coordinator.current_reference('tenant', 'user', 7) is None
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    coordinator.associate(lease, assistant_message_id=19, automation_run_id=42)
    reference = coordinator.reference(lease)
    assert reference == coordinator.current_reference('tenant', 'user', 7)
    assert reference.assistant_message_id == 19 and reference.automation_generation == '42'
    with pytest.raises(SandboxCoordinationUnknown, match='no admitted'):
        coordinator.record_workspace('b' * 32, tmp_path)
    with pytest.raises(SandboxCoordinationUnknown, match='does not match'):
        coordinator.record_workspace(lease.run_id, tmp_path)
    workspace = KubernetesWorkspace(coordinator.workspace_root, coordinator.owner, execution_gid=1000).run_path('tenant', 'user', lease.run_id)
    coordinator.record_workspace(lease.run_id, workspace)
    assert coordinator.journal.read_run(lease.run_id).workspace_path == str(workspace)


def test_stale_lifecycle_events_fail_closed(coordinator):
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    with pytest.raises(ValueError):
        coordinator.lifecycle(lease.run_id).begin('unregistered')
    with pytest.raises(SandboxCoordinationUnknown):
        coordinator.lifecycle('b' * 32)
    stale = SandboxRunLifecycle(coordinator, replace(lease, token='wrong'))
    with pytest.raises(SandboxCoordinationUnknown):
        stale.finish('execution')
    assert coordinator.lost_coordination.is_set()
    with pytest.raises(SandboxCoordinationUnknown):
        stale.unknown('kernel')
    assert coordinator.journal.read_run(lease.run_id).phase == 'INTENT'
    coordinator.finish(lease)
    with pytest.raises(SandboxCoordinationUnknown):
        coordinator.hold(lease, 'late')


def test_incomplete_renewal_response_cancels_once_and_retains_unknown_marker(coordinator):
    coordinator.renew_active()
    cancelled = Mock()
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32, cancel=cancelled)
    coordinator.client.pipeline.return_value.execute.return_value = []
    coordinator.renew_active()
    cancelled.assert_called_once()
    assert coordinator.journal.read_run(lease.run_id).phase == 'UNKNOWN'
    coordinator.client.eval.side_effect = OSError('offline')
    assert coordinator.finish(lease)
    assert coordinator.journal.read_run(lease.run_id).phase == 'TERMINAL'


def test_state_ttl_policy_is_immutable_and_renewal_uses_shortest_interval(coordinator, monkeypatch):
    coordinator.configure_state_ttls(3, 6, 9, 12)
    coordinator.configure_state_ttls(3, 6, 9, 12)
    with pytest.raises(ValueError, match='immutable'):
        coordinator.configure_state_ttls(4, 6, 9, 12)
    event = Mock()
    event.wait.side_effect = [False, True]
    renewal = Mock()
    monkeypatch.setattr(coordinator, 'renew_active', renewal)
    coordinator.renewal_loop(event)
    assert all(call.args == (1,) for call in event.wait.call_args_list)
    renewal.assert_called_once()


def test_owner_and_stream_ttls_are_renewed_together_and_completion_uses_retention(coordinator):
    coordinator.claim_owner()
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    coordinator.configure_state_ttls(3, 6, 9, 12)
    coordinator.activate(lease)
    pipeline = coordinator.client.pipeline.return_value
    pipeline.execute.return_value = [1, 1]
    coordinator.renew_active()
    assert pipeline.eval.call_count == 2
    renewal = pipeline.eval.call_args.args
    assert renewal[1] == 7
    assert renewal[-4:] == (3, 6, 9, 12)
    assert coordinator.finish(lease)
    retention = coordinator.client.eval.call_args.args
    assert retention[1] == 6 and retention[-2:] == (lease.run_id, 9)
    assert coordinator.active_count == 0


def test_active_lease_renews_compact_replay_until_completion(coordinator):
    coordinator.client = fakeredis.FakeRedis(decode_responses=True)
    state = SandboxStreamState(coordinator, run_ttl=30, stream_ttl=6, completed_ttl=9,
                               cancel_ttl=12, max_stream_length=100)
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    coordinator.activate(lease)
    ref = coordinator.reference(lease)
    state.reset_stream('user', 7, run_ref=ref)
    replay = CompactReplay()
    first = 'data: {"type":"final_answer","content":"first "}\n\n'
    state.append_stream_event('user', 7, first, run_ref=ref, replay_update=replay.append(first))
    checkpoint_key = state.keys(ref)[2] + ':replay'
    assert coordinator.client.expire(checkpoint_key, 1)
    coordinator.renew_active()
    assert coordinator.client.ttl(checkpoint_key) > 1

    second = 'data: {"type":"final_answer","content":"second"}\n\n'
    state.append_stream_event('user', 7, second, run_ref=ref, replay_update=replay.append(second))
    assert state.read_replay_checkpoint('user', 7, run_ref=ref)['entries'][0]['content'] == 'first second'
    assert coordinator.finish(lease)
    assert coordinator.client.ttl(checkpoint_key) > state.stream_ttl


@pytest.mark.parametrize('response', [-1, OSError('Redis unavailable')])
def test_activation_failure_preserves_unknown_marker_before_any_remote_work(coordinator, response):
    cancelled = Mock()
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32, cancel=cancelled)
    if isinstance(response, Exception):
        coordinator.client.eval.side_effect = response
    else:
        coordinator.client.eval.return_value = response
    with pytest.raises(SandboxCoordinationUnknown):
        coordinator.activate(lease)
    assert coordinator.journal.read_run(lease.run_id).phase == 'UNKNOWN'
    calls = coordinator.client.eval.call_count
    with pytest.raises(SandboxCoordinationUnknown, match='coordination is unknown'):
        coordinator.activate(lease)
    assert coordinator.client.eval.call_count == calls


def test_renewal_with_unreadable_journal_still_attempts_cancellation(coordinator, monkeypatch):
    cancelled = Mock(side_effect=RuntimeError('cancel transport unavailable'))
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32, cancel=cancelled)
    read = coordinator.journal.read_run
    monkeypatch.setattr(coordinator.journal, 'read_run', Mock(side_effect=OSError('PVC unavailable')))
    coordinator.client.pipeline.return_value.execute.return_value = [0]
    coordinator.renew_active()
    cancelled.assert_called_once()
    assert coordinator.lost_coordination.is_set()
    assert read(lease.run_id).phase == 'INTENT'
