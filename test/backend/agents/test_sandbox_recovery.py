# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from dataclasses import asdict, replace
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox_contracts import SandboxOwner
from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal, SandboxRunRecord
from runtime.sandbox_owner import SandboxOwnerFacts
from runtime.sandbox_recovery import SandboxRuntimeRecovery


@pytest.fixture
def recovery(tmp_path):
    owner = SandboxOwner('release', 'namespace', 'runtime-a', 'uid-a', '10.0.0.1', 'old')
    journal = SandboxRunJournal(tmp_path / 'control')
    facts = SandboxOwnerFacts(journal, owner)
    facts.initialize({'pid': 123, 'start_ticks': '100', 'boot_id': 'boot', 'container_id': 'runtime-cid',
                      'container_name': 'nexent-runtime'})
    key = journal.business_key('release', 'namespace', 'tenant', 'user', 7)
    record = SandboxRunRecord('a' * 32, key, asdict(owner), 'tenant', 'user', 7, 'b' * 64, phase='ACTIVE')
    record.associations['assistant_message_id'] = 19
    journal.publish(record)
    coordinator = Mock(owner=replace(owner, pod_uid='uid-b', pod_name='runtime-b', epoch='new'), journal=journal)
    observer, api, fail = Mock(), Mock(), Mock(return_value={'conversation_messages': 1})
    engine = SandboxRuntimeRecovery(coordinator, lambda: nullcontext(api), observer, fail,
                                    workspace_root=tmp_path / 'work')
    return engine, record, facts, observer, api, fail


def test_live_owner_is_preserved_without_database_or_resource_mutations(recovery):
    engine, record, facts, observer, api, fail = recovery
    observer.process_stopped.return_value = False
    result = engine.recover()
    assert result['recovered_runs'] == 0
    assert not result['restart_confirmed']
    fail.assert_not_called()
    api.delete_namespaced_pod.assert_not_called()
    assert engine.journal.read_run(record.run_id).phase == 'ACTIVE'


def test_proved_dead_unused_owner_recovers_only_exact_associations(recovery):
    engine, record, facts, observer, api, fail = recovery
    observer.process_stopped.return_value = True
    result = engine.recover()
    assert result['recovered_runs'] == 1
    assert result['restart_confirmed']
    kwargs = fail.call_args.kwargs
    assert kwargs['assistant_message_id'] == 19
    assert kwargs['tenant_id'] == 'tenant' and kwargs['conversation_id'] == 7
    assert kwargs['evaluation_batch'] is False
    assert engine.journal.read_run(record.run_id).phase == 'TERMINAL'
    api.delete_namespaced_pod.assert_not_called()
    assert engine.recover()['recovered_runs'] == 0


def test_current_owner_never_recovers_itself_even_if_observer_is_wrong(recovery):
    engine, record, facts, observer, api, fail = recovery
    engine.coordinator.owner = facts.owner
    observer.process_stopped.return_value = True
    result = engine.recover()
    assert result['recovered_runs'] == 0
    assert not result['restart_confirmed']
    fail.assert_not_called()


def test_stopped_epoch_does_not_confirm_restart_while_peer_is_active(recovery):
    engine, _, facts, observer, _, _ = recovery
    peer = SandboxOwnerFacts(engine.journal, replace(facts.owner, pod_uid='uid-c', pod_name='runtime-c'))
    peer.initialize(facts.read(facts.owner.epoch)['process'])
    observer.process_stopped.side_effect = lambda fact: fact['owner']['pod_uid'] == facts.owner.pod_uid

    result = engine.recover()

    assert result['recovered_runs'] == 1
    assert not result['restart_confirmed']
    assert peer.read(peer.owner.epoch)['process_stopped_at'] is None


def test_new_epoch_same_pod_is_blocked_by_another_live_process(recovery):
    engine, record, facts, observer, api, fail = recovery
    engine.coordinator.owner = replace(facts.owner, epoch='new')
    observer.process_stopped.return_value = False
    with pytest.raises(SandboxCoordinationUnknown):
        engine.recover(startup=True)
    fail.assert_not_called()


def test_missing_ready_sandbox_never_proves_execution_stopped(recovery):
    from kubernetes.client.exceptions import ApiException
    from nexent.core.agents.sandbox_contracts import SystemSandboxProfile

    engine, record, facts, observer, api, fail = recovery
    facts.creation_intent(facts.owner, SystemSandboxProfile('image:tag', 'claim'), 'sandbox-name')
    facts.observe_pod(facts.owner, 'sandbox-uid', 'sandbox-cid', ready=True)
    observer.process_stopped.return_value = True
    api.read_namespaced_pod.side_effect = ApiException(status=404)
    assert engine.recover()['recovered_runs'] == 0
    fail.assert_not_called()
    assert engine.journal.read_run(record.run_id).phase == 'ACTIVE'


