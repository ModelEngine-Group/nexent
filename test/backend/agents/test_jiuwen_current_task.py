# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep historical attachments available without reactivating them for Jiuwen."""

import pytest

from contracts.agentos import RunInput
from contracts.conversation import HistoryItem
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input
from runtime.agentos.prepared_attachments import materialize_evaluation_input


@pytest.mark.parametrize(
    "include_history,current_upload", [(False, False), (False, True), (True, False)]
)
def test_current_query_preserves_history_without_reactivating_uploads(mocker, include_history, current_upload):
    mocker.patch("infrastructure.agent_attachments.MINIO_DEFAULT_BUCKET", "nexent")
    actor = ServicePrincipal("fixture-user", "fixture-tenant")
    old_file = {"name": "old-image.png", "url": "s3://nexent/attachments/fixture-user/old-image.png"}
    new_file = {"name": "new-image.png", "url": "s3://nexent/attachments/fixture-user/new-image.png"}
    history = [
        HistoryItem(role="user", content="Analyze the original image", minio_files=[old_file]),
        HistoryItem(role="assistant", content="The image has already been analyzed"),
    ]
    raw_query = "What can you do?"
    request = build_evaluation_input(
        raw_query, [new_file] if current_upload else [], history, actor.user_id, actor.tenant_id,
    )
    query, restored, files = materialize_evaluation_input(
        RunInput.model_validate_json(request.model_dump_json()), actor, "en",
        include_history_in_query=include_history,
    )

    assert raw_query in query
    assert "old-image.png" in restored[0].content
    assert [file["name"] for file in files] == (["new-image.png", "old-image.png"] if current_upload else ["old-image.png"])
    assert ("old-image.png" in query) is include_history
    assert ("new-image.png" in query) is current_upload
    if not include_history and not current_upload:
        assert query == raw_query
