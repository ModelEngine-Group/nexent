# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for agent execution constants."""

from contracts.constants.constants import SAFE_AGENT_STREAM_ERROR_MESSAGE


def test_safe_agent_stream_error_message_is_stable_and_non_empty():
    assert SAFE_AGENT_STREAM_ERROR_MESSAGE == "Agent execution failed. Please try again later."

