# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unavailable framework identity must not become an invented parent invocation."""

import pytest
from infrastructure.observability.trajectory_identity import (
    INVOCATION,
    PARENT_INVOCATION,
    invocation_attributes,
)


@pytest.mark.parametrize("framework_id", [None, "", True, 42])
def test_agent_without_framework_identity_uses_actual_generated_record(framework_id):
    result = invocation_attributes(
        {"openinference.span.kind": "AGENT", "subagent.invocation_id": framework_id},
        {},
        "record-uuid",
    )
    assert result[INVOCATION] == "record-uuid"
    assert PARENT_INVOCATION not in result


def test_technical_span_without_known_agent_cannot_create_invocation():
    assert (
        invocation_attributes(
            {"openinference.span.kind": "CHAIN"}, {}, "technical-record"
        )
        == {}
    )
