# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared Workbench definitions keep resource selection and backfills tenant safe."""

from copy import deepcopy

from contracts.agent import AgentRequest, SystemAgentRef, WorkbenchSessionConfig
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.services.agent import workbench
from management.services.agent.preparation import run as preparation
from nexent.core.agents.contracts.config import AgentConfig


def test_shared_profile_resolves_published_shared_bindings(mocker):
    mocker.patch.object(
        workbench.system_agent_provider,
        "get_workbench_main_ref",
        return_value=SystemAgentRef(
            ASSET_OWNER_TENANT_ID,
            "workbench_main",
            77,
            3,
        ),
    )
    published = mocker.patch.object(workbench, "SkillService")
    published.return_value.get_enabled_skills_for_agent.return_value = [{"skill_id": 501, "name": "pdf"}]
    profile = workbench.build_workbench_main_profile("tenant-a")
    assert profile["agent_id"] == 77 and profile["version_no"] == 3
    assert profile["default_skill_resources"][0]["skill_id"] == 501
    published.return_value.get_enabled_skills_for_agent.assert_called_once_with(
        agent_id=77, tenant_id=ASSET_OWNER_TENANT_ID, version_no=3,
    )


def test_shared_plan_mounts_published_capabilities_with_tenant_runtime(mocker):
    source = {
        "agent_id": 77,
        "version_no": 3,
        "name": "workbench_main",
        "enabled": True,
        "tenant_id": ASSET_OWNER_TENANT_ID,
        "agent_origin": "SYSTEM",
    }
    original = deepcopy(source)
    mocker.patch.object(
        workbench.system_agent_provider,
        "get_workbench_main_ref",
        return_value=SystemAgentRef(
            ASSET_OWNER_TENANT_ID,
            "workbench_main",
            77,
            3,
        ),
    )
    mocker.patch.object(workbench, "search_agent_info_by_agent_id", return_value=source)
    skill_resolution = mocker.patch.object(
        workbench, "_resolve_skill_mounts", return_value=()
    )
    persistent_bindings = mocker.patch.object(
        workbench.skill_db, "search_skills_for_agent", return_value=[{"skill_id": 501, "name": "pdf"}]
    )
    canonical, plan = workbench.resolve_workbench_config(
        WorkbenchSessionConfig(mode="generic_chat"), tenant_id="tenant-a"
    )
    assert plan.root.identity.agent_id == 77
    assert skill_resolution.call_args.args[1] == "tenant-a"
    assert skill_resolution.call_args.args[2] == ({"skill_id": 501, "name": "pdf"},)
    persistent_bindings.assert_called_once_with(agent_id=77, tenant_id=ASSET_OWNER_TENANT_ID, version_no=3)
    assert skill_resolution.call_args.kwargs["published_tenant_id"] == ASSET_OWNER_TENANT_ID

    mocker.patch.object(workbench, "ENABLE_AGENT_WORKBENCH", True)
    knowledge = mocker.patch.object(workbench, "resolve_workbench_knowledge")
    tools = mocker.patch.object(
        workbench.system_agent_provider,
        "get_workbench_default_tools",
        return_value=[
            {
                "tool_id": 901,
                "class_name": "KnowledgeBaseSearchTool",
                "name": "knowledge_base_search",
            },
        ],
    )
    request = AgentRequest(
        agent_id=77,
        conversation_id=1,
        query="hello",
        history=[],
        minio_files=[],
        is_debug=False,
        entrypoint="workbench",
        workbench=canonical,
        expected_workbench_config_version=1,
    )
    prepared = workbench.prepare_portable_workbench(
        request, {"workbench_config": canonical.model_dump(mode="json"), "workbench_config_version": 1},
        "user-a", "tenant-a",
    )
    compiled = workbench.compile_runtime_mount_plan(
        prepared.plan, AgentConfig(
            agent_id=77, version_no=3, name="workbench_main", description="", model_name="model", tools=[],
        ),
    )
    tools.assert_not_called()
    knowledge.assert_not_called()
    assert prepared.version == 1
    assert compiled.root.identity == plan.root.identity
    assert compiled.root.identity.origin == "SYSTEM"
    assert source == original


def test_runtime_reasoning_backfill_never_mutates_system_snapshots(mocker):
    from management.services.agent import reasoning

    mocker.patch.object(
        preparation,
        "search_agent_info_by_agent_id",
        return_value={
            "agent_id": 77,
            "agent_origin": "SYSTEM",
            "tenant_id": ASSET_OWNER_TENANT_ID,
        },
    )
    resolve = mocker.patch.object(reasoning, "snapshot_agent_reasoning_config")
    update = mocker.patch.object(preparation, "update_agent_snapshot")
    preparation._ensure_agent_reasoning_snapshot(77, "tenant-a", 3)
    resolve.assert_not_called()
    update.assert_not_called()
