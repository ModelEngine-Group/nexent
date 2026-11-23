# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from dataclasses import replace
from unittest.mock import Mock

import pytest
from runtime.sandbox_coordination import SandboxRunBusy, SandboxRunCoordinator
from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal

from nexent.core.agents.sandbox_contracts import SandboxOwner


@pytest.fixture
def coordinator(tmp_path):
    owner = SandboxOwner('release', 'namespace', 'runtime', 'uid', '10.0.0.1', 'epoch')
    client = Mock()
    client.eval.return_value = 1
    return SandboxRunCoordinator(client, SandboxRunJournal(tmp_path / 'control'), owner)


def test_active_marker_prevents_takeover_even_with_missing_redis_key(coordinator):
    lease = coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    coordinator.activate(lease)
    other = SandboxRunCoordinator(coordinator.client, coordinator.journal,
                                  replace(coordinator.owner, pod_uid='other', epoch='new'))
    with pytest.raises(SandboxRunBusy):
        other.reserve('tenant', 'user', 1, 'b' * 32)
    assert coordinator.client.eval.call_count == 2


def test_evaluation_parent_reservation_is_unique_across_dispatching_users(coordinator):
    owner = coordinator.reserve('tenant', 'user-a', 'evaluation:7', 'a' * 32, kind='EVALUATION')
    with pytest.raises(SandboxRunBusy):
        coordinator.reserve('tenant', 'user-b', 'evaluation:7', 'b' * 32, kind='EVALUATION')
    record = coordinator.journal.read_current(owner.business_key)
    assert record.user_id == 'user-a'
    other = coordinator.reserve('other-tenant', 'user-b', 'evaluation:7', 'c' * 32, kind='EVALUATION')
    assert other.business_key != owner.business_key


def test_business_associations_are_exact_nullable_and_immutable(coordinator):
    lease = coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    initial = coordinator.journal.read_current(lease.business_key)
    assert all(value is None for value in initial.associations.values())
    coordinator.associate(lease, assistant_message_id=23, automation_run_id=42)
    record = coordinator.journal.read_current(lease.business_key)
    assert record.associations['assistant_message_id'] == 23
    assert record.associations['automation_run_id'] == 42
    assert coordinator.client.eval.call_args.args[2:] == (
        coordinator.redis_key(lease.business_key), lease.run_id, coordinator.owner.pod_uid, coordinator.owner.epoch,
        coordinator.journal.token_hash(lease.token), "42",
    )
    assert record.associations['evaluation_id'] is None
    with pytest.raises(SandboxCoordinationUnknown, match='immutable'):
        coordinator.associate(lease, assistant_message_id=24)
    with pytest.raises(ValueError):
        coordinator.associate(lease, model_output='forbidden')


def test_redis_admission_error_is_not_a_local_fallback(coordinator):
    coordinator.client.eval.side_effect = OSError('Redis unavailable')
    with pytest.raises(SandboxCoordinationUnknown, match='Redis'):
        coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    assert coordinator.lost_coordination.is_set()
    with pytest.raises(SandboxCoordinationUnknown, match='closed'):
        coordinator.reserve('tenant', 'user', 2, 'b' * 32)
    assert coordinator.client.eval.call_count == 1


def test_activation_rechecks_token_before_remote_effects(coordinator):
    lease = coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    with pytest.raises(SandboxCoordinationUnknown):
        coordinator.activate(replace(lease, token='wrong'))
    assert coordinator.client.eval.call_count == 1
    coordinator.client.eval.return_value = 0
    with pytest.raises(SandboxCoordinationUnknown, match='lost'):
        coordinator.activate(lease)
    assert coordinator.journal.read_current(lease.business_key).phase == 'UNKNOWN'


def test_renewal_is_batched_and_lost_lease_cancels_each_affected_run(coordinator):
    first, second = Mock(), Mock()
    left = coordinator.reserve('tenant', 'user', 1, 'a' * 32, cancel=first)
    right = coordinator.reserve('tenant', 'user', 2, 'b' * 32, cancel=second)
    pipeline = coordinator.client.pipeline.return_value
    pipeline.execute.return_value = [1, 0]
    coordinator.renew_active()
    assert pipeline.eval.call_count == 2
    first.assert_not_called()
    second.assert_called_once()
    assert coordinator.journal.read_current(left.business_key).phase == 'INTENT'
    assert coordinator.journal.read_current(right.business_key).phase == 'UNKNOWN'
    assert coordinator.lost_coordination.is_set()


