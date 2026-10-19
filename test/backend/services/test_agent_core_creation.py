"""Regression coverage for the Agent creation context policy contract."""

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from consts.model import AgentInfoRequest
from management.services.agent import service


@pytest.fixture
def create_boundary(monkeypatch):
    monkeypatch.setattr(service, "get_current_user_info", lambda _: ("user", "tenant", "DEV"))
    monkeypatch.setattr(service, "get_prompt_template_summary", lambda **_: (0, "system_default"))
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
    payload = {"name": "context-test", "display_name": "Context test", "agent_core": core}
    if flag is not None:
        payload["enable_context_manager"] = flag
    result = await service.update_agent_info_impl(AgentInfoRequest(**payload), "Bearer test")
    assert result["agent_id"] == 42
    config = create_boundary.call_args.kwargs["agent_info"]
    assert config["enable_context_manager"] is expected
    assert config["agent_core"] == core


@pytest.mark.asyncio
async def test_create_database_failure_is_not_reported_as_success(create_boundary):
    create_boundary.side_effect = RuntimeError("database unavailable")
    with pytest.raises(ValueError, match="database unavailable"):
        await service.update_agent_info_impl(
            AgentInfoRequest(name="test", display_name="Test", agent_core="jiuwen", enable_context_manager=False), "Bearer test"
        )


def test_unknown_core_is_rejected_before_creation(create_boundary):
    with pytest.raises(ValidationError):
        AgentInfoRequest(agent_core="unknown")
    create_boundary.assert_not_called()
