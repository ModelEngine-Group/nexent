# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project background output from its scoped AgentOS journal into durable history."""

import json
from unittest.mock import AsyncMock

import pytest

from contracts.conversation import MessageSource
from contracts.errors.exceptions import RuntimeServiceUnavailableError
from management.services.agent import prepared_projection
from .test_agentos_conversation_projection import REFERENCE, event, response


@pytest.fixture
def save_batch(mocker):
    return mocker.patch.object(prepared_projection, "run_blocking", return_value=42)


def observer(index, kind, content, **fields):
    return event(index, "agentos_observer", json.dumps({"type": kind, "content": content, **fields}))


def terminal(index, status):
    return event(index, "agentos_terminal", json.dumps({"status": status}))


async def project(*frames):
    async def replay(request, _user, _tenant):
        offset = int(request.after_event_id.rsplit(":", 1)[1]) if request.after_event_id else 0
        return response(*frames[offset:])

    resume = AsyncMock(side_effect=replay)
    return await prepared_projection.resume_assistant_projection(
        resume, REFERENCE, "owner", "tenant",
        message_index=5, message_source=MessageSource.AUTOMATION, assistant_message_id=42,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status,include_error", [
    ("completed", False), ("completed", True), ("failed", True), ("stopped", False),
])
async def test_scoped_terminal_decides_status_and_keeps_partial_output(save_batch, status, include_error):
    frames = [observer(1, "model_output_thinking", "partial")]
    if include_error:
        frames.append(observer(2, "error", "model failed", error_code="MODEL_FAILED"))
    observer_count = len(frames)
    frames.append(terminal(observer_count + 1, status))

    result = await project(*frames)

    save_batch.assert_awaited_once()
    batch = save_batch.await_args.kwargs
    assert (result.assistant_message_id, result.status, result.chunks) == (42, status, observer_count)
    assert batch["terminal_status"] == status
    assert (batch["assistant_message_id"], batch["projection_run_id"]) == (42, REFERENCE.run_id)
    assert (batch["conversation_id"], batch["user_id"], batch["tenant_id"]) == (42, "owner", "tenant")
    assert batch["message_source"] is MessageSource.AUTOMATION
    assert [unit["unit_content"] for unit in batch["message_units"]] == (
        ["partial", "model failed"] if include_error else ["partial"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, "invalid"])
async def test_missing_or_invalid_terminal_never_commits_a_partial_batch(save_batch, status):
    frames = [observer(1, "model_output_thinking", "partial")]
    if status is not None:
        frames.append(terminal(2, status))

    with pytest.raises(RuntimeServiceUnavailableError):
        await project(*frames)

    save_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_persistence_does_not_report_terminal_success(save_batch):
    failure = RuntimeError("transaction rolled back")
    save_batch.side_effect = failure

    with pytest.raises(RuntimeError) as caught:
        await project(observer(1, "final_answer", "done"), terminal(2, "completed"))

    assert caught.value is failure
    save_batch.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,object_name", [
    ("skill_artifact", "fixture/report.csv"),
    ("file_artifact", f"workspace/others/{REFERENCE.run_id}/outputs/report.csv"),
    ("file_artifact", f"workspace/owner/{'b' * 32}/outputs/report.csv"),
])
async def test_unresolved_or_foreign_artifact_never_reaches_persistence(save_batch, kind, object_name):
    content = {"artifacts": [{"object_name": object_name}]}

    with pytest.raises(RuntimeServiceUnavailableError):
        await project(observer(1, kind, content), terminal(2, "completed"))

    save_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_artifact_persists_without_expiring_public_url(save_batch):
    object_name = f"workspace/owner/{REFERENCE.run_id}/outputs/report.csv"
    content = {"artifacts": [{
        "object_name": object_name, "file_name": "report.csv", "file_size": 5,
        "presigned_url": "temporary-url",
    }]}

    result = await project(observer(1, "file_artifact", content), terminal(2, "completed"))

    assert result.status == "completed"
    batch = save_batch.await_args.kwargs
    assert batch["message_units"] == []
    assert [file["object_name"] for file in batch["skill_files"]] == [object_name]
    assert "temporary-url" not in json.dumps(batch["skill_files"])
