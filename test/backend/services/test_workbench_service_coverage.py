from types import SimpleNamespace

import pytest

from consts.exceptions import ValidationError, WorkbenchError
from consts.model import WorkbenchSessionConfig
from services import workbench_service


def _config(**updates):
    payload = {
        "mode": "single_agent_chat",
        "agent_mounts": [{"agent_id": 7, "version_no": 3}],
        "skill_mounts": [],
    }
    payload.update(updates)
    return WorkbenchSessionConfig.model_validate(payload)


def _resolve_dependencies(monkeypatch, snapshot=None):
    monkeypatch.setattr(
        workbench_service.system_agent_provider,
        "get_workbench_main_ref",
        lambda _tenant: SimpleNamespace(agent_id=99, version_no=4),
    )
    monkeypatch.setattr(
        workbench_service,
        "search_agent_info_by_agent_id",
        lambda agent_id, *_args: snapshot
        or {"agent_id": agent_id, "name": f"Agent {agent_id}", "enabled": True},
    )
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 3)
    monkeypatch.setattr(
        workbench_service.skill_db, "search_skills_for_agent", lambda **_kwargs: []
    )


def test_capture_skill_snapshot_requires_directory(monkeypatch):
    monkeypatch.setattr(
        workbench_service.SkillService,
        "load_skill_directory",
        lambda *_args, **_kwargs: {},
    )

    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE"):
        workbench_service._capture_skill_file_snapshot("demo", "tenant-a")


def test_capture_skill_snapshot_rejects_directory_outside_temp(monkeypatch, tmp_path):
    directory = tmp_path / "ordinary"
    directory.mkdir()
    monkeypatch.setattr(
        workbench_service.SkillService,
        "load_skill_directory",
        lambda *_args, **_kwargs: {"directory": str(directory)},
    )
    monkeypatch.setattr(workbench_service.tempfile, "gettempdir", lambda: str(tmp_path))

    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE"):
        workbench_service._capture_skill_file_snapshot("demo", "tenant-a")


def test_capture_skill_snapshot_returns_files_and_cleans_source(monkeypatch, tmp_path):
    directory = tmp_path / "skill_demo_123"
    directory.mkdir()
    (directory / "SKILL.md").write_text("# Demo", encoding="utf-8")
    (directory / "reference.txt").write_bytes(b"reference")
    monkeypatch.setattr(
        workbench_service.SkillService,
        "load_skill_directory",
        lambda *_args, **_kwargs: {"directory": str(directory)},
    )
    monkeypatch.setattr(workbench_service.tempfile, "gettempdir", lambda: str(tmp_path))

    snapshot = workbench_service._capture_skill_file_snapshot("demo", "tenant-a")

    assert dict(snapshot) == {"SKILL.md": b"# Demo", "reference.txt": b"reference"}
    assert not directory.exists()


def test_capture_skill_snapshot_requires_manifest_and_still_cleans(monkeypatch, tmp_path):
    directory = tmp_path / "skill_demo_456"
    directory.mkdir()
    (directory / "notes.txt").write_text("notes", encoding="utf-8")
    monkeypatch.setattr(
        workbench_service.SkillService,
        "load_skill_directory",
        lambda *_args, **_kwargs: {"directory": str(directory)},
    )
    monkeypatch.setattr(workbench_service.tempfile, "gettempdir", lambda: str(tmp_path))

    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE"):
        workbench_service._capture_skill_file_snapshot("demo", "tenant-a")
    assert not directory.exists()


def test_capture_skill_snapshot_rejects_oversized_payload(monkeypatch, tmp_path):
    directory = tmp_path / "skill_demo_oversized"
    directory.mkdir()
    (directory / "SKILL.md").write_bytes(b"x")
    monkeypatch.setattr(
        workbench_service.SkillService,
        "load_skill_directory",
        lambda *_args, **_kwargs: {"directory": str(directory)},
    )
    monkeypatch.setattr(workbench_service.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(workbench_service, "_MAX_SKILL_SNAPSHOT_BYTES", 0)

    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE"):
        workbench_service._capture_skill_file_snapshot("demo", "tenant-a")


@pytest.mark.parametrize(
    ("schemas", "runtime"),
    [
        ([{"name": "required", "type": "string", "required": True}], {}),
        ([{"name": "count", "type": "integer"}], {"count": True}),
        ([{"name": "choice", "type": "string", "enum": ["a"]}], {"choice": "b"}),
        ([{"name": "score", "type": "number"}], {"score": float("inf")}),
        ([{"name": "score", "type": "number", "minimum": 1}], {"score": 0}),
        ([{"name": "score", "type": "number", "maximum": 1}], {"score": 2}),
    ],
)
def test_resolve_skill_config_rejects_invalid_values(schemas, runtime):
    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_CONFIG_INVALID"):
        workbench_service.resolve_skill_config(schemas, {}, {}, runtime)


def test_resolve_skill_config_applies_default_and_ignores_empty_optional():
    result = workbench_service.resolve_skill_config(
        [
            {"name": "mode", "type": "string", "default": "safe"},
            {"name": "note", "type": "string"},
        ],
        {},
        {},
        {"note": ""},
    )

    assert result == {"mode": "safe", "note": ""}


def test_resolve_workbench_rejects_creation_mode():
    config = _config().model_copy(update={"mode": "skill_create"})
    with pytest.raises(WorkbenchError, match="WORKBENCH_MODE_RESOURCE_CONFLICT"):
        workbench_service.resolve_workbench_config(config, tenant_id="tenant-a")


def test_resolve_workbench_rejects_unpublished_agent(monkeypatch):
    _resolve_dependencies(monkeypatch)
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 0)

    with pytest.raises(WorkbenchError, match="AGENT_VERSION_UNAVAILABLE"):
        workbench_service.resolve_workbench_config(_config(), tenant_id="tenant-a")


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        ({"agent_id": 7, "enabled": False}, "AGENT_NOT_RUNNABLE"),
        ({"agent_id": 7, "enabled": True, "system_key": "reserved"}, "AGENT_NOT_RUNNABLE"),
    ],
)
def test_resolve_workbench_rejects_disabled_or_system_child(monkeypatch, snapshot, message):
    _resolve_dependencies(monkeypatch, snapshot=snapshot)

    with pytest.raises(WorkbenchError, match=message):
        workbench_service.resolve_workbench_config(_config(), tenant_id="tenant-a")


