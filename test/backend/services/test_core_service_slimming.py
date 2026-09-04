"""Acceptance regressions for the shared core-service implementations."""

import importlib.util
import io
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def load_source(monkeypatch, relative_path, name):
    """Load the real unit while isolating unrelated application initialization."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def dependency(monkeypatch, name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.mark.parametrize("query,zone,expected", [
    ("hello", None, "hello"),
    ("hello", "invalid/zone", "hello"),
    ("", "UTC", ""),
    ("[Current time: existing] hello", "UTC", "[Current time: existing] hello"),
    ("hello", "Asia/Shanghai", "[Current time: 2026-08-31 08:00:00]\n\nhello"),
])
def test_ac002_prepend_time_compatibility(monkeypatch, query, zone, expected):
    module = load_source(monkeypatch, "backend/utils/time_context_utils.py", "slimming_time")
    assert module.prepend_current_time(
        query, zone, now=datetime(2026, 8, 31, tzinfo=timezone.utc)
    ) == expected


@pytest.mark.parametrize("query,expected", [
    (None, None), ("", ""), ("  hello  ", "  hello  "),
    ("[Current time: incomplete", "[Current time: incomplete"),
    ("[Current time: now]\n\n hello  ", "hello"),
])
def test_ac002_strip_time_compatibility(monkeypatch, query, expected):
    module = load_source(monkeypatch, "backend/utils/time_context_utils.py", "slimming_time")
    assert module.strip_current_time_prefix(query) == expected


def _project_python_files(root):
    """Scan project sources without descending into local Python environments."""
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories
            if name not in {".venv", "venv", "__pycache__"}
            and not (Path(directory) / name / "pyvenv.cfg").is_file()
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(directory) / filename


def test_ac002_preview_key_matches_existing_contract(monkeypatch):
    import hashlib

    module = load_source(monkeypatch, "backend/utils/storage_key_utils.py", "slimming_keys")
    for name in ("a.docx", "folder/中文.pptx", "without-extension", "a.b.c"):
        stem = name.rsplit(".", 1)[0] if "." in name else name
        digest = hashlib.md5(name.encode()).hexdigest()[:8]
        assert module.build_preview_pdf_object_key(name) == f"preview/converted/{stem}_{digest}.pdf"
        assert module.build_preview_pdf_object_key(name, temporary=True) == f"preview/converting/{stem}_{digest}.pdf.tmp"


@pytest.fixture
def naming(monkeypatch):
    dependency(monkeypatch, "consts.const", LANGUAGE={"ZH": "zh", "EN": "en"})
    dependency(monkeypatch, "database.agent_db", query_all_agent_info_by_tenant_id=lambda tenant: [])
    dependency(monkeypatch, "utils.llm_utils", call_llm_for_system_prompt=lambda **kw: "fresh")
    dependency(
        monkeypatch, "utils.prompt_template_utils",
        get_prompt_generate_prompt_template=lambda language: {},
        normalize_prompt_generate_template_content=lambda value: value,
    )
    return load_source(monkeypatch, "backend/management/services/agent/naming.py", "slimming_naming")


@pytest.mark.parametrize("field", ["name", "display_name"])
def test_ac003_duplicate_scope_and_suffix(naming, field):
    agents = [{"agent_id": 1, field: "same"}, {"agent_id": 2, field: "same_1"}]
    assert naming.check_agent_value_duplicate(field, "same", "tenant", agents_cache=agents)
    assert not naming.check_agent_value_duplicate(field, "same", "tenant", 1, agents)
    assert not naming.check_agent_value_duplicate(field, "", "tenant", agents_cache=agents)
    assert naming.generate_unique_agent_value(field, "same", "tenant", agents) == "same_2"
    with pytest.raises(ValueError, match="max attempts"):
        naming.generate_unique_agent_value(field, "same", "tenant", agents, max_suffix_attempts=1)


@pytest.mark.parametrize("field", ["name", "display_name"])
@pytest.mark.parametrize("failure", ["exception", "duplicate", "empty"])
def test_ac003_five_attempts_then_suffix(naming, monkeypatch, field, failure):
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if failure == "exception":
            raise RuntimeError("unavailable")
        return "same" if failure == "duplicate" else ""

    monkeypatch.setattr(naming, "call_llm_for_system_prompt", generate)
    assert naming.regenerate_agent_value(
        field, "same", ["same"], "task", 12, "tenant", agents_cache=[]
    ) == "same_1"
    assert len(calls) == 5
    assert all(call["model_id"] == 12 and call["tenant_id"] == "tenant" for call in calls)


def test_ac003_template_resolution_and_output_normalization(naming, monkeypatch):
    observed = {}

    def resolve(**kwargs):
        observed.update(kwargs)
        return {
            "agent_name_regenerate_system_prompt": "old={{ original_value }}",
            "agent_name_regenerate_user_prompt": "{{ task_description }} {{ existing_values }}",
        }

    dependency(monkeypatch, "services.prompt_template_service", resolve_prompt_generate_template=resolve)
    calls = []
    monkeypatch.setattr(naming, "call_llm_for_system_prompt", lambda **kw: calls.append(kw) or " fresh \nignored")
    assert naming.regenerate_agent_value(
        "name", "old", ["z", "a"], "task", 12, "tenant", user_id="user", prompt_template_id=7
    ) == "fresh"
    assert observed["prompt_template_id"] == 7
    assert observed["user_id"] == "user"
    assert calls[0]["system_prompt"] == "old=old"
    assert calls[0]["user_prompt"] == "task a, z"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "gb18030"])
def test_ac004_strict_text_decoding(monkeypatch, encoding):
    module = load_source(monkeypatch, "sdk/nexent/skills/text_codec.py", "slimming_codec")
    text = "hello 中文" if encoding not in ("utf-16-le", "utf-16-be") else "hello world"
    result = module.decode_skill_text(text.encode(encoding))
    assert str(result) == text
    assert result.encoding


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "C:escape", "C:\\escape", "/escape", "a\x00b"])
def test_ac004_invalid_skill_name(monkeypatch, tmp_path, name):
    module = load_source(monkeypatch, "sdk/nexent/skills/paths.py", "slimming_paths")
    with pytest.raises(module.InvalidSkillNameError):
        module.resolve_skill_path(str(tmp_path), name)


@pytest.mark.parametrize("path", ["../escape", "a/../../escape", "C:escape", "C:\\escape", "/escape", "a\x00b"])
def test_ac004_path_escape(monkeypatch, tmp_path, path):
    module = load_source(monkeypatch, "sdk/nexent/skills/paths.py", "slimming_paths")
    with pytest.raises(module.UnsafeSkillPathError):
        module.resolve_skill_path(str(tmp_path), "skill", path)


def test_ac004_symlink_escape_and_allowed_root(monkeypatch, tmp_path):
    module = load_source(monkeypatch, "sdk/nexent/skills/paths.py", "slimming_paths")
    root = tmp_path / "skills"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "skill").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks requires Windows Developer Mode or elevation")
    with pytest.raises(module.UnsafeSkillPathError):
        module.resolve_skill_path(str(root), "skill", "script.py")
    with pytest.raises(module.UnsafeSkillRootError):
        module.resolve_skill_path(str(outside), "skill", allowed_root=str(root))
    assert module.resolve_skill_path(str(root), "safe", "./scripts\\run.py") == str(root / "safe/scripts/run.py")


@pytest.mark.parametrize("value", [b"hello", "hello", io.BytesIO(b"hello")])
def test_ac005_upload_normalization(monkeypatch, value):
    module = load_source(monkeypatch, "sdk/nexent/skills/upload.py", "slimming_upload")
    assert module.normalize_skill_upload(value) == (b"hello", "md")
    assert module.normalize_skill_upload(b"PKdata") == (b"PKdata", "zip")
    assert module.normalize_skill_upload(b"hello", filename="legacy.zip") == (b"hello", "zip")
    assert module.normalize_skill_upload(b"PKdata", "md") == (b"PKdata", "md")


@pytest.mark.parametrize("enabled,debug", [(False, False), (True, False), (False, True), (True, True)])
def test_ac008_shared_run_preparation(monkeypatch, enabled, debug):
    calls = []
    dependency(monkeypatch, "nexent.monitor", AgentRunMetadata=types.SimpleNamespace)

    def memory(*args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(user_config=types.SimpleNamespace(memory_switch=enabled, agent_share_option="private"))

    dependency(monkeypatch, "services.memory_config_service", build_memory_context=memory)
    dependency(monkeypatch, "utils.monitoring", monitoring_manager=types.SimpleNamespace(bind_agent_context=lambda value: value))
    module = load_source(monkeypatch, "backend/management/services/agent/run_context.py", "slimming_run_context")
    request = types.SimpleNamespace(
        agent_id=3, conversation_id=4, query="hello", is_debug=debug, history=[1, 2], minio_files=[]
    )
    context = module.build_agent_run_context(request, "user", "tenant", "en", extra_metadata={"background": True})
    assert context.enable_memory is (enabled and not debug)
    assert calls == [(("user", "tenant", 3), {"skip_query": debug})]
    assert context.metadata.memory_enabled is enabled
    assert context.metadata.history_count == 2
    assert context.metadata.minio_files_count == 0
    assert context.metadata.extra_metadata == {"agent_share_option": "private", "background": True}


@pytest.fixture
def model_resolver(monkeypatch):
    status = types.SimpleNamespace(
        AVAILABLE=types.SimpleNamespace(value="available"), get_value=lambda value: value or "not_detected"
    )
    dependency(monkeypatch, "consts.model", ModelConnectStatusEnum=status)
    dependency(
        monkeypatch, "database.model_management_db",
        get_model_by_model_id=lambda *args: None, get_model_records=lambda *args: [],
        get_model_by_model_id_ignore_delete=lambda *args: None,
        get_valid_model_ids=lambda ids, tenant: [mid for mid in ids if mid != 9],
    )
    dependency(monkeypatch, "services.model_gateway_service", build_adapter_fresh=lambda *args: args)
    dependency(
        monkeypatch, "utils.config_utils",
        tenant_config_manager=types.SimpleNamespace(get_model_config=lambda **kwargs: {}),
    )
    return load_source(monkeypatch, "backend/management/services/model/resolver.py", "management.services.model.resolver")


@pytest.mark.parametrize("kind,slot", [("embedding", "embedding"), ("multi_embedding", "multiEmbedding")])
def test_ac006_embedding_adapter_contract(model_resolver, monkeypatch, kind, slot):
    record = {"model_id": 7, "model_name": "model", "model_type": kind, "model_factory": "vendor"}
    calls = []
    monkeypatch.setattr(model_resolver, "get_model_by_model_id", lambda *args: calls.append(args) or record)
    adapter, model_id = model_resolver.get_embedding_model_by_id("tenant", 7)
    config, modality, selected_slot, adapter_tenant = adapter
    assert model_id == 7
    assert calls == [(7, "tenant")]
    assert (modality, selected_slot, adapter_tenant) == (kind, slot, None)
    assert config["model_factory"] == "vendor"
    assert config["max_tokens"] == 1024
    assert config["ssl_verify"] is True


@pytest.mark.parametrize("record", [None, {}, {"model_type": "llm"}])
def test_ac006_missing_or_wrong_embedding_model(model_resolver, monkeypatch, record):
    monkeypatch.setattr(model_resolver, "get_model_by_model_id", lambda *args: record)
    assert model_resolver.get_embedding_model_by_id("tenant", 7) == (None, None)


def test_ac006_catalog_failure_and_capability_single_lookup(model_resolver, monkeypatch):
    calls = []
    monkeypatch.setattr(model_resolver, "get_model_by_model_id", lambda *args: calls.append(args) or {
        "model_type": "multi_embedding", "display_name": "Multi",
    })
    descriptor = model_resolver.get_model_descriptor(7, "tenant")
    assert descriptor.display_name == "Multi"
    assert descriptor.is_multimodal is True
    assert calls == [(7, "tenant")]
    cache = {}
    model_resolver.resolve_model_record(7, "tenant", cache)
    model_resolver.resolve_model_record(7, "tenant", cache)
    assert len(calls) == 2

    def fail(*args):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(model_resolver, "get_model_by_model_id", fail)
    assert model_resolver.get_model_descriptor(8, "tenant").is_multimodal is False
    assert model_resolver.get_embedding_model_by_id("tenant", 8) == (None, None)


@pytest.fixture
def agent_reader(monkeypatch, model_resolver):
    dependency(monkeypatch, "database.agent_db", search_agent_info_by_agent_id=lambda *args: None)
    dependency(
        monkeypatch, "database.tool_db", search_tools_for_sub_agent=lambda **kwargs: [],
        check_tool_is_available=lambda ids: [True] * len(ids),
    )
    load_source(monkeypatch, "backend/consts/agent_unavailable_reasons.py", "consts.agent_unavailable_reasons")
    return load_source(monkeypatch, "backend/management/services/agent/read.py", "slimming_agent_reader")


def test_ac007_projection_keeps_distinct_legacy_name_rules(agent_reader, monkeypatch, model_resolver):
    records = {1: {"display_name": None}, 2: {"display_name": "Second"}}
    monkeypatch.setattr(model_resolver, "get_model_by_model_id", lambda mid, *args: records.get(mid))
    data = {"model_ids": [1, 9, 2, 2]}
    listed = agent_reader.project_agent_models(data, "tenant", {})
    detail = agent_reader.project_agent_models(data, "tenant", detail=True)
    assert listed.fields["model_ids"] == detail.fields["model_ids"] == [1, 2, 2]
    assert listed.fields["model_names"] == detail.fields["model_names"] == ["Second", "Second"]
    assert listed.fields["model_name"] == "Second"
    assert detail.fields["model_name"] is None
    assert listed.deleted_model_ids == detail.deleted_model_ids == frozenset({9})


def test_ac010_deleted_model_reason_is_added_once(agent_reader):
    ok, reasons = agent_reader.apply_deleted_model_reason(
        False,
        [agent_reader.AgentUnavailableReason.MODEL_NOT_CONFIGURED],
        frozenset({9}),
    )
    assert ok is False
    assert reasons == [
        agent_reader.AgentUnavailableReason.MODEL_NOT_CONFIGURED,
        agent_reader.AgentUnavailableReason.MODEL_DELETED,
    ]
    _, repeated = agent_reader.apply_deleted_model_reason(False, reasons, frozenset({9}))
    assert repeated.count(agent_reader.AgentUnavailableReason.MODEL_DELETED) == 1


def test_ac012_knowledge_list_merge_uses_one_compatible_executor(monkeypatch):
    dependency(monkeypatch, "consts.const", PERMISSION_READ="READ_ONLY")
    module = load_source(
        monkeypatch,
        "backend/management/services/knowledge_base/listing.py",
        "slimming_knowledge_list",
    )
    primary = {
        "indices": ["tenant"],
        "count": 1,
        "total": 1,
        "indices_info": [{"name": "tenant", "update_time": "2026-02", "permission": "EDIT"}],
        "facets": {"sources": ["local"], "models": ["m1"]},
    }
    asset = {
        "indices": ["asset"],
        "count": 1,
        "total": 1,
        "indices_info": [{"name": "asset", "update_time": "2026-01", "permission": "EDIT"}],
        "facets": {"sources": ["official"], "models": ["m2"]},
    }
    merged = module.merge_list_indices_results(primary, asset)
    assert merged["indices"] == ["tenant", "asset"]
    assert merged["indices_info"][1]["permission"] == "READ_ONLY"
    paged = module.merge_paginated_list_indices_results(primary, asset, 0, 1)
    assert paged["indices"] == ["tenant"]
    assert paged["total"] == 2
    assert paged["next_offset"] == 1
    assert paged["facets"] == {"sources": ["local", "official"], "models": ["m1", "m2"]}


def test_ac012_permission_requirements_share_resolver(monkeypatch):
    dependency(
        monkeypatch,
        "consts.const",
        ASSET_OWNER_TENANT_ID="asset",
        IS_SPEED_MODE=False,
        PERMISSION_EDIT="EDIT",
    )
    dependency(monkeypatch, "database.knowledge_db", get_knowledge_record=lambda query: {})
    dependency(monkeypatch, "database.group_db", query_group_ids_by_user=lambda user_id: [])
    dependency(monkeypatch, "database.user_tenant_db", get_user_tenant_by_user_id=lambda user_id: {})
    dependency(monkeypatch, "permissions.models", Resource=object)
    dependency(monkeypatch, "permissions.dac", ResourceAccessControl=object)
    module = load_source(
        monkeypatch,
        "backend/management/services/knowledge_base/permission.py",
        "slimming_knowledge_permission",
    )
    monkeypatch.setattr(module, "resolve_knowledge_base_permission", lambda *args: "READ_ONLY")
    assert module.require_knowledge_base_read_permission("kb", "user") == "READ_ONLY"
    with pytest.raises(PermissionError, match="modify"):
        module.require_knowledge_base_edit_permission("kb", "user")
    monkeypatch.setattr(module, "resolve_knowledge_base_permission", lambda *args: "CREATOR")
    assert module.require_knowledge_base_edit_permission("kb", "user") == "CREATOR"


@pytest.mark.parametrize("configured,available", [(False, False), (True, False), (True, True)])
def test_ac007_availability_uses_real_shared_model_predicate(agent_reader, model_resolver, monkeypatch, configured, available):
    monkeypatch.setattr(model_resolver, "get_model_by_model_id", lambda *args: {
        "connect_status": "available" if available else "unavailable"
    })
    ok, reasons = agent_reader.check_agent_availability(
        1, "tenant", {"agent_id": 1, "model_ids": [7] if configured else []}
    )
    assert ok is (configured and available)
    expected = [] if ok else [
        agent_reader.AgentUnavailableReason.MODEL_UNAVAILABLE if configured
        else agent_reader.AgentUnavailableReason.MODEL_NOT_CONFIGURED
    ]
    assert reasons == expected


def test_ac007_deleted_tool_model_and_duplicate_order(agent_reader, monkeypatch):
    monkeypatch.setattr(agent_reader, "get_model_by_model_id_ignore_delete", lambda *args: {"delete_flag": "Y"})
    assert agent_reader.tool_has_deleted_model({"params": [{"name": "selected_model_id", "default": 7}]}, "tenant")
    assert not agent_reader.tool_has_deleted_model({"params": "invalid"}, "tenant")
    entries = [
        {"raw_agent": {"name": "same", "create_time": time}, "unavailable_reasons": []}
        for time in (2, 1)
    ]
    agent_reader.apply_duplicate_name_availability_rules(entries)
    assert entries[0]["unavailable_reasons"] == [agent_reader.AgentUnavailableReason.DUPLICATE_NAME]
    assert entries[1]["unavailable_reasons"] == []


def test_ac016_management_services_are_grouped_by_business_package():
    services_root = ROOT / "backend" / "management" / "services"
    root_modules = sorted(path.name for path in services_root.glob("*.py"))
    business_packages = sorted(
        path.name
        for path in services_root.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )

    assert root_modules == ["__init__.py"]
    assert business_packages == ["agent", "knowledge_base", "model", "skill"]
    assert all((services_root / package / "__init__.py").is_file() for package in business_packages)


def test_ac017_repository_has_no_flat_management_service_references():
    flat_modules = [
        "agent" + suffix
        for suffix in (
            "_service",
            "_management_service",
            "_naming_service",
            "_read_service",
            "_run_context",
            "_run_service",
        )
    ]
    flat_modules.extend(
        ["skill" + "_service", "skill" + "_support_service", "vectordatabase" + "_service"]
    )
    flat_modules.extend(
        "knowledge_base" + suffix
        for suffix in (
            "_common",
            "_deletion_service",
            "_list_service",
            "_management_service",
            "_permission_service",
        )
    )
    flat_modules.append("model" + "_resolver_service")
    stale_prefixes = tuple(f"management.services.{name}" for name in flat_modules)

    checked_roots = (ROOT / "backend", ROOT / "sdk", ROOT / "test")
    stale_references = []
    for checked_root in checked_roots:
        for path in _project_python_files(checked_root):
            content = path.read_text(encoding="utf-8-sig")
            for stale_prefix in stale_prefixes:
                if stale_prefix in content:
                    stale_references.append(f"{path.relative_to(ROOT)}: {stale_prefix}")

    assert stale_references == []
