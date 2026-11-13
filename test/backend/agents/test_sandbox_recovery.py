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
    assert engine.recover()['recovered_runs'] == 0
    fail.assert_not_called()
    api.delete_namespaced_pod.assert_not_called()
    assert engine.journal.read_run(record.run_id).phase == 'ACTIVE'


def test_proved_dead_unused_owner_recovers_only_exact_associations(recovery):
    engine, record, facts, observer, api, fail = recovery
    observer.process_stopped.return_value = True
    assert engine.recover()['recovered_runs'] == 1
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
    assert engine.recover()['recovered_runs'] == 0
    fail.assert_not_called()


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