def test_resolve_workbench_maps_missing_system_root(monkeypatch):
    _resolve_dependencies(monkeypatch)
    monkeypatch.setattr(
        workbench_service.system_agent_provider,
        "get_workbench_main_ref",
        lambda _tenant: (_ for _ in ()).throw(RuntimeError("missing")),
    )

    with pytest.raises(WorkbenchError, match="WORKBENCH_SYSTEM_AGENT_UNAVAILABLE"):
        workbench_service.resolve_workbench_config(_config(), tenant_id="tenant-a")


def test_resolve_workbench_rejects_disabled_system_root(monkeypatch):
    _resolve_dependencies(monkeypatch)
    monkeypatch.setattr(
        workbench_service,
        "search_agent_info_by_agent_id",
        lambda agent_id, *_args: {
            "agent_id": agent_id,
            "name": "Root",
            "enabled": agent_id != 99,
        },
    )

    with pytest.raises(WorkbenchError, match="WORKBENCH_SYSTEM_AGENT_UNAVAILABLE"):
        workbench_service.resolve_workbench_config(_config(), tenant_id="tenant-a")


def test_resolve_workbench_rejects_unavailable_model(monkeypatch):
    _resolve_dependencies(monkeypatch)
    monkeypatch.setattr(workbench_service, "get_model_by_model_id", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(workbench_service, "is_model_available", lambda _model: False)

    with pytest.raises(WorkbenchError, match="WORKBENCH_MODEL_NOT_ALLOWED"):
        workbench_service.resolve_workbench_config(
            _config(model_id=8), tenant_id="tenant-a"
        )


def test_capability_preview_rejects_missing_published_version(monkeypatch):
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 0)

    with pytest.raises(WorkbenchError, match="AGENT_VERSION_UNAVAILABLE"):
        workbench_service.build_workbench_capability_preview(
            agent_id=7, version_no=None, tenant_id="tenant-a", user_id="user-a"
        )


def test_capability_preview_rejects_empty_capability_version(monkeypatch):
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 3)
    monkeypatch.setattr(
        workbench_service,
        "search_agent_info_by_agent_id",
        lambda *_args: {"agent_id": 7, "created_by": "user-a", "enabled": True},
    )
    monkeypatch.setattr(
        workbench_service,
        "get_agent_knowledge_capabilities",
        lambda **_kwargs: {"version_no": 0},
    )
    monkeypatch.setattr(workbench_service, "_get_user_role", lambda _user_id: "USER")

    with pytest.raises(ValidationError, match="no published version"):
        workbench_service.build_workbench_capability_preview(
            agent_id=7, version_no=3, tenant_id="tenant-a", user_id="user-a"
        )


def test_capability_preview_rejects_inaccessible_default_skill(monkeypatch):
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 3)
    monkeypatch.setattr(
        workbench_service,
        "search_agent_info_by_agent_id",
        lambda *_args: {"agent_id": 7, "created_by": "user-a", "enabled": True},
    )
    monkeypatch.setattr(
        workbench_service,
        "get_agent_knowledge_capabilities",
        lambda **_kwargs: {"version_no": 3},
    )
    monkeypatch.setattr(
        workbench_service.SkillService,
        "get_enabled_skills_for_agent",
        lambda *_args, **_kwargs: [{"skill_id": 11}],
    )
    monkeypatch.setattr(workbench_service.skill_db, "get_skill_by_id", lambda *_args: None)
    monkeypatch.setattr(workbench_service, "_get_user_role", lambda _user_id: "USER")
    monkeypatch.setattr(workbench_service, "query_group_ids_by_user", lambda _user_id: [])

    with pytest.raises(WorkbenchError, match="RUNTIME_SKILL_FORBIDDEN"):
        workbench_service.build_workbench_capability_preview(
            agent_id=7, version_no=3, tenant_id="tenant-a", user_id="user-a"
        )


