# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AIDP hit identity and request-scoped northbound link configuration."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from management.services.agent.preparation import tools as tool_preparation
from nexent.core.agents.nexent_agent import NexentAgent

CASE_ID = "AIDP-FILE-IDENTITY-D1-001"
KDS_ID = "kb-42"
FILE_UUID = "11111111-2222-4333-8444-555555555555"
NORTHBOUND_BASE = "https://api.example.com/api"
EXPECTED_URL = (
    f"{NORTHBOUND_BASE}/nb/v1/knowledge-bases/{KDS_ID}/files/{FILE_UUID}/download"
)

pytestmark = [pytest.mark.case_id(CASE_ID), pytest.mark.stage("D1")]


def _tool_record():
    return {
        "class_name": "AidpSearchTool",
        "name": "aidp_search",
        "description": "AIDP search",
        "description_zh": "AIDP 检索",
        "inputs": "{}",
        "output_type": "string",
        "params": [{"name": "kds_list", "default": [KDS_ID]}],
        "source": "local",
        "usage": None,
    }


def _access_module():
    module = SimpleNamespace()
    module.resolve_current_aidp_access = lambda **_kwargs: SimpleNamespace(
        accessible_id_set={KDS_ID},
        name_to_id={},
        tenant_name_to_id={},
    )
    return module


async def _build_tool(northbound_run: bool):
    with patch.object(
        tool_preparation, "discover_langchain_tools",
        new=AsyncMock(return_value=[]),
    ), patch.object(
        tool_preparation, "_resolve_runtime_tool_records",
        return_value=[_tool_record()],
    ), patch.object(
        tool_preparation, "search_agent_info_by_agent_id",
        return_value={"name": "agent"},
    ), patch.object(
        tool_preparation, "AIDP_SERVER_URL", "https://aidp.test",
    ), patch.object(
        tool_preparation, "AIDP_API_KEY", "aidp-secret",
    ), patch.object(
        tool_preparation, "AIDP_TENANT_ID", "aidp",
    ), patch.object(
        tool_preparation, "NORTHBOUND_EXTERNAL_URL", NORTHBOUND_BASE,
    ), patch.dict(
        sys.modules,
        {"ext_components.aidp.services.aidp_access_service": _access_module()},
    ):
        configs = await tool_preparation.create_tool_config_list(
            agent_id="1",
            tenant_id="tenant-1",
            user_id="user-1",
            northbound_run=northbound_run,
        )
    assert len(configs) == 1
    config = configs[0]
    # Exercise the SDK's real ToolConfig-to-instance path (whitelist and the
    # request-scoped northbound settings included), not a hand-built tool.
    tool = NexentAgent.create_local_tool(
        SimpleNamespace(observer=None), config
    )
    return config, tool


def _records():
    identity = {"kds_id": KDS_ID, "file_uuid": FILE_UUID}
    return [
        {
            "id": "chunk-1",
            "chunk_type": "text",
            "title": "Manual.pdf",
            "text": "first chunk",
            "file_url": "",
            "metadata": dict(identity),
        },
        {
            "id": "chunk-2",
            "chunk_type": "text",
            "title": "Manual.pdf",
            "text": "second chunk",
            "file_url": "",
            "metadata": dict(identity),
        },
        {
            "id": "chunk-3",
            "chunk_type": "text",
            "title": "No identity.pdf",
            "text": "missing locator",
            "file_url": "kb-42/data/image.png",
            "metadata": {"kds_id": KDS_ID},
        },
    ]


@pytest.mark.asyncio
async def test_page_tool_keeps_identity_without_northbound_field():
    config, tool = await _build_tool(northbound_run=False)

    assert "northbound_run" not in (config.metadata or {})
    ui_results, model_results, _ = tool._process_records(_records())

    assert ui_results[0]["score_details"]["kds_id"] == KDS_ID
    assert ui_results[0]["score_details"]["file_uuid"] == FILE_UUID
    assert "kds_id" not in ui_results[2]["score_details"]
    assert "file_uuid" not in ui_results[2]["score_details"]
    assert all(
        "northbound_api_download_url" not in item for item in model_results
    )
    assert all(
        "northbound_api_download_url" not in item for item in ui_results
    )


@pytest.mark.asyncio
async def test_northbound_tool_adds_only_a_model_side_locator_url():
    config, tool = await _build_tool(northbound_run=True)

    assert config.metadata["northbound_run"] is True
    assert config.metadata["northbound_external_url"] == NORTHBOUND_BASE
    assert "northbound_run" not in config.params
    assert "northbound_external_url" not in config.params

    ui_results, model_results, _ = tool._process_records(_records())

    assert model_results[0]["northbound_api_download_url"] == EXPECTED_URL
    assert model_results[1]["northbound_api_download_url"] == EXPECTED_URL
    assert "northbound_api_download_url" not in model_results[2]
    assert all(
        "northbound_api_download_url" not in item for item in ui_results
    )
    assert "aidp-secret" not in str(model_results)


@pytest.mark.asyncio
async def test_invalid_northbound_base_degrades_without_a_link():
    _, tool = await _build_tool(northbound_run=True)
    tool.set_northbound_download("not-an-absolute-url")

    _, model_results, _ = tool._process_records(_records())

    assert all(
        "northbound_api_download_url" not in item for item in model_results
    )
