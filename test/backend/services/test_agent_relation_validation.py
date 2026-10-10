"""Reject invalid relationship selections before any configuration writes."""

import pytest

from test.backend.services import test_agent_service as legacy
from consts.exceptions import AgentNotFoundError, AgentRelationValidationError
from consts.model import AgentInfoRequest
from management.services.agent import service


@pytest.fixture
def boundary(mocker):
    mocker.patch.object(service, "get_current_user_info", return_value=("user", "tenant", "en"))
    mocker.patch.object(service, "is_system_agent", return_value=False)
    lookup = mocker.patch.object(service, "search_agent_info_by_agent_id", return_value={"agent_id": 2})
    children = mocker.patch.object(service, "query_sub_agents_id_list", return_value=[])
    writes = [mocker.patch.object(service, name) for name in (
        "create_agent", "update_agent", "update_related_agents", "create_or_update_tool_by_tool_info",
    )]
    writes.append(mocker.patch.object(service.skill_db, "create_or_update_skill_by_skill_info"))
    prompt = mocker.patch.object(service, "get_prompt_template_summary")
    return lookup, children, writes, prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"related_agent_ids": [1]},
    {"related_agent_ids": [1, 999]},
    {"related_agent_ids": [2, 2]},
    {"related_agents": [{"agent_id": 1}]},
    {"related_agents": [{"agent_id": 2}, {"agent_id": 2}]},
    {"related_agent_ids": [2], "related_agents": [{"agent_id": 3}]},
])
async def test_invalid_selection_stops_all_writes(boundary, payload):
    lookup, children, writes, prompt = boundary
    with pytest.raises(AgentRelationValidationError):
        await service.update_agent_info_impl(AgentInfoRequest(agent_id=1, name="changed", **payload), "token")
    for write in writes:
        write.assert_not_called()
    lookup.assert_not_called()
    children.assert_not_called()
    prompt.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [AgentNotFoundError, RuntimeError])
@pytest.mark.parametrize("payload", [
    {"related_agent_ids": [999]},
    {"related_agents": [{"agent_id": 999, "version_no": 3}]},
])
async def test_target_lookup_failure_stops_all_writes(boundary, error_type, payload):
    lookup, children, writes, prompt = boundary
    lookup.side_effect = error_type("not visible or unavailable")
    with pytest.raises(error_type):
        await service.update_agent_info_impl(AgentInfoRequest(agent_id=1, **payload), "token")
    for write in writes:
        write.assert_not_called()
    children.assert_not_called()
    prompt.assert_not_called()


@pytest.mark.asyncio
async def test_indirect_cycle_stops_all_writes(boundary):
    lookup, children, writes, prompt = boundary
    children.side_effect = lambda main_agent_id, **kwargs: {2: [3], 3: [1]}[main_agent_id]
    with pytest.raises(AgentRelationValidationError, match="Circular dependency"):
        await service.update_agent_info_impl(AgentInfoRequest(agent_id=1, related_agent_ids=[2]), "token")
    for write in writes:
        write.assert_not_called()
    prompt.assert_not_called()


@pytest.mark.parametrize("payload, expected", [
    ({}, None),
    ({"related_agent_ids": []}, []),
    ({"related_agents": []}, []),
    ({"related_agent_ids": [2]}, [{"agent_id": 2, "version_no": None}]),
    ({"related_agents": [{"agent_id": 2, "version_no": 3}]}, [{"agent_id": 2, "version_no": 3}]),
    ({"related_agent_ids": [2], "related_agents": [{"agent_id": 2, "version_no": 3}]},
     [{"agent_id": 2, "version_no": 3}]),
])
def test_valid_selection_and_patch_semantics(boundary, payload, expected):
    lookup, children, _, _ = boundary
    assert service._validate_agent_relationships(AgentInfoRequest(agent_id=1, **payload), "tenant") == expected
    if expected:
        version = expected[0]["version_no"] or 0
        lookup.assert_called_once_with(2, "tenant", version_no=version)
        children.assert_called_once_with(main_agent_id=2, tenant_id="tenant", version_no=version)
    else:
        lookup.assert_not_called()
        children.assert_not_called()


def test_shared_descendant_is_not_a_cycle(boundary):
    _, children, _, _ = boundary
    children.side_effect = lambda main_agent_id, **kwargs: {2: [4], 3: [4], 4: []}[main_agent_id]
    request = AgentInfoRequest(agent_id=1, related_agent_ids=[2, 3])
    assert service._validate_agent_relationships(request, "tenant") == [
        {"agent_id": 2, "version_no": None}, {"agent_id": 3, "version_no": None},
    ]
    assert children.call_count == 3
