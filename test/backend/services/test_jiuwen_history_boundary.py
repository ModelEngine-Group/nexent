"""An existing chat cannot fall back to client history when its DB boundary is unknown."""

from unittest.mock import AsyncMock

import pytest
from consts.exceptions import ForbiddenError
from consts.model import AgentRequest
from management.services.agent import run as service


@pytest.mark.parametrize("boundary", [None, True, "12", 12])
async def test_invalid_database_boundary_rejects_before_runtime_allocation(mocker, boundary):
    mocker.patch.object(service, "get_current_run_user_message_id", return_value=boundary)
    load = mocker.patch.object(service, "load_historical_context", return_value=None)
    memory = mocker.patch.object(service, "build_memory_context")
    allocate = mocker.patch.object(service, "create_agent_run_info", new=AsyncMock())
    request = AgentRequest(agent_id=42, conversation_id=101, query="Continue",
        history=[{"role": "assistant", "content": "Client supplied history"}])
    with pytest.raises(ForbiddenError, match="history boundary"):
        await service.prepare_agent_run(request, "owner", "tenant")
    memory.assert_not_called()
    allocate.assert_not_awaited()
    assert load.call_count == (1 if boundary == 12 else 0)
