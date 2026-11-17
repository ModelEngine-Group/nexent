# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep historical attachments out of the native core's active task."""

from unittest.mock import AsyncMock

import pytest

import management.services.agent.preparation.run as service
from contracts.conversation import HistoryItem
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig


@pytest.mark.parametrize("core,current_upload", [("jiuwen", False), ("jiuwen", True), ("smolagents", False)])
async def test_current_query_preserves_history_without_reactivating_uploads(mocker, core, current_upload):
    old_file = {"name": "old-image.png", "url": "s3://nexent/attachments/old-image.png"}
    new_file = {"name": "new-image.png", "url": "s3://nexent/attachments/new-image.png"}
    history = [HistoryItem(role="user", content="Analyze the original image", minio_files=[old_file]),
               HistoryItem(role="assistant", content="The image has already been analyzed")]
    mocker.patch("management.services.model.runtime_options.compile_bound_model_profile", return_value=None)
    config = AgentConfig(agent_core=core, name="fixture", description="Fixture", model_name="fixture", tools=[])
    model = ModelConfig(cite_name="fixture", model_name="fixture", url="http://fixture")
    for name in ["_ensure_agent_reasoning_snapshot", "_validate_run_minio_files"]:
        mocker.patch.object(service, name)
    mocker.patch.object(service, "_build_run_workspace", return_value="/fixture/workspace")
    mocker.patch.object(service, "create_agent_config", new=AsyncMock(return_value=config))
    mocker.patch.object(service, "create_model_config_list", new=AsyncMock(return_value=[model]))
    mocker.patch.object(service, "search_agent_info_by_agent_id", return_value={})
    mocker.patch.object(service, "get_remote_mcp_server_list", new=AsyncMock(return_value=[]))
    mocker.patch.object(service, "filter_mcp_servers_and_tools", return_value=[])
    mocker.patch.object(service, "get_tenant_local_mcp_server", return_value="http://fixture/mcp")
    mocker.patch.object(service, "get_redis_client", return_value=None)
    mocker.patch("runtime.adapters.nexent.sandbox.resolve_sandbox_config", return_value=None)
    mocker.patch("management.services.agent.service.build_sandbox_policy", return_value=None)
    info = await service.create_agent_run_info(
        agent_id=1, minio_files=[new_file] if current_upload else [], query="What can you do?",
        history=history, user_id="fixture-user", tenant_id="fixture-tenant", language="en", is_debug=True,
    )
    assert "What can you do?" in info.query
    assert "old-image.png" in info.history[0].content
    assert len(info.minio_files) == (2 if current_upload else 1)
    if core == "jiuwen":
        assert "old-image.png" not in info.query
        if current_upload:
            assert "new-image.png" in info.query
        else:
            assert info.query == "What can you do?"
    else:
        assert "old-image.png" in info.query
