# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pending notifications follow actual submission rounds, including legacy writes."""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from test.backend.services.test_mcp_management_service import svc_mod


@pytest.mark.asyncio
@pytest.mark.parametrize("description", [None, "Same description", "Replacement description"])
async def test_pending_update_preserves_published_record_and_delegates_review_round(
    mocker, description,
):
    record = {
        "market_id": 1, "source_mcp_id": 9, "tenant_id": "tenant", "user_id": "owner",
        "submitted_user_id": "submitter", "review_status": "pending_review",
        "submission_revision": 2, "mcp_name": "MCP", "submit_description": "Same description",
    }
    mocker.patch.object(svc_mod, "get_mcp_market_record_by_id", return_value=record)
    mocker.patch.object(svc_mod, "_get_user_role", return_value="ADMIN")
    status = mocker.patch.object(svc_mod, "update_mcp_market_status")
    mocker.patch.object(svc_mod, "update_mcp_market_record")
    mocker.patch.object(svc_mod, "_resolve_user_email", return_value="admin@example.test")
    deactivate = mocker.patch.object(svc_mod, "deactivate_notifications")
    pending = mocker.patch.object(svc_mod, "_create_mcp_pending_review_notification")
    result = mocker.patch.object(svc_mod, "create_repository_review_notification")

    review_service = ModuleType("management.services.repository.reviews")
    review_service.save_submission = MagicMock(return_value={"review_id": "41"})
    with patch.dict(sys.modules, {"management.services.repository.reviews": review_service}):
        await svc_mod.update_community_mcp_service(
            tenant_id="tenant", user_id="admin", market_id=1,
            name=None, description=None, tags=None, registry_json=None, content=description,
        )

    # The review unit of work owns notification replacement and frozen snapshots.
    args = review_service.save_submission.call_args.args
    assert args[:5] == ("mcp", 9, "tenant", "admin", "ADMIN")
    assert args[5]["content"] == (description or "")
    assert record["submit_description"] == "Same description"
    assert record["review_status"] == "pending_review"
    status.assert_not_called()
    deactivate.assert_not_called()
    pending.assert_not_called()
    result.assert_not_called()



def test_review_result_targets_actual_submitter(mocker):
    result = mocker.patch.object(svc_mod, "create_repository_review_notification")
    deactivate = mocker.patch.object(svc_mod, "deactivate_notifications")
    svc_mod._handle_mcp_review_status_notifications(
        current_status="pending_review", new_status="shared",
        record={"user_id": "author", "submitted_user_id": "submitter", "tenant_id": "tenant"},
        market_id=1, user_id="admin",
    )
    assert result.call_args.kwargs["receiver_user_id"] == "submitter"
    deactivate.assert_called_once()
