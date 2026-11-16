# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Creator history lists combine resource-tenant, executor and owner boundaries."""

import pytest

from contracts.agent import SystemAgentRef
from management.services.conversation import creator_histories as service


@pytest.fixture
def collaborators(mocker):
    agent = mocker.patch.object(service, "query_agent_records_for_nl2agent", return_value=[{"version_no": 0, "delete_flag": "N"}])
    skill = mocker.patch.object(service, "get_skill_by_id", return_value={"skill_id": 201})
    executor = mocker.patch.object(service.system_agent_provider, "get_creator_ref", return_value=SystemAgentRef("shared", "nl2agent_main", 77, 0))
    page = mocker.patch.object(service, "get_conversation_list_page", return_value={"items": [], "metadata": {"total": 0}})
    return agent, skill, executor, page


@pytest.mark.parametrize("kind", ["agent", "skill"])
def test_history_query_scopes_target_tenant_executor_owner_and_pagination(collaborators, kind):
    agent, skill, executor, page = collaborators
    assert service.list_creator_histories(kind=kind, target_id=201, user_id="u", tenant_id="t", offset=20) == {"items": [], "total": 0}
    (agent if kind == "agent" else skill).assert_called_once_with(201, "t")
    executor.assert_called_once_with("t", f"nl2{kind}_main")
    page.assert_called_once_with(user_id="u", today_start_ms=0, week_start_ms=0,
        offset=20, limit=20, creator_agent_id=77, creator_target={"type": kind, "id": 201})


@pytest.mark.parametrize("kind,records", [("agent", []), ("agent", [{"version_no": 0, "delete_flag": "Y"}]), ("agent", [{"version_no": 1, "delete_flag": "N"}]), ("skill", None)])
def test_missing_foreign_or_deleted_target_never_queries_histories(collaborators, kind, records):
    agent, skill, executor, page = collaborators
    (agent if kind == "agent" else skill).return_value = records
    with pytest.raises(PermissionError):
        service.list_creator_histories(kind=kind, target_id=201, user_id="u", tenant_id="t")
    executor.assert_not_called()
    page.assert_not_called()


@pytest.mark.parametrize("change", [{"kind": "file"}, {"target_id": 0}, {"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_invalid_history_query_is_rejected(collaborators, change):
    values = {"kind": "agent", "target_id": 201, "user_id": "u", "tenant_id": "t", **change}
    with pytest.raises(ValueError):
        service.list_creator_histories(**values)
    collaborators[-1].assert_not_called()


@pytest.mark.parametrize("user,tenant", [("", "t"), ("u", "")])
def test_history_requires_authenticated_identity(collaborators, user, tenant):
    with pytest.raises(PermissionError):
        service.list_creator_histories(kind="agent", target_id=201, user_id=user, tenant_id=tenant)
    collaborators[0].assert_not_called()
