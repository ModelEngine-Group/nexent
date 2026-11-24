# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""MCP listing timestamps accept serialized database rows and datetime values."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from test.backend.services.test_mcp_management_service import svc_mod


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "published_at, expected",
    [
        ("2026-11-13T08:30:00Z", "2026-11-13T08:30:00Z"),
        ("2026-11-13T16:30:00+08:00", "2026-11-13T16:30:00+08:00"),
        (datetime(2026, 11, 13, 8, 30, tzinfo=timezone.utc), "2026-11-13T08:30:00+00:00"),
        (None, None),
        ("", None),
    ],
)
async def test_list_community_mcp_preserves_published_timestamp(published_at, expected):
    row = {"market_id": 7, "mcp_name": "visible-service", "review_status": "shared", "published_at": published_at}
    with patch.object(svc_mod, "_get_user_role", return_value=("ADMIN",)), \
            patch.object(svc_mod, "get_mcp_market_records", return_value={"count": 1, "total": 1, "page": 1, "items": [row]}):
        result = await svc_mod.list_community_mcp_services(
            tenant_id="tenant", user_id="viewer", page=1, limit=12
        )
    assert result["count"] == result["total"] == 1
    assert result["page"] == 1
    assert result["items"][0]["communityId"] == 7
    assert result["items"][0]["publishedAt"] == expected
