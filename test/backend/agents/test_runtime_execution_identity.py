# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Execution identity is internal, validated and stable across preparation retries."""

from types import SimpleNamespace

import pytest
from runtime.identity import ensure_request_run_id, resolve_execution_run_id
from runtime.workspace import create_run_workspace


def test_request_identity_is_stable_and_separate_from_public_identifiers():
    request = SimpleNamespace(conversation_id=123, _debug_run_id='debug-legacy', _runtime_automation_generation='42')
    first = ensure_request_run_id(request)
    assert len(first) == 32
    assert ensure_request_run_id(request) == first
    assert request.conversation_id == 123
    assert request._debug_run_id == 'debug-legacy'
    assert request._runtime_automation_generation == '42'
    assert resolve_execution_run_id(first) == first


def test_new_admission_gets_a_new_identity():
    request = SimpleNamespace()
    first = ensure_request_run_id(request)
    assert ensure_request_run_id(request, new=True) != first
    assert ensure_request_run_id(SimpleNamespace()) != first


@pytest.mark.parametrize('value', ['', '../bad', 'A' * 32, 'x' * 32, 'a' * 33, 123, True])
def test_untrusted_or_invalid_identity_is_rejected(value):
    with pytest.raises(ValueError, match='run_id'):
        resolve_execution_run_id(value)


def test_injected_identity_selects_the_same_workspace_on_retry(tmp_path):
    run_id = resolve_execution_run_id(None)
    first = create_run_workspace('user', resolve_execution_run_id(run_id), workspace_root=str(tmp_path))
    retry = create_run_workspace('user', resolve_execution_run_id(run_id), workspace_root=str(tmp_path))
    assert first == retry
    assert first.endswith(run_id)
