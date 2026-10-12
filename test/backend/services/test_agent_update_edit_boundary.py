"""All Agent updates must enforce edit authorization before mutation."""

import pytest

from test.backend.services import test_agent_service as legacy
from consts.exceptions import AgentNotFoundError, ForbiddenError
from consts.model import AgentInfoRequest
from management.services.agent import service


@pytest.fixture
def boundary(mocker):
    mocker.patch.object(service, "get_current_user_info", return_value=("user", "tenant", "en"))
    mocker.patch.object(service, "is_system_agent", return_value=False)
    mocker.patch.object(service, "get_prompt_template_summary", return_value=(None, None))
    mocker.patch.object(service, "build_reasoning_snapshot", return_value=None)
    lookup = mocker.patch.object(service, "search_agent_info_by_agent_id", return_value={"agent_id": 1})
    permission = mocker.patch.object(service, "resolve_agent_list_permission", return_value="EDIT")
    writes = [mocker.patch.object(service, name) for name in (
        "update_agent", "update_related_agents", "create_or_update_tool_by_tool_info")]
    writes.append(mocker.patch.object(service.skill_db, "create_or_update_skill_by_skill_info"))
    external = mocker.patch.object(service.a2a_agent_db, "get_external_agent_by_id", return_value={"id": 2})
    writes.append(mocker.patch.object(service.a2a_agent_db, "add_external_agent_relation"))
    return lookup, permission, writes, external


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"name": "changed"}, {"related_agent_ids": []}, {"related_external_agent_ids": []}])
async def test_read_only_update_without_protocol_field_is_denied(boundary, payload):
    _, permission, writes, _ = boundary
    permission.return_value = "READ_ONLY"
    with pytest.raises(ForbiddenError):
        await service.update_agent_info_impl(AgentInfoRequest(agent_id=1, **payload), "token")
    for write in writes:
        write.assert_not_called()


@pytest.mark.asyncio
async def test_foreign_parent_update_is_denied(boundary):
    lookup, _, writes, _ = boundary
    lookup.side_effect = AgentNotFoundError("agent not found")
    with pytest.raises(AgentNotFoundError):
        await service.update_agent_info_impl(AgentInfoRequest(agent_id=1, name="changed"), "token")
    for write in writes:
        write.assert_not_called()


@pytest.mark.asyncio
async def test_foreign_external_selection_does_not_modify_parent(boundary):
    _, _, writes, external = boundary
    external.return_value = None
    with pytest.raises(AgentNotFoundError):
        await service.update_agent_info_impl(
            AgentInfoRequest(agent_id=1, name="changed", related_external_agent_ids=[2]), "token")
    external.assert_called_once_with(2, "tenant")
    for write in writes:
        write.assert_not_called()


@pytest.mark.asyncio
async def test_missing_reference_during_persistence_is_not_silently_accepted(boundary, mocker):
    _, _, writes, _ = boundary
    mocker.patch.object(service.a2a_agent_db, "list_external_relations_by_local_agent", return_value=[])
    writes[-1].side_effect = AgentNotFoundError("Agent not found")
    with pytest.raises(AgentNotFoundError):
        await service.update_agent_info_impl(
            AgentInfoRequest(agent_id=1, related_external_agent_ids=[2]), "token")
    writes[-1].assert_called_once_with(
        local_agent_id=1, external_agent_id=2, tenant_id="tenant", user_id="user")