def test_capability_preview_maps_missing_snapshot(monkeypatch):
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 3)
    monkeypatch.setattr(
        workbench_service,
        "search_agent_info_by_agent_id",
        lambda *_args: (_ for _ in ()).throw(ValueError("missing")),
    )

    with pytest.raises(WorkbenchError, match="AGENT_VERSION_UNAVAILABLE"):
        workbench_service.build_workbench_capability_preview(
            agent_id=7, version_no=3, tenant_id="tenant-a", user_id="user-a"
        )


def test_capability_preview_rejects_disabled_agent(monkeypatch):
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 3)
    monkeypatch.setattr(
        workbench_service,
        "search_agent_info_by_agent_id",
        lambda *_args: {"agent_id": 7, "created_by": "user-a", "enabled": False},
    )
    monkeypatch.setattr(workbench_service, "_get_user_role", lambda _user_id: "USER")

    with pytest.raises(WorkbenchError, match="AGENT_NOT_RUNNABLE"):
        workbench_service.build_workbench_capability_preview(
            agent_id=7, version_no=3, tenant_id="tenant-a", user_id="user-a"
        )


def test_capability_preview_returns_authorized_defaults(monkeypatch):
    monkeypatch.setattr(workbench_service, "resolve_root_version", lambda *_args: 3)
    monkeypatch.setattr(
        workbench_service,
        "search_agent_info_by_agent_id",
        lambda *_args: {"agent_id": 7, "created_by": "user-a", "enabled": True},
    )
    monkeypatch.setattr(
        workbench_service,
        "get_agent_knowledge_capabilities",
        lambda **_kwargs: {"version_no": 3, "local": {"enabled": True}},
    )
    monkeypatch.setattr(
        workbench_service.SkillService,
        "get_enabled_skills_for_agent",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(workbench_service, "_get_user_role", lambda _user_id: "USER")
    monkeypatch.setattr(workbench_service, "query_group_ids_by_user", lambda _user_id: [])

    result = workbench_service.build_workbench_capability_preview(
        agent_id=7, version_no=3, tenant_id="tenant-a", user_id="user-a"
    )

    assert result["agent_id"] == 7
    assert result["version_no"] == 3
    assert result["default_skill_mounts"] == []
    assert result["knowledge"]["local"]["enabled"] is True


def test_attach_runtime_knowledge_tree_returns_immutable_copy():
    identity = workbench_service.RuntimeAgentIdentity(
        runtime_ref="agent:7:v3",
        agent_id=7,
        version_no=3,
        invocation_name="root",
        display_name="Root",
        origin="PERSISTED",
    )
    plan = workbench_service.ResolvedAgentPlan(
        root=workbench_service.PublishedRootDescriptor(
            identity=identity,
            published_snapshot={"agent_id": 7},
        ),
        overlay=workbench_service.RootRuntimeOverlay(None, None, (), None),
        root_skills=(),
        child_mounts=(),
    )
    knowledge_tree = [{"agent_id": 7, "tools": [{"name": "search"}]}]

    updated = workbench_service.attach_runtime_knowledge_tree(plan, knowledge_tree)

    knowledge_tree[0]["tools"].append({"name": "changed"})
    assert len(updated.knowledge_tree[0]["tools"]) == 1
    assert plan.knowledge_tree == ()


def test_resolve_skill_mounts_deduplicates_published_instances(monkeypatch):
    monkeypatch.setattr(
        workbench_service.skill_db,
        "get_skill_by_id",
        lambda *_args: {
            "skill_id": 1,
            "name": "demo",
            "description": "Demo",
            "tool_ids": [],
        },
    )
    monkeypatch.setattr(
        workbench_service,
        "_capture_skill_file_snapshot",
        lambda *_args: (("SKILL.md", b"# Demo"),),
    )

    result = workbench_service._resolve_skill_mounts(
        (),
        "tenant-a",
        ({"skill_id": 1}, {"skill_id": 1}),
    )

    assert len(result) == 1


def test_resolve_skill_mounts_skips_unrelated_tool_values(monkeypatch):
    skills = {
        1: {"skill_id": 1, "name": "one", "tool_ids": [11]},
        2: {"skill_id": 2, "name": "two", "tool_ids": [12]},
    }
    monkeypatch.setattr(
        workbench_service.skill_db,
        "get_skill_by_id",
        lambda skill_id, _tenant: skills[skill_id],
    )
    monkeypatch.setattr(
        workbench_service,
        "_capture_skill_file_snapshot",
        lambda *_args: (("SKILL.md", b"# Demo"),),
    )
    monkeypatch.setattr(
        workbench_service,
        "query_tools_by_ids",
        lambda _ids: [
            {"tool_id": 11, "author": "tenant-a", "is_available": True, "params": []},
            {"tool_id": 12, "author": "tenant-a", "is_available": True, "params": []},
        ],
    )

    result = workbench_service._resolve_skill_mounts(
        ({"skill_id": 1}, {"skill_id": 2}), "tenant-a"
    )

    assert [skill.skill_id for skill in result] == [1, 2]
