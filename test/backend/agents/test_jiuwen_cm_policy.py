# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The saved CM checkbox is authoritative at Agent policy precedence."""

import pytest
from management.services.agent.preparation.compiler import build_agent_context_policy
from nexent.core.agents.context.policy import resolve_policy


@pytest.mark.parametrize("enabled", [False, True])
def test_saved_switch_overrides_tenant_and_stale_agent_mode(enabled):
    opposite = "passthrough" if enabled else "adaptive_compact"
    layers = build_agent_context_policy(enabled, {"processing_mode": opposite}, {"processing_mode": opposite})
    assert resolve_policy(layers).processing_mode.value == ("adaptive_compact" if enabled else "passthrough")


def test_explicit_request_policy_keeps_existing_highest_precedence():
    layers = build_agent_context_policy(True, request_policy={"processing_mode": "passthrough"})
    assert resolve_policy(layers).processing_mode.value == "passthrough"
