# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A disappeared or replaced API object never proves sandbox execution stopped."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from kubernetes import watch as watch_module

from nexent.core.agents import sandbox_kubernetes as module


def pod(*, uid='uid', name='sandbox', identity='cid', terminated=False, previous=False):
    state = {'terminated': {'containerID': identity, 'finishedAt': 'finished'}} if terminated else {'running': {}}
    status = {'name': name, 'containerID': 'new-cid' if previous else identity,
              'state': {'running': {}} if previous else state}
    if previous:
        status['lastState'] = state
    return {'metadata': {'uid': uid, 'name': 'owned', 'resourceVersion': '123'},
            'status': {'containerStatuses': [status]}}


@pytest.mark.parametrize('condition,expected', [
    ('current', True), ('previous', True), ('replacement_uid', False),
    ('foreign_container', False), ('sidecar', False), ('running', False), ('no_identity_required', True),
])
def test_only_matching_container_termination_is_proof(condition, expected):
    actual = pod(terminated=condition != 'running', previous=condition == 'previous')
    if condition == 'replacement_uid':
        actual['metadata']['uid'] = 'replacement'
    elif condition == 'foreign_container':
        actual['status']['containerStatuses'][0]['state']['terminated']['containerID'] = 'foreign'
    elif condition == 'sidecar':
        actual['status']['containerStatuses'][0]['name'] = 'sidecar'
    assert module.sandbox_container_terminated(actual, 'uid', None if condition == 'no_identity_required' else 'cid') is expected


@pytest.mark.parametrize('event_kind', ['raw', 'object', 'deleted', 'expired', 'error'])
def test_watch_requires_positive_proof_and_always_closes_stream(monkeypatch, event_kind):
    api, watch, closed = Mock(), Mock(), Mock()
    observed = pod(terminated=True) if event_kind in {'raw', 'object'} else pod()
    event = {'type': 'DELETED' if event_kind == 'deleted' else 'MODIFIED'}
    event['raw_object' if event_kind == 'raw' else 'object'] = observed
    def events():
        try:
            if event_kind == 'error':
                raise OSError('watch disconnected')
            yield event
        finally:
            closed()
    watch.stream.return_value = events()
    monkeypatch.setattr(watch_module, 'Watch', Mock(return_value=watch))
    ticks = Mock(side_effect=[0, 11]) if event_kind == 'expired' else lambda: 0
    monkeypatch.setattr(module.time, 'monotonic', ticks)
    if event_kind == 'error':
        with pytest.raises(OSError, match='disconnected'):
            module.wait_for_sandbox_termination(api, 'namespace', pod(), 10, container_id='cid')
    else:
        assert module.wait_for_sandbox_termination(api, 'namespace', pod(), 10, container_id='cid') is (event_kind in {'raw', 'object'})
    watch.stop.assert_called_once()
    closed.assert_called_once()
    assert watch.stream.call_args.kwargs['resource_version'] == '123'
    assert watch.stream.call_args.kwargs['field_selector'] == 'metadata.name=owned'


def test_no_watch_is_started_without_time_or_observed_resource_version(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr(watch_module, 'Watch', constructor)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 10)
    assert module.wait_for_sandbox_termination(Mock(), 'ns', pod(terminated=True), 0, container_id='cid')
    assert not module.wait_for_sandbox_termination(Mock(), 'ns', pod(), 0, container_id='cid')
    missing_version = deepcopy(pod())
    del missing_version['metadata']['resourceVersion']
    assert not module.wait_for_sandbox_termination(Mock(), 'ns', missing_version, 20, container_id='cid')
    constructor.assert_not_called()
