# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression coverage for the Agent creation context policy contract."""

from unittest.mock import MagicMock

import pytest

from contracts.agent import AgentInfoRequest
from contracts.authentication import AuthenticatedIdentity
from management.services.agent import service


@pytest.fixture
def create_boundary(monkeypatch):
    monkeypatch.setattr(service, "build_reasoning_snapshot", lambda **_: None)
    monkeypatch.setattr(service, "_get_user_group_ids", lambda *_: "")
    monkeypatch.setattr(service, "query_all_agent_info_by_tenant_id", lambda *_: [])
    create = MagicMock(return_value={"agent_id": 42})
    monkeypatch.setattr(service, "create_agent", create)
    return create


@pytest.mark.asyncio
@pytest.mark.parametrize("core", ["smolagents", "jiuwen"])
@pytest.mark.parametrize("flag,expected", [(None, True), (False, False), (True, True)])
async def test_create_preserves_context_manager_flag(create_boundary, core, flag, expected):
    payload = {"name": "context_test", "display_name": "Context test", "agent_core": core}
    if flag is not None:
        payload["enable_context_manager"] = flag
    result = await service.update_agent_info_impl(AgentInfoRequest(**payload), AuthenticatedIdentity("user", "tenant"))
    assert result["agent_id"] == 42
    config = create_boundary.call_args.kwargs["agent_info"]
    assert config["enable_context_manager"] is expected
    assert "agent_core" not in config


@pytest.mark.asyncio
async def test_create_database_failure_is_not_reported_as_success(create_boundary):
    create_boundary.side_effect = RuntimeError("database unavailable")
    with pytest.raises(ValueError, match="database unavailable"):
        await service.update_agent_info_impl(
            AgentInfoRequest(name="test", display_name="Test", agent_core="jiuwen", enable_context_manager=False),
            AuthenticatedIdentity("user", "tenant"),
        )


@pytest.mark.parametrize("legacy_core", ["unknown", "", "jiuwen", "smolagents"])
def test_legacy_core_input_is_ignored_before_creation(create_boundary, legacy_core):
    request = AgentInfoRequest(agent_core=legacy_core)
    assert "agent_core" not in request.model_dump()
    assert "agent_core" not in AgentInfoRequest.model_fields
    create_boundary.assert_not_called()


def test_agent_orm_has_no_core_column():
    from management.db.agent.models import AgentInfo

    assert "agent_core" not in AgentInfo.__table__.columns
