# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private history source kinds cannot impersonate units or untyped coverage."""

import pytest
from pydantic import ValidationError
from contracts.agentos import (
    PreparedExecutionSource,
    PreparedHistoryTurn,
    StructuredHistoryProof,
)


def test_sc009_user_source_is_separate_from_actual_native_and_execution_units():
    user = PreparedExecutionSource(
        message_id=1, unit_index=None, record_type="user_message", content="original"
    )
    native = PreparedExecutionSource(
        message_id=2,
        unit_index=3,
        record_type="tool_result",
        tool_call_id="local",
        content="event",
    )
    legacy = PreparedExecutionSource(message_id=2, unit_index=4, content="legacy event")
    assert (
        user.unit_index is None
        and native.tool_call_id == "local"
        and legacy.record_type == "execution_result"
    )
    turn = PreparedHistoryTurn(
        user_message="annotated",
        user_source_content="original",
        assistant_final_answer="answer",
        user_message_id=1,
        assistant_message_id=2,
    )
    assert turn.model_dump()["user_source_content"] == "original"


@pytest.mark.parametrize(
    "data",
    [
        {"record_type": "user_message", "unit_index": 0},
        {"record_type": "user_message", "tool_call_id": "fake-unit"},
        {"record_type": "tool_result", "unit_index": 0},
        {"record_type": "execution_result", "unit_index": None},
        {"record_type": "user_message", "message_id": True},
    ],
)
def test_sc009_source_kind_requires_its_real_provenance(data):
    with pytest.raises(ValidationError):
        PreparedExecutionSource.model_validate(
            {"message_id": 1, "content": "original", **data}
        )


def test_sc006_proof_roundtrip_and_integer_types():
    proof = {
        "source_kind": "user_message",
        "source_ref": "message:1/user-message",
        "source_sha256": "a" * 64,
        "sha256": "b" * 64,
        "part": 0,
        "json_path": "/rows",
        "row_count": 2,
    }
    assert StructuredHistoryProof.model_validate(proof).model_dump() == proof
    with pytest.raises(ValidationError):
        StructuredHistoryProof.model_validate({**proof, "row_count": True})
    with pytest.raises(ValidationError):
        StructuredHistoryProof.model_validate({**proof, "part": 0.0})
