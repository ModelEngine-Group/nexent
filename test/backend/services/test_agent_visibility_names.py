# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import pytest

import services.asset_owner_visibility as service
from consts.const import ASSET_OWNER_TENANT_ID


@pytest.mark.parametrize("role,expected_ids,hidden", [
    ("ADMIN", [7, 8, 9, 10], 0), ("USER", [7, 9, 10], 1),
])
def test_preview_keeps_creator_shared_and_group_agents_but_hides_private_names(
    monkeypatch, role, expected_ids, hidden,
):
    monkeypatch.setattr(service, "get_user_tenant_by_user_id", lambda _: {"user_role": role})
    monkeypatch.setattr(service, "query_group_ids_by_user", lambda _: [1])
    metadata = {
        7: {"display_name": "A creator", "created_by": "u1"},
        8: {"display_name": "B private", "created_by": "other", "group_ids": "1", "ingroup_permission": "PRIVATE"},
        9: {"display_name": "C group", "created_by": "other", "group_ids": "1", "ingroup_permission": "READ_ONLY"},
        10: {"display_name": "D shared", "tenant_id": ASSET_OWNER_TENANT_ID},
    }
    agents = service.get_visible_agent_names(metadata, user_id="u1")
    assert [agent["agent_id"] for agent in agents] == expected_ids
    assert len(metadata) - len(agents) == hidden