def test_database_failure_keeps_protected_active_marker(recovery):
    engine, record, facts, observer, api, fail = recovery
    observer.process_stopped.return_value = True
    fail.side_effect = RuntimeError('database offline')
    assert engine.recover()['recovered_runs'] == 0
    assert engine.journal.read_current(record.business_key).phase == 'ACTIVE'


def test_startup_rejects_existing_old_pod_without_a_protected_owner_fact(recovery):
    engine, record, facts, observer, api, fail = recovery
    api.read_namespaced_pod.return_value = {'metadata': {'uid': 'unassociated-old-pod'}}
    with pytest.raises(SandboxCoordinationUnknown, match='safely reconciled'):
        engine.verify_current_owner_resources_absent(0)
    api.delete_namespaced_pod.assert_not_called()


def test_startup_requires_both_pod_and_service_absence(recovery):
    from kubernetes.client.exceptions import ApiException

    engine, record, facts, observer, api, fail = recovery
    api.read_namespaced_pod.side_effect = ApiException(status=404)
    with pytest.raises(SandboxCoordinationUnknown, match='Service'):
        engine.verify_current_owner_resources_absent(0)
    api.read_namespaced_service.side_effect = ApiException(status=404)
    engine.verify_current_owner_resources_absent(0)


def test_retired_resource_still_retries_exact_service_cleanup(recovery):
    from nexent.core.agents.sandbox_contracts import SystemSandboxProfile

    engine, record, facts, observer, api, fail = recovery
    profile = SystemSandboxProfile('image:tag', 'claim')
    facts.creation_intent(facts.owner, profile, 'sandbox-name')
    facts.observe_pod(facts.owner, 'sandbox-uid', 'sandbox-cid', ready=True)
    facts.terminated(facts.owner, 'sandbox-uid')
    api.read_namespaced_service.return_value = {'metadata': {'name': 'sandbox-name', 'uid': 'service-uid',
        'annotations': {'nexent.ai/epoch': facts.owner.epoch, 'nexent.ai/profile': profile.fingerprint},
        'ownerReferences': [{'kind': 'Pod', 'name': facts.owner.pod_name, 'uid': facts.owner.pod_uid}]}}
    observer.process_stopped.return_value = True
    assert engine.recover()['recovered_runs'] == 1
    api.read_namespaced_pod.assert_not_called()
    assert api.delete_namespaced_service.call_args.kwargs['body'] == {'preconditions': {'uid': 'service-uid'}}


def declared_resource(facts, *, observed=True):
    from nexent.core.agents.sandbox_contracts import SystemSandboxProfile

    profile = SystemSandboxProfile('image:tag', 'claim')
    facts.creation_intent(facts.owner, profile, 'sandbox-name')
    if observed:
        facts.observe_pod(facts.owner, 'sandbox-uid', 'sandbox-cid', ready=True)
    return {'metadata': {'name': 'sandbox-name', 'uid': 'sandbox-uid',
        'annotations': {'nexent.ai/epoch': facts.owner.epoch, 'nexent.ai/profile': profile.fingerprint},
        'ownerReferences': [{'kind': 'Pod', 'name': facts.owner.pod_name, 'uid': facts.owner.pod_uid}]}}


@pytest.mark.parametrize('observed', [False, True])
@pytest.mark.parametrize('terminated', [False, True])
def test_resource_retirement_waits_for_exact_termination_before_service_delete(recovery, monkeypatch, observed, terminated):
    import time
    from kubernetes.client.exceptions import ApiException
    import runtime.sandbox_recovery as module

    engine, record, facts, observer, api, fail = recovery
    api.read_namespaced_pod.return_value = declared_resource(facts, observed=observed)
    api.read_namespaced_service.side_effect = ApiException(status=404)
    wait = Mock(return_value=terminated)
    monkeypatch.setattr(module, 'wait_for_sandbox_termination', wait)
    assert engine._retire_resource(facts, facts.read(facts.owner.epoch), time.monotonic() + 10) is terminated
    assert api.delete_namespaced_pod.call_args.kwargs['body']['preconditions'] == {'uid': 'sandbox-uid'}
    assert facts.read(facts.owner.epoch)['resource_state'] == ('TERMINATED' if terminated else 'READY' if observed else 'BOUND')
    assert api.read_namespaced_service.call_count == int(terminated)


@pytest.mark.parametrize('conflict', ['uid', 'name', 'epoch', 'profile', 'owner'])
def test_resource_conflict_never_deletes_or_fails_business(recovery, conflict):
    import time
    engine, record, facts, observer, api, fail = recovery
    pod = declared_resource(facts)
    if conflict in {'uid', 'name'}:
        pod['metadata'][conflict] = 'foreign'
    elif conflict == 'owner':
        pod['metadata']['ownerReferences'][0]['uid'] = 'foreign'
    else:
        pod['metadata']['annotations']['nexent.ai/' + conflict] = 'foreign'
    api.read_namespaced_pod.return_value = pod
    with pytest.raises(SandboxCoordinationUnknown):
        engine._retire_resource(facts, facts.read(facts.owner.epoch), time.monotonic() + 10)
    api.delete_namespaced_pod.assert_not_called()
    fail.assert_not_called()


