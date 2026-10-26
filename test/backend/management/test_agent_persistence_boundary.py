# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-ARB-004: retain assistant batch commit and failure ordering."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.services.agent.persistence import finalize_assistant_projection


async def invoke(_lane, _spec, fn, *args, **kwargs):
    return fn(*args, **kwargs)


def parameters():
    return dict(
        thread_manager=SimpleNamespace(run=invoke),
        message_id=42,
        conversation_id=7,
        terminal_status="completed",
        buffered_units=[
            {
                "type": "final_answer",
                "unit_content": "",
                "_content_fragments": ["ans", "wer"],
                "_attempt_id": "a",
            }
        ],
        buffered_search_records=[],
        buffered_image_urls=[],
        frontend_skill_files=[],
        buffered_automation_proposals=[],
        user_id="u",
        tenant_id="t",
        final_answer_content="",
        run_outcome=SimpleNamespace(attempt_outcome="completed"),
        persist_batch=Mock(),
        mark_failed=Mock(),
        logger=Mock(),
    )


@pytest.mark.asyncio
async def test_batch_projection_preserves_transaction_arguments_and_canonical_answer():
    values = parameters()
    status, failed, answer = await finalize_assistant_projection(**values)
    assert (status, failed, answer) == ("completed", False, "answer")
    values["persist_batch"].assert_called_once()
    call = values["persist_batch"].call_args.kwargs
    assert call["message_id"] == 42 and call["conversation_id"] == 7
    assert (call["user_id"], call["tenant_id"]) == ("u", "t")
    assert call["message_content"] == "answer"
    assert "_attempt_id" not in call["message_units"][0]
    values["mark_failed"].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_fails", [False, True])
async def test_batch_failure_marks_outcome_before_status_fallback(fallback_fails):
    values = parameters()
    values["persist_batch"].side_effect = RuntimeError("controlled batch failure")

    def mark(*args):
        assert values["run_outcome"].attempt_outcome == "failed"
        assert args == (42, "failed", "u")
        if fallback_fails:
            raise RuntimeError("controlled fallback failure")

    values["mark_failed"].side_effect = mark
    status, failed, answer = await finalize_assistant_projection(**values)
    assert (status, failed, answer) == ("failed", True, "answer")
    values["persist_batch"].assert_called_once()
    values["mark_failed"].assert_called_once()
    assert values["logger"].exception.call_count == (2 if fallback_fails else 1)


@pytest.mark.asyncio
async def test_missing_message_has_no_persistence_side_effect():
    values = parameters()
    values.update(message_id=None, final_answer_content="existing")
    assert await finalize_assistant_projection(**values) == (
        "completed",
        False,
        "existing",
    )
    values["persist_batch"].assert_not_called()
    values["mark_failed"].assert_not_called()
    assert values["run_outcome"].attempt_outcome == "completed"
