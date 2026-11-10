# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest

from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.agents.nexent_agent import NexentAgent


@pytest.mark.asyncio
async def test_independent_aidp_tool_rebuilds_a_reference_the_management_proxy_accepts(mocker):
    from infrastructure import ind_aidp_images
    from management.services.agent.preparation import local_tool, tools
    from management.services.knowledge_base.providers import aidp as proxy
    from runtime.agentos import prepared_local_tool

    mocker.patch.object(environment, "JWT_SECRET", "fixture-agentos-key")
    mocker.patch.object(ind_aidp_images, "IND_AIDP_IMAGE_SIGNING_KEY", "fixture-image-signing-key")
    row = {
        "tool_id": 10, "tool_instance_id": 24, "name": "ind_aidp_search", "class_name": "IndependentAidpSearchTool",
        "source": "local", "description": "Private search", "inputs": None, "usage": None, "output_type": "string",
        "instance_params": {}, "params": [{"name": name, "default": value} for name, value in {
            "server_url": "https://private-aidp.invalid", "api_key": "runtime-aidp-fixture-key",
            "tenant_id": "provider-a", "kds_list": ["private-kb"],
        }.items()],
    }
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[row])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={})
    compile_callback = mocker.patch.object(tools, "create_ind_aidp_image_url_builder")
    tool, = await tools.create_tool_config_list(8, "tenant-a", "user-a", version_no=4, portable_evaluation=True)
    compile_callback.assert_not_called()
    binding = local_tool.export_local_tool(tool, [row], 8, 4, "tenant-a", "zh")
    for secret in ("https://private-aidp.invalid", "runtime-aidp-fixture-key", "provider-a", "private-kb"):
        assert secret not in binding.model_dump_json()

    mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[row])
    resource = SimpleNamespace(agent_id=8, version_no=4, tools=[binding])
    hydrated = prepared_local_tool.materialize_local_tools(resource, ServicePrincipal("user-a", "tenant-a"), "zh")
    instance = NexentAgent.create_local_tool(SimpleNamespace(observer=None), hydrated["ind_aidp_search"])
    assert instance.api_key == "runtime-aidp-fixture-key"
    assert instance.kds_list == ["private-kb"]
    reference = instance.image_url_builder("/KnowledgeBase/Tenants/provider-a/KnowledgeBases/private-kb/p.png")
    assert reference.startswith("/api/ind-aidp/images/")
    payload = proxy._decode_image_ref(reference.rsplit("/", 1)[-1])
    assert payload == {
        "agent_id": 8, "version_no": 4, "tenant_id": "tenant-a", "aidp_tenant_id": "provider-a",
        "tool_id": 10, "image_path": "private-kb/p.png",
    }
    with pytest.raises(ValueError):
        instance.image_url_builder("../outside.png")