def test_expired_retirement_deadline_preserves_resource(recovery):
    engine, record, facts, observer, api, fail = recovery
    api.read_namespaced_pod.return_value = declared_resource(facts)
    assert not engine._retire_resource(facts, facts.read(facts.owner.epoch), 0)
    api.delete_namespaced_pod.assert_not_called()


def test_recovery_cleanup_is_exact_and_preserves_peer_workspace(recovery):
    from runtime.sandbox_workspace import KubernetesWorkspace

    engine, record, facts, observer, api, fail = recovery
    assert not engine._cleanup_workspace(record)
    actual = KubernetesWorkspace(engine.workspace_root, facts.owner, execution_gid=1000).run_path(
        record.tenant_id, record.user_id, record.run_id)
    record.workspace_path = str(actual.parent / 'wrong')
    with pytest.raises(SandboxCoordinationUnknown, match='protected business identity'):
        engine._cleanup_workspace(record)
    record.workspace_path = str(actual)
    assert not engine._cleanup_workspace(record)
    actual.parent.mkdir(parents=True)
    actual.write_text('not a directory')
    with pytest.raises(SandboxCoordinationUnknown, match='not a directory'):
        engine._cleanup_workspace(record)
    actual.unlink()
    actual.mkdir()
    (actual / 'output').write_text('owned')
    peer = actual.with_name('peer')
    peer.mkdir()
    (peer / 'keep').write_text('PEER_KEEP')
    assert engine._cleanup_workspace(record)
    assert not actual.exists() and (peer / 'keep').read_text() == 'PEER_KEEP'


def test_terminal_collection_keeps_newer_current_pointer_and_owner_evidence(recovery):
    import time
    engine, record, facts, observer, api, fail = recovery
    record.phase, record.updated_at = 'TERMINAL', 0
    engine.journal.write_run(record)
    newer = replace(record, run_id='c' * 32, phase='ACTIVE')
    engine.journal.publish(newer)
    engine.retention_seconds = 0
    engine._collect_terminal(record)
    assert engine.journal.read_run(record.run_id) is None
    assert engine.journal.read_current(record.business_key).run_id == newer.run_id
    facts.record_process_stopped()
    engine._collect_owner_facts([facts], time.monotonic() + 10)
    assert facts.read(facts.owner.epoch) is not None
    (engine.journal.root / 'runs' / (newer.run_id + '.json')).unlink()
    engine._collect_owner_facts([facts], time.monotonic() + 10)
    assert facts.read(facts.owner.epoch) is None


def test_recent_terminal_run_is_retained_and_active_run_cannot_be_collected(recovery):
    engine, record, facts, observer, api, fail = recovery
    engine._collect_terminal(record)
    assert engine.journal.read_run(record.run_id).phase == 'ACTIVE'
    record.phase = 'TERMINAL'
    engine.journal.write_run(record)
    engine._collect_terminal(record)
    assert engine.journal.read_run(record.run_id) is not None


def test_corrupt_association_keeps_owner_fact_for_manual_reconciliation(recovery):
    import time
    engine, record, facts, observer, api, fail = recovery
    path = engine.journal.root / 'runs' / (record.run_id + '.json')
    path.write_text('{broken')
    facts.record_process_stopped()
    engine.retention_seconds = 0
    engine._collect_owner_facts([facts], time.monotonic() + 10)
    assert facts.read(facts.owner.epoch) is not None
    assert engine.recover()['recovered_runs'] == 0
    fail.assert_not_called()


def test_startup_does_not_probe_another_replica_or_accept_unbounded_deadline(recovery):
    engine, record, facts, observer, api, fail = recovery
    assert engine.recover(startup=True)['recovered_runs'] == 0
    observer.process_stopped.assert_not_called()
    engine.coordinator.owner = replace(facts.owner, epoch='new')
    with pytest.raises(SandboxCoordinationUnknown, match='deadline exceeded'):
        engine.recover(startup=True, deadline=0)
    assert engine.recover(deadline=0)['recovered_runs'] == 0


def test_recovery_loop_survives_transient_failure_and_stops_on_event(recovery, monkeypatch):
    engine, *_ = recovery
    event = Mock()
    event.wait.side_effect = [False, False, True]
    recover = Mock(side_effect=[OSError('API unavailable'), {}])
    monkeypatch.setattr(engine, 'recover', recover)
    engine.recovery_loop(event)
    assert recover.call_count == 2
