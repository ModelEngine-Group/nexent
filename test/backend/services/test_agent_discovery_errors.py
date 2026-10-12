"""Preserve expected lookup misses through the Agent service boundary."""

import pytest

from test.backend.services import test_agent_service as legacy
from consts.exceptions import AgentNotFoundError
from management.services.agent import management, service


@pytest.mark.asyncio
async def test_detail_preserves_not_found_and_stops_capability_reads(mocker):
    error = AgentNotFoundError("agent not found")
    lookup = mocker.patch.object(service, "search_agent_info_by_agent_id", side_effect=error)
    tools = mocker.patch.object(service, "search_tools_for_sub_agent")
    with pytest.raises(AgentNotFoundError) as raised:
        await service.get_agent_info_impl(42, "tenant-b", 0, "user-b")
    assert raised.value is error
    lookup.assert_called_once_with(42, "tenant-b", 0)
    tools.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["lookup", "versions"])
@pytest.mark.parametrize("error_type", [AgentNotFoundError, RuntimeError])
def test_name_preserves_error_classification(mocker, failure_stage, error_type):
    error = error_type("lookup failed")
    lookup = mocker.patch.object(management, "search_agent_id_by_agent_name", return_value=42)
    versions = mocker.patch.object(management, "query_version_list", return_value=[])
    (lookup if failure_stage == "lookup" else versions).side_effect = error
    with pytest.raises(error_type) as raised:
        management.get_agent_by_name_impl("missing", "tenant-b")
    assert raised.value is error
    if failure_stage == "lookup":
        versions.assert_not_called()
