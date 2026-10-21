# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Conversation activity cursor forwarding and HTTP error conversion."""

import sys
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from test.backend.app import test_conversation_management_app as legacy


conversation_app = sys.modules[legacy.list_conversations_endpoint.__module__]


@pytest.fixture
def list_page(monkeypatch):
    monkeypatch.setattr(
        conversation_app, "get_current_user_id", lambda _authorization: ("owner", "tenant"),
    )
    query = MagicMock()
    monkeypatch.setattr(conversation_app, "get_conversation_list_page", query)
    return query


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", [None, "opaque-activity-cursor"])
async def test_list_forwards_cursor_and_owned_scope_without_changing_payload(list_page, cursor):
    page = {"items": [], "metadata": {"total": 0}, "next_cursor": None}
    list_page.return_value = page

    response = await conversation_app.list_conversations_endpoint(
        2000, 1000, authorization="Bearer token", limit=2,
        conversation_type="workbench", cursor=cursor,
    )

    assert response.code == 0 and response.message == "success" and response.data == page
    expected = {
        "user_id": "owner", "today_start_ms": 2000, "week_start_ms": 1000,
        "limit": 2, "offset": 0, "conversation_type": "workbench",
    }
    if cursor is not None:
        expected["cursor"] = cursor
    list_page.assert_called_once_with(**expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "detail, offset",
    [("Invalid conversation activity cursor", 0), ("Conversation cursor cannot be combined with offset", 1)],
)
async def test_list_converts_cursor_validation_error_to_bad_request(list_page, detail, offset):
    error = ValueError(detail)
    list_page.side_effect = error

    with pytest.raises(HTTPException) as caught:
        await conversation_app.list_conversations_endpoint(
            2000, 1000, authorization="Bearer token", limit=2, offset=offset, cursor="invalid",
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == detail
    assert caught.value.__cause__ is error
    list_page.assert_called_once_with(
        user_id="owner", today_start_ms=2000, week_start_ms=1000,
        limit=2, offset=offset, cursor="invalid",
    )
