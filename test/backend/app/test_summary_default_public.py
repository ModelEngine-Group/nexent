# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SUM-DEFAULT-02 keep automatic summary selection and SSE semantics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from management.api.knowledge_base import knowledge_summary as module
from nexent.storage.errors import (
    Conflict,
    DeadlineExceeded,
    OperationCancelled,
    ScopeDenied,
    Unavailable,
)

from test.backend.app.test_summary_metadata_public import (
    public as public,  # noqa: PLC0414 - Re-export the shared fixture.
)


@pytest.fixture
def automatic(public, mocker):
    mocker.patch.object(
        module, "get_current_user_info", return_value=("reader", "tenant-a", "zh")
    )
    default = mocker.patch.object(module, "read_default_summary_model", return_value=7)
    generate = AsyncMock(return_value="Summary")
    mocker.patch.object(
        module,
        "KnowledgeSummaryService",
        return_value=SimpleNamespace(generate=generate),
    )
    return SimpleNamespace(client=public.client, default=default, generate=generate)


def test_default_selection_passes_actual_actor_and_keeps_stream(automatic):
    s = automatic
    response = s.client.post("/summary/kb/auto_summary?batch_size=100")
    assert response.status_code == 200 and '"completed"' in response.text
    actor = s.default.await_args.args[0]
    assert (actor.user_id, actor.tenant_id) == (
        "reader",
        "tenant-a",
    ) and s.default.await_count == 1
    s.generate.assert_awaited_once_with(
        index_name="kb",
        batch_size=100,
        user_id="reader",
        tenant_id="tenant-a",
        language="zh",
        model_id=7,
    )


@pytest.mark.parametrize("model_id", [0, 9, -2])
def test_explicit_model_skips_default_query(automatic, model_id):
    s = automatic
    s.default.side_effect = AssertionError("Default queried with explicit ID")
    assert (
        s.client.post(f"/summary/kb/auto_summary?model_id={model_id}").status_code
        == 200
    )
    s.default.assert_not_awaited()
    assert s.generate.await_args.kwargs["model_id"] == model_id


@pytest.mark.parametrize("error", [None, ValueError("invalid"), Unavailable()])
def test_missing_or_ordinary_default_read_failure_preserves_existing_none(
    automatic, error
):
    s = automatic
    s.default.return_value = None
    s.default.side_effect = error
    assert s.client.post("/summary/kb/auto_summary").status_code == 200
    assert (
        s.generate.await_args.kwargs["model_id"] is None and s.default.await_count == 1
    )


@pytest.mark.parametrize(
    "error,status",
    [
        (ScopeDenied(), 403),
        (Conflict(), 500),
        (DeadlineExceeded(), 500),
        (OperationCancelled(), 500),
    ],
)
def test_authorization_ambiguity_deadline_and_cancellation_stop_generation(
    automatic, error, status
):
    s = automatic
    s.default.side_effect = error
    response = s.client.post("/summary/kb/auto_summary")
    assert response.status_code == status
    s.generate.assert_not_awaited()
    assert s.default.await_count == 1
