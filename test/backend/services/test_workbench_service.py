"""Unit tests for request-scoped Workbench root resolution."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from consts.exceptions import ValidationError, WorkbenchConfigVersionConflict
from consts.model import WorkbenchSessionConfig
from services import workbench_service
from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.agent_model import ToolConfig
from threading import local


def test_runtime_copy_preserves_live_clients_and_isolates_nested_configuration():
    client = local()
    source = AgentConfig(name="root", model_name="test", description="", tools=[
        ToolConfig(class_name="KnowledgeBaseSearchTool", name="search", params={"client": client, "index_names": ["a", "b"]}),
    ], managed_agents=[AgentConfig(name="child", model_name="test", description="", tools=[])])
    identity = workbench_service.RuntimeAgentIdentity("system:root", None, None, "root", "Root", "SYSTEM")
    overlay = workbench_service.RootRuntimeOverlay(None, None, (), None)
    result = workbench_service.RuntimeMountService().resolve_root(workbench_service.RuntimeRootDescriptor(identity, source), overlay).root.agent_config
    assert result.tools[0].params["client"] is client
    assert result.tools[0] is not source.tools[0]
    assert result.managed_agents[0] is not source.managed_agents[0]
    result.tools[0].params["index_names"].append("c")
    assert source.tools[0].params["index_names"] == ["a", "b"]


@pytest.fixture(autouse=True)
def published_instances(mocker):
    mocker.patch.object(
        workbench_service,
        "_capture_skill_file_snapshot",
        return_value=(("SKILL.md", b"# Test"),),
    )
    mocker.patch.object(workbench_service, "query_tools_by_ids", return_value=[{"tool_id": 4, "author": "tenant", "is_available": True, "params": []}])
    return mocker.patch.object(workbench_service.skill_db, "search_skills_for_agent", return_value=[])


def _config(version_no=None, skills=None):
    return WorkbenchSessionConfig.model_validate({
        "mode": "single_agent_chat",
        "agent_mounts": [{"agent_id": 7, "version_no": version_no}],
        "skill_mounts": skills or [],
    })


def test_ut_be_wb_003_resolver_locks_current_published_version(mocker):
    """UT-BE-WB-003: the first resolution writes a concrete version."""
    mocker.patch.object(workbench_service, "resolve_root_version", return_value=5)
    mocker.patch.object(
        workbench_service,
        "search_agent_info_by_agent_id",
        return_value={"agent_id": 7, "name": "Root"},
    )
    canonical, tree = workbench_service.resolve_workbench_config(
        _config(), tenant_id="tenant"
    )
    assert canonical.agent_mounts[0].version_no == 5
    assert tree.root.identity.invocation_name == "agent_7_v5"


def test_ut_be_wb_006_resolution_is_deep_copy_and_relation_write_free(mocker):
    """UT-BE-WB-006: overlays do not mutate caller input or repositories."""
    config = _config(3, [{"skill_id": 11, "config_values": {"nested": {"x": 1}}}])
    before = deepcopy(config.model_dump(mode="json"))
    mocker.patch.object(workbench_service, "resolve_root_version", return_value=3)
    mocker.patch.object(
        workbench_service,
        "search_agent_info_by_agent_id",
        return_value={"agent_id": 7, "name": "Root"},
    )
    mocker.patch.object(
        workbench_service.skill_db,
        "get_skill_by_id",
        return_value={
            "skill_id": 11,
            "name": "Invoice",
            "description": "Extract invoices",
            "tool_ids": [4],
            "config_values": {"base": True},
            "config_schemas": [{"name": "base", "type": "boolean"}, {"name": "nested", "type": "object"}],
        },
    )
    _, tree = workbench_service.resolve_workbench_config(config, tenant_id="tenant")
    assert config.model_dump(mode="json") == before
    assert tree.root_skills[0].config_values == {"base": True, "nested": {"x": 1}}


def test_empty_skill_mounts_do_not_restore_agent_defaults(mocker):
    """UT-BE-WB-010/UT-BE-WB-028: an empty full selection remains empty."""
    mocker.patch.object(workbench_service, "resolve_root_version", return_value=3)
    mocker.patch.object(
        workbench_service,
        "search_agent_info_by_agent_id",
        return_value={"agent_id": 7, "name": "Root"},
    )
    _, tree = workbench_service.resolve_workbench_config(_config(3), tenant_id="tenant")
    assert workbench_service.runtime_skill_snapshot(tree) == []


def test_ut_be_wb_014_missing_skill_fails_before_snapshot(mocker):
    """UT-BE-WB-014: inaccessible Skills fail with no partial snapshot."""
    mocker.patch.object(workbench_service, "resolve_root_version", return_value=3)
    mocker.patch.object(
        workbench_service,
        "search_agent_info_by_agent_id",
        return_value={"agent_id": 7, "name": "Root"},
    )
    mocker.patch.object(workbench_service.skill_db, "get_skill_by_id", return_value=None)
    with pytest.raises(ValidationError, match="RUNTIME_SKILL_FORBIDDEN"):
        workbench_service.resolve_workbench_config(
            _config(3, [{"skill_id": 99}]), tenant_id="tenant"
        )


def test_version_check_returns_current_canonical_state():
    """Stale writers receive the current version and declaration."""
    current = {"mode": "single_agent_chat"}
    with pytest.raises(WorkbenchConfigVersionConflict) as raised:
        workbench_service.assert_workbench_version(
            {"workbench_config_version": 4, "workbench_config": current}, 3
        )
    assert raised.value.current_version == 4
    assert raised.value.current_config == current


def test_ut_be_wb_024_runtime_composer_rejects_multi_root_scope():
    """UT-BE-WB-024: reserved composer cannot accidentally enable orchestration."""
    with pytest.raises(ValidationError, match="Multi-Agent"):
        workbench_service.RuntimeAgentTreeComposer().compose([])


@pytest.mark.parametrize("origin,agent_id,runtime_ref", [("PERSISTED", 7, "agent:7:v3"), ("SYSTEM", None, "system:assistant")])
def test_ut_be_wb_022_023_executable_roots_share_pure_mount_contract(mocker, origin, agent_id, runtime_ref):
    """UT-BE-WB-022/UT-BE-WB-023: both roots use the same pure compiler."""
    repository_lookup = mocker.patch.object(workbench_service.skill_db, "get_skill_by_id")
    source = AgentConfig(name="Published", description="", tools=[], model_name="root-model")
    descriptor = workbench_service.RuntimeRootDescriptor(
        identity=workbench_service.RuntimeAgentIdentity(
            runtime_ref=runtime_ref, agent_id=agent_id, version_no=3 if agent_id else None,
            invocation_name="runtime_root", display_name="Display", origin=origin,
        ),
        agent_config=source,
    )
    overlay = workbench_service.RootRuntimeOverlay(model_id=None, requested_output_tokens=None, skill_mounts=(), knowledge_scope=None)
    tree = workbench_service.RuntimeMountService().resolve_root(descriptor, overlay)
    assert tree.root.agent_config is not source
    assert tree.root.agent_config.runtime_ref == runtime_ref
    assert tree.root.agent_config.invocation_name == "runtime_root"
    assert tree.root.agent_config.display_name == "Display"
    assert tree.root.agent_config.origin == origin
    assert source.runtime_ref is None
    repository_lookup.assert_not_called()


def test_ut_be_wb_001_persisted_plan_compiles_the_effective_root_only(mocker):
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value={"name": "Root"})
    _, plan = workbench_service.resolve_workbench_config(_config(3), tenant_id="tenant")
    child = AgentConfig(name="Child", description="", tools=[], model_name="child-model")
    root = AgentConfig(name="Root", description="", tools=[], model_name="root-model", managed_agents=[child])
    tree = workbench_service.compile_runtime_mount_plan(plan, root)
    assert tree.root.agent_config is not root
    assert tree.root.agent_config.runtime_ref == "agent:7:v3"
    assert tree.root.agent_config.managed_agents[0].model_name == "child-model"
    assert tree.root.agent_config.managed_agents[0] is not child
    assert root.runtime_ref is None


def test_ut_be_wb_007_concurrent_mounts_are_request_isolated():
    """UT-BE-WB-007: concurrent overlays for one root cannot cross-contaminate."""
    descriptor = workbench_service.RuntimeRootDescriptor(
        identity=workbench_service.RuntimeAgentIdentity(
            runtime_ref="agent:7:v3",
            agent_id=7,
            version_no=3,
            invocation_name="agent_7_v3",
            display_name="Root",
            origin="PERSISTED",
        ),
        agent_config=AgentConfig(
            name="Root",
            description="",
            tools=[],
            model_name="root-model",
        ),
    )

    def resolve(skill_id, knowledge_id):
        return workbench_service.RuntimeMountService().resolve_root(
            descriptor,
            workbench_service.RootRuntimeOverlay(
                model_id=None,
                requested_output_tokens=None,
                skill_mounts=({"skill_id": skill_id},),
                knowledge_scope={"local": {"knowledge_ids": [knowledge_id]}},
            ),
            resolved_skills=(
                workbench_service.ResolvedSkillMount(
                    skill_id=skill_id,
                    name=f"Skill {skill_id}",
                    description="",
                    tool_ids=(),
                    config_values={},
                ),
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(resolve, 31, "KB1")
        second_future = executor.submit(resolve, 45, "KB2")
        first = first_future.result()
        second = second_future.result()

    assert [skill.skill_id for skill in first.root_skills] == [31]
    assert [skill.skill_id for skill in second.root_skills] == [45]
    assert first.overlay.knowledge_scope["local"]["knowledge_ids"] == ["KB1"]
    assert second.overlay.knowledge_scope["local"]["knowledge_ids"] == ["KB2"]


def test_system_root_knowledge_mount_uses_the_executable_contract(mocker):
    """UT-BE-WB-023: external callers resolve knowledge without persisted Agent IDs."""
    from nexent.core.agents.agent_model import ToolConfig

    identity = workbench_service.RuntimeAgentIdentity("system:root", None, None, "system_root", "Root", "SYSTEM")
    config = AgentConfig(name="root", description="test", model_name="model", tools=[
        ToolConfig(class_name="AidpSearchTool", name="aidp_search", params={"kds_list": ["old"]},
                   metadata={"allowed_kds_set": ["old"], "kds_name_to_id_map": {"Old": "old"}}),
    ])
    overlay = workbench_service.RootRuntimeOverlay(None, None, (), {
        "local": {"mode": "disabled"}, "aidp": {"mode": "disabled"},
    })
    mounts = workbench_service.RuntimeMountService()
    tree = mounts.resolve_root(workbench_service.RuntimeRootDescriptor(identity, config), overlay)
    agent_lookup = mocker.patch.object(workbench_service, "search_agent_info_by_agent_id")
    resolved, scope = mounts.resolve_knowledge(tree, tenant_id="tenant", user_id="user")
    assert resolved.root.agent_config.agent_id is None
    assert resolved.root.agent_config.tools[0].params["kds_list"] == []
    assert resolved.root.agent_config.tools[0].metadata["allowed_kds_set"] == []
    assert resolved.root.agent_config.tools[0].metadata["kds_name_to_id_map"] == {}
    assert tree.root.agent_config.tools[0].params["kds_list"] == ["old"]
    assert scope.aidp_disabled
    agent_lookup.assert_not_called()


def test_config_version_check_does_not_change_metadata():
    """Version checks report only the Workbench lock state."""
    conversation = {
        "workbench_config_version": 2,
        "workbench_config": {"schema_version": 3},
        "runtime_metadata_version": 9,
    }
    workbench_service.assert_workbench_version(conversation, 2)
    assert conversation["runtime_metadata_version"] == 9


def test_ut_be_wb_009_three_layer_config_precedence():
    """UT-BE-WB-009: runtime config wins without mutating lower layers."""
    defaults = {"language": "en"}
    published = {"language": "zh"}
    assert workbench_service.resolve_skill_config(
        [{"name": "language", "type": "string", "required": True}],
        defaults, published, {},
    ) == {"language": "zh"}
    assert workbench_service.resolve_skill_config(
        [{"name": "language", "type": "string"}], defaults, published, {"language": "fr"},
    ) == {"language": "fr"}
    assert defaults == {"language": "en"}
    assert published == {"language": "zh"}


@pytest.mark.parametrize("runtime", [{}, {"amount": "invalid"}, {"amount": True}, {"amount": 2, "authorized_skill_names": []}])
def test_skill_config_rejects_missing_invalid_and_undeclared_values(runtime):
    """UT-BE-WB-010: invalid and undeclared Skill values fail closed."""
    with pytest.raises(ValidationError):
        workbench_service.resolve_skill_config(
            [{"name": "amount", "type": "integer", "required": True}], {}, {}, runtime,
        )


def test_ut_be_wb_004_locked_version_does_not_query_latest(mocker):
    """UT-BE-WB-004: a pinned conversation never queries the latest version."""
    latest = mocker.patch("services.knowledge_scope_service.query_current_version_no", return_value=4)
    lookup = mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value={"name": "Root"})
    canonical, _ = workbench_service.resolve_workbench_config(_config(3), tenant_id="tenant")
    latest.assert_not_called()
    lookup.assert_called_once_with(7, "tenant", 3)
    assert canonical.agent_mounts[0].version_no == 3


def test_ut_be_wb_005_missing_pinned_version_has_no_fallback(mocker):
    """UT-BE-WB-005: an unavailable pinned version has no fallback."""
    latest = mocker.patch("services.knowledge_scope_service.query_current_version_no", return_value=4)
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", side_effect=ValueError("private details"))
    skills = mocker.patch.object(workbench_service.skill_db, "get_skill_by_id")
    with pytest.raises(workbench_service.WorkbenchError) as error:
        workbench_service.resolve_workbench_config(_config(3), tenant_id="tenant")
    assert error.value.code == "AGENT_VERSION_UNAVAILABLE"
    assert "private details" not in str(error.value)
    latest.assert_not_called()
    skills.assert_not_called()


def test_ut_be_wb_013_unreadable_agent_stops_before_skill_resolution(mocker):
    """UT-BE-WB-013: Agent authorization fails before resource resolution."""
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value={"name": "Secret", "created_by": "other", "ingroup_permission": "PRIVATE"})
    mocker.patch.object(workbench_service, "_get_user_role", return_value="USER")
    mocker.patch.object(workbench_service, "query_group_ids_by_user", return_value=[1])
    skills = mocker.patch.object(workbench_service.skill_db, "get_skill_by_id")
    with pytest.raises(workbench_service.WorkbenchError) as error:
        workbench_service.resolve_workbench_config(_config(3, [{"skill_id": 2}]), tenant_id="tenant", user_id="user")
    assert error.value.status_code == 403
    assert "Secret" not in str(error.value)
    skills.assert_not_called()


def test_ut_be_wb_014_same_tenant_private_skill_is_not_authorized(mocker):
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value={"created_by": "user"})
    mocker.patch.object(workbench_service, "_get_user_role", return_value="USER")
    mocker.patch.object(workbench_service, "query_group_ids_by_user", return_value=[1])
    mocker.patch.object(workbench_service.skill_db, "get_skill_by_id", return_value={"name": "Secret", "created_by": "other", "ingroup_permission": "PRIVATE"})
    with pytest.raises(workbench_service.WorkbenchError) as error:
        workbench_service.resolve_workbench_config(_config(3, [{"skill_id": 2}]), tenant_id="tenant", user_id="user")
    assert error.value.code == "RUNTIME_SKILL_FORBIDDEN"
    assert error.value.status_code == 403
    assert "Secret" not in str(error.value)


def test_preview_revalidates_published_default_skill_before_disclosure(mocker):
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value={"created_by": "user", "enabled": True})
    mocker.patch.object(workbench_service, "get_agent_knowledge_capabilities", return_value={"version_no": 3})
    mocker.patch.object(workbench_service.SkillService, "get_enabled_skills_for_agent", return_value=[{"skill_id": 11, "name": "Secret", "description": "hidden"}])
    mocker.patch.object(workbench_service.skill_db, "get_skill_by_id", return_value={"skill_id": 11, "created_by": "other", "ingroup_permission": "PRIVATE"})
    mocker.patch.object(workbench_service, "_get_user_role", return_value="USER")
    mocker.patch.object(workbench_service, "query_group_ids_by_user", return_value=[])
    with pytest.raises(workbench_service.WorkbenchError) as error:
        workbench_service.build_workbench_capability_preview(agent_id=7, version_no=3, tenant_id="tenant", user_id="user")
    assert error.value.code == "RUNTIME_SKILL_FORBIDDEN"
    assert "Secret" not in str(error.value)


def test_ut_be_wb_024_multi_mounts_never_reach_root_resolver(mocker):
    lookup = mocker.patch.object(workbench_service, "search_agent_info_by_agent_id")
    resolve = mocker.patch.object(workbench_service.RuntimeMountService, "resolve_root")
    config = WorkbenchSessionConfig(mode="multi_agent_chat", agent_mounts=[{"agent_id": 7}, {"agent_id": 8}])
    with pytest.raises(workbench_service.WorkbenchError) as error:
        workbench_service.resolve_workbench_config(config, tenant_id="tenant")
    assert error.value.code == "WORKBENCH_MULTI_AGENT_NOT_SUPPORTED"
    lookup.assert_not_called()
    resolve.assert_not_called()


@pytest.mark.parametrize("definitions", [[], [{"tool_id": 4, "author": "tenant", "is_available": False}], [{"tool_id": 4, "author": "other", "is_available": True}]])
def test_ut_be_wb_015_dependency_unavailability_fails_before_snapshot(mocker, definitions):
    """UT-BE-WB-015: unavailable Tool dependencies cannot form a snapshot."""
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value={"name": "Root"})
    mocker.patch.object(workbench_service.skill_db, "get_skill_by_id", return_value={"name": "Skill", "tool_ids": [4]})
    mocker.patch.object(workbench_service, "query_tools_by_ids", return_value=definitions)
    with pytest.raises(workbench_service.WorkbenchError) as error:
        workbench_service.resolve_workbench_config(_config(3, [{"skill_id": 11}]), tenant_id="tenant")
    assert error.value.code == "RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE"
    assert "other" not in str(error.value)


def test_ut_be_wb_012_shared_tool_parameter_conflicts_fail_before_snapshot(mocker):
    """UT-BE-WB-012: conflicting Tool parameters fail without a partial result."""
    mocker.patch.object(workbench_service, "search_agent_info_by_agent_id", return_value={"name": "Root"})
    mocker.patch.object(workbench_service.skill_db, "get_skill_by_id", return_value={"name": "Skill", "tool_ids": [4], "config_schemas": [{"name": "region", "type": "string"}]})
    mocker.patch.object(workbench_service, "query_tools_by_ids", return_value=[{"tool_id": 4, "author": "tenant", "is_available": True, "params": [{"name": "region"}]}])
    with pytest.raises(workbench_service.WorkbenchError) as error:
        workbench_service.resolve_workbench_config(_config(3, [{"skill_id": 11, "config_values": {"region": "CN"}}, {"skill_id": 12, "config_values": {"region": "US"}}]), tenant_id="tenant")
    assert error.value.code == "RUNTIME_SKILL_TOOL_CONFLICT"
    assert "CN" not in str(error.value)


@pytest.mark.parametrize("value", [-1, 11, float("inf"), float("nan")])
def test_runtime_numeric_config_rejects_nonfinite_and_out_of_range(value):
    with pytest.raises(workbench_service.WorkbenchError):
        workbench_service.resolve_skill_config([{"name": "count", "type": "number", "minimum": 0, "maximum": 10}], {}, {}, {"count": value})
