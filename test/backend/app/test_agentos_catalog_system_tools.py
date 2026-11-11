# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserve catalog-bound transfer and parallel tools through AgentOS."""

from types import SimpleNamespace

import pytest

from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import local_tool, tools
from nexent.core.agents.nexent_agent import NexentAgent
from runtime.agentos import prepared_local_tool
from test.backend.app.test_agentos_prepared_local_tool import stored_tool


@pytest.mark.asyncio
@pytest.mark.parametrize("class_name,canonical", [
    ("DownloadFromS3Tool", "download_from_s3"), ("UploadToS3Tool", "upload_to_s3"),
    ("ParallelExecutorTool", "parallel_executor"),
    ("StoreMemoryTool", "store_memory"), ("SearchMemoryTool", "search_memory"),
])
async def test_catalog_system_class_keeps_actual_sdk_state_and_bound_scope(mocker, tmp_path, stored_tool, class_name, canonical):
    from infrastructure.object_storage import client as storage

    params = ({"default_timeout_seconds": 47} if class_name == "ParallelExecutorTool" else
              {} if class_name in {"StoreMemoryTool", "SearchMemoryTool"} else {"workspace_path": str(tmp_path)})
    row = {**stored_tool, "name": "tenant_" + canonical, "class_name": class_name,
           "params": [{"name": key, "default": value} for key, value in params.items()], "instance_params": {}}
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[row])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "root"})
    client = mocker.patch.object(storage, "minio_client")
    mocker.patch.object(tools, "minio_client", client)
    legacy, = await tools.create_tool_config_list(7, "tenant-a", "user-a", version_no=3)
    portable, = await tools.create_tool_config_list(7, "tenant-a", "user-a", version_no=3, portable_evaluation=True)
    assert portable.metadata is None
    reference = local_tool.export_local_tool(portable, [row], 7, 3, "tenant-a", "zh")
    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[row])
    rebound = prepared_local_tool.materialize_local_tools(
        SimpleNamespace(agent_id=7, version_no=3, tools=[reference]), ServicePrincipal("user-a", "tenant-a"), "zh",
    )[reference.tool_id]
    old = NexentAgent.create_local_tool(SimpleNamespace(observer=None), legacy)
    actual = NexentAgent.create_local_tool(SimpleNamespace(observer=None), rebound)
    assert rebound.name == portable.name and actual.name == old.name == canonical
    if class_name in {"StoreMemoryTool", "SearchMemoryTool"}:
        assert actual.memory_service is old.memory_service is None
        assert (actual.user_id, actual.tenant_id) == (old.user_id, old.tenant_id) == ("", "")
        assert actual.forward("fixture") == old.forward("fixture")
    elif class_name == "ParallelExecutorTool":
        assert actual.default_timeout_seconds == old.default_timeout_seconds == 47
        assert actual.forward([]) == old.forward([]) == []
    else:
        assert actual.workspace_path == old.workspace_path
        assert (actual.user_id, actual.tenant_id) == (old.user_id, old.tenant_id) == ("user-a", "tenant-a")
        assert actual.minio_client is old.minio_client is client
        if class_name == "DownloadFromS3Tool":
            assert actual._check_access("attachments/user-a/file") == old._check_access("attachments/user-a/file") is True
            assert actual._check_access("attachments/user-b/file") == old._check_access("attachments/user-b/file") is False
        else:
            assert actual._validate_path("approved.txt") == old._validate_path("approved.txt")
            with pytest.raises(Exception, match="within the workspace"):
                actual._validate_path("../denied.txt")
    assert client.mock_calls == []
