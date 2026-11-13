# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest

from contracts.agentos import WorkbenchDebugSkillLookup, WorkbenchSkillLookup, WorkbenchSkillMounts
from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.agents.nexent_agent import NexentAgent


@pytest.mark.asyncio
@pytest.mark.parametrize("derived", [False, True, "workbench", "debug"])
async def test_independent_aidp_tool_rebuilds_a_reference_the_management_proxy_accepts(mocker, derived):
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
    mounted = derived in {"workbench", "debug"}
    if derived:
        row.pop("tool_instance_id")
        row["workbench_skill_ids" if mounted else "skill_instance_ids"] = [42]
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[row])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={})
    compile_callback = mocker.patch.object(tools, "create_ind_aidp_image_url_builder")
    tool, = await tools.create_tool_config_list(8, "tenant-a", "user-a", version_no=4, portable_evaluation=True)
    compile_callback.assert_not_called()
    binding = local_tool.export_local_tool(tool, [row], 8, 4, "tenant-a", "zh")
    for secret in ("https://private-aidp.invalid", "runtime-aidp-fixture-key", "provider-a", "private-kb"):
        assert secret not in binding.model_dump_json()

    if derived is True:
        mocker.patch.object(prepared_local_tool, "read_skill_derived_local_tools", return_value=[row])
    elif not derived:
        mocker.patch.object(prepared_local_tool, "read_bound_local_tools", return_value=[row])
    resource = SimpleNamespace(
        agent_id=8, version_no=4, tools=[binding],
        skill_refs=[SimpleNamespace(instance_id=42)] if derived is True else [],
        workbench_skill_refs=[SimpleNamespace(skill_id=42)] if mounted else [],
    )
    actor = ServicePrincipal("user-a", "tenant-a")
    options = {}
    if mounted:
        lookup = WorkbenchDebugSkillLookup(agent_id=8, agent_version=4, run_id="a" * 32) if derived == "debug" else WorkbenchSkillLookup(
            agent_id=8, agent_version=4, conversation_id=12, run_id="a" * 32, workbench_version=3,
        )
        with pytest.raises(ValueError, match="Workbench"):
            prepared_local_tool.materialize_local_tools(resource, actor, "zh", workbench_tools=[row])
        options = {"workbench_tools": [row], "workbench_lookup": lookup}
    hydrated = prepared_local_tool.materialize_local_tools(resource, actor, "zh", **options)
    instance = NexentAgent.create_local_tool(SimpleNamespace(observer=None), hydrated["ind_aidp_search"])
    assert instance.api_key == "runtime-aidp-fixture-key"
    assert instance.kds_list == ["private-kb"]
    reference = instance.image_url_builder("/KnowledgeBase/Tenants/provider-a/KnowledgeBases/private-kb/p.png")
    assert reference.startswith("/api/ind-aidp/images/")
    payload = proxy._decode_image_ref(reference.rsplit("/", 1)[-1])
    if mounted:
        assert payload["workbench"] == lookup.model_dump(mode="json")
        assert "runtime-aidp-fixture-key" not in str(payload) and "https://private-aidp.invalid" not in str(payload)
        authorization = (
            WorkbenchSkillMounts(mounts=[{"skill_id": 42, "config_values": {}}])
            if derived == "debug" else {42: {}}
        )
        if derived == "debug":
            mounts = mocker.patch.object(proxy, "read_workbench_debug_grant", return_value=authorization)
            scope_args = (lookup, actor)
        else:
            mounts = mocker.patch.object(proxy, "read_workbench_image_mounts", return_value=authorization)
            scope_args = (lookup, "user-a", "tenant-a")
        rows = mocker.patch.object(proxy, "read_workbench_skill_rows", return_value={42: {"skill_id": 42}})
        tools = mocker.patch.object(proxy, "read_workbench_derived_tools", return_value=[row])
        assert proxy._resolve_image_credentials(payload, actor) == (
            "https://private-aidp.invalid", "runtime-aidp-fixture-key", "provider-a", "private-kb/p.png",
        )
        mounts.assert_called_once_with(*scope_args)
        rows.assert_called_once_with(8, 4, actor, {42: {}})
        for foreign in (None, ServicePrincipal("user-a", "other-tenant")):
            with pytest.raises(proxy.IndependentAidpServiceError, match="unavailable"):
                proxy._resolve_image_credentials(payload, foreign)
        mounts.return_value = None
        with pytest.raises(proxy.IndependentAidpServiceError, match="unavailable"):
            proxy._resolve_image_credentials(payload, ServicePrincipal("other-user", "tenant-a"))
        mounts.return_value = authorization
        row["workbench_skill_ids"] = [43]
        with pytest.raises(proxy.IndependentAidpServiceError, match="changed"):
            proxy._resolve_image_credentials(payload, actor)
        tools.return_value = []
        with pytest.raises(proxy.IndependentAidpServiceError, match="unavailable"):
            proxy._resolve_image_credentials(payload, actor)
        return

    revision = payload.pop("skill_revision", None)
    assert bool(revision) is derived
    assert payload == {
        "agent_id": 8, "version_no": 4, "tenant_id": "tenant-a", "aidp_tenant_id": "provider-a",
        "tool_id": 10, "image_path": "private-kb/p.png",
    }
    if derived:
        payload["skill_revision"] = revision
        lookup = mocker.patch.object(proxy, "read_skill_derived_local_tools", return_value=[row])
        explicit = mocker.patch.object(proxy, "query_tool_instances_by_id")
        assert proxy._resolve_image_credentials(payload) == (
            "https://private-aidp.invalid", "runtime-aidp-fixture-key", "provider-a", "private-kb/p.png",
        )
        lookup.assert_called_once_with(8, 4, "tenant-a", ["ind_aidp_search"])
        explicit.assert_not_called()
        row["skill_instance_ids"] = [43]
        with pytest.raises(proxy.IndependentAidpServiceError, match="changed"):
            proxy._resolve_image_credentials(payload)
        lookup.return_value = []
        with pytest.raises(proxy.IndependentAidpServiceError, match="unavailable"):
            proxy._resolve_image_credentials(payload)
    with pytest.raises(ValueError):
        instance.image_url_builder("../outside.png")
