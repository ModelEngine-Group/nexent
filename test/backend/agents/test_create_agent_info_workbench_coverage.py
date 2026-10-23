from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
import sys
import types

import pytest

from test.backend.agents import test_create_agent_info as legacy


create_agent_info = legacy.create_agent_info_module
WorkbenchError = legacy.WorkbenchError


def test_materialize_runtime_skill_snapshot_writes_frozen_files(tmp_path):
    result = create_agent_info._materialize_runtime_skill_snapshot(
        [
            {
                "name": "demo",
                "files": [
                    ("SKILL.md", b"# Demo"),
                    ("scripts/main.py", b"print('ok')"),
                ],
            }
        ],
        str(tmp_path),
        "tenant-a",
    )

    skill = result[0]
    snapshot_root = tmp_path / ".skill_snapshot"
    assert (snapshot_root / "tenant-a" / "demo" / "SKILL.md").read_bytes() == b"# Demo"
    assert (snapshot_root / "tenant-a" / "demo" / "scripts" / "main.py").is_file()
    assert skill["_snapshot_root"] == str(snapshot_root.resolve())
    assert "files" not in skill


@pytest.mark.parametrize(
    ("tenant_id", "snapshot"),
    [
        ("../outside", [{"name": "demo", "files": []}]),
        ("tenant-a", [{"name": "../demo", "files": []}]),
        ("tenant-a", [{"name": "demo", "files": [("../escape", b"x")]}]),
        ("tenant-a", [{"name": "demo", "files": [("notes.txt", b"x")]}]),
    ],
)
def test_materialize_runtime_skill_snapshot_rejects_unsafe_or_incomplete_input(
    tmp_path, tenant_id, snapshot
):
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE"):
        create_agent_info._materialize_runtime_skill_snapshot(
            snapshot, str(tmp_path), tenant_id
        )