def test_renewal_transport_error_cancels_all_and_never_releases_for_takeover(coordinator):
    cancelled = Mock()
    lease = coordinator.reserve('tenant', 'user', 1, 'a' * 32, cancel=cancelled)
    coordinator.client.pipeline.return_value.execute.side_effect = OSError('Redis unavailable')
    coordinator.renew_active()
    cancelled.assert_called_once()
    assert coordinator.journal.read_current(lease.business_key).phase == 'UNKNOWN'


def test_finished_worker_releases_once_and_old_token_cannot_touch_new_run(coordinator):
    old = coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    assert coordinator.finish(old)
    assert not coordinator.finish(old)
    new = coordinator.reserve('tenant', 'user', 1, 'b' * 32)
    with pytest.raises(SandboxCoordinationUnknown):
        coordinator.finish(old)
    assert coordinator.journal.read_current(new.business_key).run_id == new.run_id


def test_renewal_snapshot_racing_finished_worker_does_not_cancel_it(coordinator):
    cancelled = Mock()
    lease = coordinator.reserve('tenant', 'user', 1, 'a' * 32, cancel=cancelled)
    pipeline = coordinator.client.pipeline.return_value

    def completed():
        coordinator.finish(lease)
        return [0]

    pipeline.execute.side_effect = completed
    coordinator.renew_active()
    cancelled.assert_not_called()
    assert not coordinator.lost_coordination.is_set()


def test_corrupt_marker_never_enables_new_admission(coordinator):
    lease = coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    (coordinator.journal.root / 'runs' / (lease.run_id + '.json')).write_text('{broken')
    with pytest.raises(SandboxCoordinationUnknown):
        coordinator.reserve('tenant', 'user', 1, 'b' * 32)


def test_nested_same_business_lock_is_bounded(coordinator):
    coordinator.journal.lock_timeout_seconds = 0.03
    key = 'c' * 64
    with coordinator.journal.locked(key):
        with pytest.raises(SandboxCoordinationUnknown, match='lock unavailable'):
            with coordinator.journal.locked(key):
                pytest.fail('A second lock must not be granted')


def test_outer_automation_finalization_and_worker_must_both_finish(coordinator):
    lease = coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    coordinator.hold(lease, 'automation')
    assert not coordinator.finish(lease)
    assert coordinator.journal.read_current(lease.business_key).phase == 'INTENT'
    with pytest.raises(SandboxRunBusy):
        coordinator.reserve('tenant', 'user', 1, 'b' * 32)
    assert coordinator.finish(lease, holder='automation')
    assert coordinator.journal.read_current(lease.business_key).phase == 'TERMINAL'


def test_late_renewal_result_after_new_owner_admission_is_ignored(coordinator):
    cancelled = Mock()
    old = coordinator.reserve('tenant', 'user', 1, 'a' * 32, cancel=cancelled)
    other = SandboxRunCoordinator(coordinator.client, coordinator.journal,
                                  replace(coordinator.owner, pod_uid='other', epoch='new'))

    def completed_and_replaced():
        coordinator.finish(old)
        other.reserve('tenant', 'user', 1, 'b' * 32)
        return [0]

    coordinator.client.pipeline.return_value.execute.side_effect = completed_and_replaced
    coordinator.renew_active()
    cancelled.assert_not_called()
    assert not coordinator.lost_coordination.is_set()


def test_missing_owner_heartbeat_prevents_admission_even_for_unrelated_conversation(coordinator):
    coordinator.claim_owner()
    coordinator.client.eval.return_value = -1
    with pytest.raises(SandboxCoordinationUnknown, match='heartbeat'):
        coordinator.reserve('tenant', 'user', 1, 'a' * 32)
    assert coordinator.lost_coordination.is_set()
    assert coordinator.active_count == 0


def test_owner_renewal_failure_cancels_all_locally_owned_runs(coordinator):
    coordinator.claim_owner()
    cancellations = [Mock(), Mock()]
    for index, cancel in enumerate(cancellations):
        coordinator.reserve('tenant', 'user', index, str(index + 1) * 32, cancel=cancel)
    coordinator.client.pipeline.return_value.execute.return_value = [0, 1, 1]
    coordinator.renew_active()
    assert coordinator.lost_coordination.is_set()
    for cancel in cancellations:
        cancel.assert_called_once()
