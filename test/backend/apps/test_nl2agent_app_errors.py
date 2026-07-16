"""Tests for structured NL2AGENT API error conversion."""

from consts.error_code import ErrorCode
from consts.exceptions import (
    AgentRunException,
    Nl2AgentDraftNotFoundError,
)

from apps.nl2agent_app import _session_http_error


def test_session_error_preserves_domain_exception() -> None:
    error = Nl2AgentDraftNotFoundError()

    assert _session_http_error(error) is error


def test_session_error_converts_legacy_workflow_failure_without_message_matching() -> None:
    converted = _session_http_error(AgentRunException("A new workflow message."))

    assert converted.error_code == ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT
    assert converted.message == "A new workflow message."


def test_session_error_converts_unexpected_failure_to_internal_error() -> None:
    converted = _session_http_error(RuntimeError("database unavailable"))

    assert converted.error_code == ErrorCode.SYSTEM_INTERNAL_ERROR
    assert converted.message == "Failed to load or update NL2AGENT session state."
