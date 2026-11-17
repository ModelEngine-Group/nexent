# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The optional lifecycle hook preserves original errors and cleanup ownership."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.agents.contracts.adapter import AgentCoreAdapter
from nexent.core.agents.orchestration.execution import execute_adapter
from test.sdk.core.agents import test_jiuwen_errors as helpers


diagnostic_adapter = helpers.adapter


@pytest.mark.parametrize(
    "phase,method", [("configuration", "validate"), ("preparation", "prepare"), ("execution", "run")]
)
def test_phase_failure_is_recorded_before_close_and_original_exception_survives(mocker, phase, method):
    calls, error = [], ValueError("private failure")
    adapter = SimpleNamespace(**{name: Mock(side_effect=lambda: None) for name in ("validate", "prepare", "run")})
    setattr(adapter, method, Mock(side_effect=error))
    adapter.record_failure = Mock(side_effect=lambda failure, **kw: calls.append((failure, kw)))
    adapter.close = Mock(side_effect=lambda: calls.append("closed"))
    mocker.patch("nexent.core.agents.factory.AgentCoreFactory.create", return_value=adapter)
    with pytest.raises(ValueError) as found:
        execute_adapter(SimpleNamespace())
    assert found.value is error
    assert calls == [(error, {"phase": phase}), "closed"]


def test_default_hook_keeps_existing_core_reporting_unchanged():
    assert AgentCoreAdapter.record_failure(object(), ValueError("private")) is None


def test_reporting_hook_cannot_mask_the_original_failure(mocker):
    original = ValueError("original private failure")
    adapter = SimpleNamespace(
        validate=Mock(side_effect=original),
        record_failure=Mock(side_effect=RuntimeError("reporting private failure")),
        close=Mock(),
    )
    mocker.patch("nexent.core.agents.factory.AgentCoreFactory.create", return_value=adapter)
    with pytest.raises(ValueError) as found:
        execute_adapter(SimpleNamespace())
    assert found.value is original
    adapter.close.assert_called_once()


def test_cleanup_error_cannot_replace_a_specific_run_failure(diagnostic_adapter, mocker):
    adapter = diagnostic_adapter
    adapter.record_failure(ConnectionRefusedError("private"), source="mcp")
    mocker.patch.object(adapter, "_close_resources", side_effect=ValueError("cleanup private"))
    with pytest.raises(ValueError):
        adapter.close()
    assert adapter.run_info.run_result.error.category == "mcp_connection_refused"
