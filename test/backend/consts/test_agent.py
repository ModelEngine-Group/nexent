"""Tests for agent execution constants."""

from backend.consts.agent import SAFE_AGENT_STREAM_ERROR_MESSAGE


def test_safe_agent_stream_error_message_is_stable_and_non_empty():
    assert SAFE_AGENT_STREAM_ERROR_MESSAGE == "Agent execution failed. Please try again later."