@pytest.mark.asyncio
async def test_create_agent_run_info_forwards_all_workbench_runtime_overrides(monkeypatch):
    import sys

    frozen_snapshot = [{"name": "demo", "_snapshot_root": "/snapshot"}]
    materialize = MagicMock(return_value=frozen_snapshot)
    agent_config = MagicMock(model_name="model")
    agent_config.sandbox_policy = None
    create_config = AsyncMock(return_value=agent_config)
    monkeypatch.setattr(create_agent_info, "_materialize_runtime_skill_snapshot", materialize)
    monkeypatch.setattr(create_agent_info, "_validate_run_minio_files", MagicMock())
    monkeypatch.setattr(
        create_agent_info,
        "join_minio_file_description_to_query",
        AsyncMock(return_value="processed"),
    )
    monkeypatch.setattr(
        create_agent_info, "create_model_config_list", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(create_agent_info, "create_agent_config", create_config)
    monkeypatch.setattr(create_agent_info, "query_current_version_no", lambda **_kwargs: 3)
    monkeypatch.setattr(create_agent_info, "_ensure_agent_reasoning_snapshot", MagicMock())
    monkeypatch.setattr(
        create_agent_info,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(
        create_agent_info, "get_remote_mcp_server_list", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(create_agent_info, "filter_mcp_servers_and_tools", MagicMock(return_value=[]))
    monkeypatch.setattr(create_agent_info, "resolve_tool_user_context", MagicMock(return_value=None))
    monkeypatch.setattr(create_agent_info, "urljoin", MagicMock(return_value="http://mcp"))
    monkeypatch.setattr(create_agent_info.threading, "Event", MagicMock(return_value="stop"))
    agent_service = sys.modules["management.services.agent.service"]
    monkeypatch.setattr(agent_service, "build_sandbox_policy", MagicMock(return_value=None))
    monkeypatch.setattr(agent_service, "get_sandbox_minio_client", MagicMock(return_value=None))

    await create_agent_info.create_agent_run_info(
        agent_id=7,
        minio_files=[],
        query="hello",
        history=[],
        tenant_id="tenant-a",
        user_id="user-a",
        override_model_id=9,
        requested_output_tokens=2048,
        context_policy={"mode": "strict"},
        runtime_knowledge_context={"policy": "knowledge"},
        runtime_skill_snapshot=[{"name": "demo", "files": []}],
        runtime_knowledge_tools=[{"name": "search"}],
        runtime_sub_agent_mounts=[{"agent_id": 8, "version_no": 2}],
    )

    materialize.assert_called_once()
    kwargs = create_config.await_args.kwargs
    assert kwargs["runtime_knowledge_context"] == {"policy": "knowledge"}
    assert kwargs["runtime_skill_snapshot"] is frozen_snapshot
    assert kwargs["override_model_id"] == 9
    assert kwargs["request_requested_output_tokens"] == 2048
    assert kwargs["request_context_policy"] == {"mode": "strict"}
    assert kwargs["runtime_knowledge_tools"] == [{"name": "search"}]
    assert kwargs["runtime_sub_agent_mounts"] == [{"agent_id": 8, "version_no": 2}]


def test_get_skills_for_template_uses_runtime_snapshot_without_repository_lookup():
    result = create_agent_info._get_skills_for_template(
        agent_id=7,
        tenant_id="tenant-a",
        version_no=3,
        runtime_skill_snapshot=[{"name": "demo", "description": "Demo skill"}],
    )

    assert result == [{"name": "demo", "description": "Demo skill"}]


def test_skill_script_tools_remove_mutating_tool_for_runtime_snapshot(monkeypatch):
    class Tool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(create_agent_info, "ToolConfig", Tool)
    tools = create_agent_info._get_skill_script_tools(
        agent_id=7,
        tenant_id="tenant-a",
        version_no=3,
        runtime_skill_snapshot=[
            {
                "name": "demo",
                "config_values": {"format": "pdf"},
                "_snapshot_root": "/snapshot",
            }
        ],
    )

    assert "WriteSkillFileTool" not in {tool.class_name for tool in tools}
    assert len(tools) == 5


def test_root_generation_overlay_skips_children_and_adds_root_alias():
    class Model:
        def __init__(self, cite_name, temperature=0.5, top_p=0.9, extra_body=None):
            self.cite_name = cite_name
            self.temperature = temperature
            self.top_p = top_p
            self.extra_body = extra_body

        def model_copy(self, *, deep, update):
            assert deep is True
            return Model(
                update["cite_name"],
                update["temperature"],
                update["top_p"],
                update["extra_body"],
            )

    child = Model("child")
    root = Model("root", extra_body={"reasoning_effort": "high"})
    models = [child, root]
    config = SimpleNamespace(model_name="root")

    create_agent_info.apply_root_generation_overlay(
        models,
        config,
        {"deep_thinking": False, "temperature": 0.2, "top_p": 0.8},
    )

    assert len(models) == 3
    assert models[-1].cite_name == "workbench_root_model"
    assert models[-1].temperature == 0.2
    assert models[-1].top_p == 0.8
    assert "reasoning_effort" not in models[-1].extra_body
    assert config.model_name == "workbench_root_model"


@pytest.mark.asyncio
async def test_create_agent_config_filters_root_knowledge_tools_before_cycle_check(
    monkeypatch,
):
    root_override = SimpleNamespace(
        tools={"knowledge_search": {"index": "old"}, "custom": {"value": 1}}
    )
    copied_params = SimpleNamespace(agents={"root": root_override})
    normalized = SimpleNamespace(
        agents={"root": root_override},
        model_copy=MagicMock(return_value=copied_params),
    )
    monkeypatch.setattr(
        create_agent_info, "_normalize_tool_params_request", lambda _params: normalized
    )
    monkeypatch.setattr(
        create_agent_info,
        "search_agent_info_by_agent_id",
        lambda **_kwargs: {"name": "root"},
    )
    monkeypatch.setattr(create_agent_info, "query_sub_agent_relations", lambda **_kwargs: [])
    runtime_mount = types.ModuleType("services.runtime_knowledge_mount")
    runtime_mount.MANAGED_CLASSES = {"knowledge_search"}
    monkeypatch.setitem(sys.modules, "services.runtime_knowledge_mount", runtime_mount)

    with pytest.raises(WorkbenchError, match="WORKBENCH_AGENT_CYCLE"):
        await create_agent_info.create_agent_config(
            agent_id=7,
            tenant_id="tenant-a",
            user_id="user-a",
            version_no=3,
            runtime_knowledge_context={"policy": "old"},
            runtime_knowledge_tools=[
                {"name": "knowledge_search", "class_name": "knowledge_search"}
            ],
            runtime_sub_agent_mounts=[{"agent_id": 7, "version_no": 3}],
        )

    normalized.model_copy.assert_called_once_with(deep=True)
    assert root_override.tools == {"custom": {"value": 1}}
