# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pending notifications follow actual submission rounds, including legacy writes."""

import pytest

from test.backend.services.test_mcp_management_service import svc_mod


@pytest.mark.asyncio
@pytest.mark.parametrize("description,replaced", [
    (None, False),
    ("Same description", False),
    ("Replacement description", True),
])
async def test_pending_status_replaces_notification_only_for_new_round(
    mocker, description, replaced,
):
    record = {
        "market_id": 1, "tenant_id": "tenant", "user_id": "owner",
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

    await svc_mod.update_community_mcp_service(
        tenant_id="tenant", user_id="admin", market_id=1,
        name=None, description=None, tags=None, registry_json=None, content=description,
    )

    assert deactivate.call_count == int(replaced)
    assert pending.call_count == int(replaced)
    assert status.call_args.kwargs["is_resubmission"] is replaced
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
