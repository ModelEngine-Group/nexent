# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import Mock

import pytest

from nexent.core.agents.sandbox_contracts import SandboxOwner, SystemSandboxProfile
from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal
from runtime.sandbox_owner import SandboxOwnerFacts, SandboxOwnerObserver


@pytest.fixture
def facts(tmp_path):
    owner = SandboxOwner('release', 'namespace', 'runtime', 'uid', '10.0.0.1', 'epoch-old')
    store = SandboxOwnerFacts(SandboxRunJournal(tmp_path), owner)
    process = {'pid': 123, 'start_ticks': '100', 'boot_id': 'boot-a', 'container_id': 'container-a',
               'container_name': 'nexent-runtime'}
    store.initialize(process)
    return store, owner, process


def test_resource_intent_precedes_observation_and_generation_is_immutable(facts):
    store, owner, _ = facts
    assert store.read(owner.epoch)['resource_state'] == 'NOT_CREATED'
    with pytest.raises(SandboxCoordinationUnknown):
        store.observe_pod(owner, 'pod-a', 'container-a', ready=True)
    store.creation_intent(owner, SystemSandboxProfile('image:tag', 'claim'), 'sandbox-name')
    assert store.read(owner.epoch)['resource_state'] == 'CREATING'
    store.observe_pod(owner, 'pod-a')
    assert store.read(owner.epoch)['resource_state'] == 'BOUND'
    store.observe_pod(owner, 'pod-a', 'container-a', ready=True)
    assert store.read(owner.epoch)['resource_state'] == 'READY'
    with pytest.raises(SandboxCoordinationUnknown):
        store.observe_pod(owner, 'pod-b', 'container-a', ready=True)
    with pytest.raises(SandboxCoordinationUnknown):
        store.observe_pod(owner, 'pod-a', 'container-b', ready=True)


def test_retirement_requires_exact_uid_and_prevents_same_epoch_recreation(facts):
    store, owner, _ = facts
    profile = SystemSandboxProfile('image:tag', 'claim')
    store.creation_intent(owner, profile, 'sandbox-name')
    store.observe_pod(owner, 'pod-a', 'container-a', ready=True)
    with pytest.raises(SandboxCoordinationUnknown):
        store.terminated(owner, 'foreign')
    store.terminated(owner, 'pod-a')
    with pytest.raises(SandboxCoordinationUnknown):
        store.creation_intent(owner, profile, 'sandbox-name')


def test_owner_initialization_is_idempotent_and_cannot_reset_ready_facts(facts):
    store, owner, process = facts
    store.creation_intent(owner, SystemSandboxProfile('image:tag', 'claim'), 'sandbox-name')
    store.initialize(process)
    assert store.read(owner.epoch)['resource_state'] == 'CREATING'
    with pytest.raises(SandboxCoordinationUnknown):
        store.initialize({**process, 'start_ticks': '200'})


@pytest.mark.parametrize('mutation', [
    {'updated_at': float('nan')}, {'resource_state': 'READY'}, {'pod_uid': 'undeclared'},
])
def test_corrupt_owner_facts_cannot_supply_termination_or_fallback_authority(facts, mutation):
    store, owner, _ = facts
    fact = store.read(owner.epoch)
    fact.update(mutation)
    with pytest.raises(SandboxCoordinationUnknown):
        store.validate(fact)


@pytest.mark.parametrize('ticks,stopped', [('100', False), ('200', True), (FileNotFoundError(), True)])
def test_epoch_change_alone_does_not_prove_process_death(facts, mocker, ticks, stopped):
    store, owner, process = facts
    api = Mock()
    observer = SandboxOwnerObserver(lambda: nullcontext(api), replace(owner, epoch='epoch-new'), process)
    lookup = mocker.patch('runtime.sandbox_owner.process_start_ticks')
    if isinstance(ticks, Exception):
        lookup.side_effect = ticks
    else:
        lookup.return_value = ticks
    assert observer.process_stopped(store.read(owner.epoch)) is stopped
    api.read_namespaced_pod.assert_not_called()


@pytest.mark.parametrize('condition,stopped', [('404', False), ('replacement-uid', False),
                                              ('phase-failed', False), ('wrong-container', False),
                                              ('terminated', True)])
def test_only_exact_terminated_container_facts_prove_remote_owner_death(facts, condition, stopped):
    store, owner, process = facts
    api = Mock()
    observer = SandboxOwnerObserver(lambda: nullcontext(api), replace(owner, pod_uid='current-uid'), process)
    pod = {'metadata': {'uid': owner.pod_uid}, 'status': {'phase': 'Failed', 'containerStatuses': []}}
    if condition == '404':
        api.read_namespaced_pod.side_effect = RuntimeError('404')
    else:
        if condition == 'replacement-uid':
            pod['metadata']['uid'] = 'replacement'
        if condition in ('wrong-container', 'terminated'):
            pod['status']['containerStatuses'] = [{
                'name': 'nexent-runtime', 'state': {'terminated': {
                    'containerID': 'foreign' if condition == 'wrong-container' else process['container_id'],
                    'finishedAt': 'time',
                }},
            }]
        api.read_namespaced_pod.return_value = pod
    assert observer.process_stopped(store.read(owner.epoch)) is stopped
