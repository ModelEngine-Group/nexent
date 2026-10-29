# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Architecture checks for the Management service migration slices."""

import ast
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
MANAGEMENT_SERVICES = BACKEND_ROOT / "management" / "services"

MIGRATED_MODULES = {
    'model/profiles.py',
    'model/outlet_projection.py',
    'agent/creation.py',
    'agent/lifecycle.py',
    'agent/background.py',
    'agent/persistence.py',
    'agent/preparation/compiler.py',
    'agent/preparation/inputs.py',
    'agent/preparation/resources.py',
    'agent/preparation/run.py',
    'agent/preparation/tools.py',
    'agent/preprocessing.py',
    'agent/resource_resolver.py',
    'agent/tool_identity.py',
    'model/run_bindings.py',
    'model/run_budget.py',
    'skill/creation.py',

    'agent/a2a/adapter.py',
    'agent/a2a/catalog.py',
    'agent/a2a/service.py',
    'agent/a2a/validation.py',
    'agent/artifacts.py',
    'agent/authorization.py',
    'agent/context.py',
    'agent/execution.py',
    'agent/icon.py',
    'agent/management.py',
    'agent/naming.py',
    'agent/policy.py',
    'agent/profile.py',
    'agent/prompt.py',
    'agent/prompt_generation.py',
    'agent/read.py',
    'agent/reasoning.py',
    'agent/run.py',
    'agent/run_state.py',
    'agent/runtime_client.py',
    'agent/service.py',
    'agent/stream.py',
    'agent/subscription.py',
    'agent/system.py',
    'agent/transfer.py',
    'agent/versions.py',
    'agent/workbench.py',
    'automation/agent_identity.py',
    'automation/capabilities.py',
    'automation/conversation.py',
    'automation/intent.py',
    'automation/intent_parser.py',
    'automation/prompt.py',
    'automation/proposal.py',
    'automation/runner.py',
    'automation/scheduler.py',
    'automation/service.py',
    'configuration/platform/capacity.py',
    'configuration/tenant/quotas.py',
    'configuration/tenant/service.py',
    'configuration/tenant/settings.py',
    'configuration/user/memory.py',
    'configuration/user/quotas.py',
    'conversation/agent_history.py',
    'conversation/creation_history.py',
    'conversation/pins.py',
    'conversation/service.py',
    'conversation/sharing.py',
    'evaluation/analysis.py',
    'evaluation/case_generation.py',
    'evaluation/common.py',
    'evaluation/evaluators.py',
    'evaluation/execution.py',
    'evaluation/maintenance.py',
    'evaluation/queries.py',
    'evaluation/reporting/fonts.py',
    'evaluation/reporting/report.py',
    'evaluation/runs.py',
    'evaluation/scoring.py',
    'evaluation/sets.py',
    'evaluation/spreadsheet.py',
    'file/access.py',
    'file/image_proxy.py',
    'file/preview.py',
    'file/service.py',
    'file/upload.py',
    'knowledge_base/clustering.py',
    'knowledge_base/common.py',
    'knowledge_base/deletion.py',
    'knowledge_base/files.py',
    'knowledge_base/ingestion.py',
    'knowledge_base/listing.py',
    'knowledge_base/management.py',
    'knowledge_base/mount.py',
    'knowledge_base/permission.py',
    'knowledge_base/providers/aidp.py',
    'knowledge_base/providers/datamate.py',
    'knowledge_base/providers/dify.py',
    'knowledge_base/providers/haotian.py',
    'knowledge_base/providers/idata.py',
    'knowledge_base/providers/ragflow.py',
    'knowledge_base/quota.py',
    'knowledge_base/quota_common.py',
    'knowledge_base/recommendation.py',
    'knowledge_base/scheduler.py',
    'knowledge_base/scope.py',
    'knowledge_base/service.py',
    'knowledge_base/status.py',
    'knowledge_base/storage.py',
    'knowledge_base/summary.py',
    'knowledge_base/tag_projection.py',
    'knowledge_base/task_state.py',
    'knowledge_base/usage.py',
    'mcp/addressing.py',
    'mcp/common.py',
    'mcp/containers.py',
    'mcp/health.py',
    'mcp/openapi.py',
    'mcp/provisioning.py',
    'mcp/registration.py',
    'mcp/service.py',
    'mcp/tools.py',
    'memory/context.py',
    'memory/dreaming/scheduler.py',
    'memory/dreaming/service.py',
    'memory/dreaming/summarizer.py',
    'memory/extraction.py',
    'memory/index.py',
    'memory/ingestion.py',
    'memory/long_term.py',
    'memory/provider.py',
    'memory/providers/configuration.py',
    'memory/providers/plugins.py',
    'memory/providers/service.py',
    'memory/records.py',
    'memory/retrieval.py',
    'model/adapter.py',
    'model/capacity.py',
    'model/catalog.py',
    'model/health.py',
    'model/invocation.py',
    'model/management.py',
    'model/media.py',
    'model/names.py',
    'model/probe.py',
    'model/provider.py',
    'model/providers/base.py',
    'model/providers/dashscope_provider.py',
    'model/providers/modelengine_provider.py',
    'model/providers/openai_provider.py',
    'model/providers/silicon_provider.py',
    'model/providers/tokenpony_provider.py',
    'model/reasoning.py',
    'model/resolver.py',
    'model/run_controls.py',
    'model/text.py',
    'model/voice.py',
    'monitor/audit.py',
    'monitor/identity.py',
    'notification/service.py',
    'permission/api_keys.py',
    'permission/asset_owner.py',
    'permission/identity/authentication.py',
    'permission/identity/provider.py',
    'permission/identity/cas.py',
    'permission/identity/display.py',
    'permission/identity/groups.py',
    'permission/identity/invitations.py',
    'permission/identity/oauth.py',
    'permission/identity/tenants.py',
    'permission/identity/users.py',
    'repository/agent/bundles.py',
    'repository/agent/common.py',
    'repository/agent/icons.py',
    'repository/agent/installation.py',
    'repository/agent/listing.py',
    'repository/agent/official.py',
    'repository/agent/publishing.py',
    'repository/agent/sync.py',
    'repository/mcp/service.py',
    'repository/precheck.py',
    'repository/review_notifications.py',
    'skill/classifier.py',
    'skill/files.py',
    'skill/naming.py',
    'skill/params.py',
    'skill/permission.py',
    'skill/prompt.py',
    'skill/service.py',
    'skill/stream_parser.py',
    'skill/transfer.py',
    'tag/library.py',
    'tag/projection.py',
    'tag/resources.py',
    'tool/catalog.py',
    'tool/common.py',
    'tool/configuration.py',
    'tool/discovery.py',
    'tool/langchain.py',
    'tool/validation.py',
}

LEGACY_MODULE_NAMES = {
    "agent_management_service",
    "agent_naming_service",
    "agent_read_service",
    "agent_run_context",
    "agent_runtime_service",
    "agent_service",
    "knowledge_base_common",
    "knowledge_base_deletion_service",
    "knowledge_base_list_service",
    "knowledge_base_management_service",
    "knowledge_base_permission_service",
    "model_resolver_service",
    "skill_service",
    "skill_support",
    "vectordatabase_service",
}

LEGACY_MODEL_MODULE_NAMES = {
    "model_capacity_suggestion_service",
    "model_gateway_service",
    "model_health_service",
    "model_management_service",
    "model_provider_service",
}

DEFAULT_MODULE_LINE_LIMIT = 1500
MODEL_MODULE_LINE_LIMIT = 1500
MODULE_LINE_LIMITS = {}


def _project_python_files(root):
    """Scan project sources without descending into local Python environments."""
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in {".venv", "venv", "__pycache__"}
            and not (Path(directory) / name / "pyvenv.cfg").is_file()
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(directory) / filename


def test_migrated_management_services_have_single_canonical_location():
    actual_modules = {
        path.relative_to(MANAGEMENT_SERVICES).as_posix()
        for path in MANAGEMENT_SERVICES.rglob("*.py")
        if path.name != "__init__.py"
    }

    assert actual_modules == MIGRATED_MODULES
    assert all(
        not (BACKEND_ROOT / "services" / f"{module_name}.py").exists()
        for module_name in LEGACY_MODULE_NAMES | LEGACY_MODEL_MODULE_NAMES
    )
    assert not list((BACKEND_ROOT / "services" / "providers").rglob("*.py"))


def test_migrated_management_services_stay_within_line_budgets():
    oversized_modules = {
        relative_path: line_count
        for path in MANAGEMENT_SERVICES.rglob("*.py")
        if (line_count := len(path.read_text(encoding="utf-8").splitlines()))
        > (
            MODEL_MODULE_LINE_LIMIT
            if (
                relative_path := path.relative_to(MANAGEMENT_SERVICES).as_posix()
            ).startswith(("model/", "agent/", "skill/", "knowledge_base/"))
            else MODULE_LINE_LIMITS.get(relative_path, DEFAULT_MODULE_LINE_LIMIT)
        )
    }

    assert oversized_modules == {}


def test_source_and_tests_do_not_reference_legacy_module_paths():
    module_pattern = "|".join(
        re.escape(module_name)
        for module_name in sorted(LEGACY_MODULE_NAMES, key=len, reverse=True)
    )
    legacy_reference = re.compile(
        rf"(?<!management\.)(?:backend\.)?services\.({module_pattern})(?![A-Za-z0-9_])"
    )
    unexpected_references = []

    for source_root in (BACKEND_ROOT, PROJECT_ROOT / "sdk", PROJECT_ROOT / "test"):
        for source_file in _project_python_files(source_root):
            if source_file == Path(__file__):
                continue
            if legacy_reference.search(source_file.read_text(encoding="utf-8")):
                unexpected_references.append(
                    source_file.relative_to(PROJECT_ROOT).as_posix()
                )

    assert unexpected_references == []


def test_management_services_do_not_import_runtime_implementation_modules():
    invalid_imports = []

    for source_file in MANAGEMENT_SERVICES.rglob("*.py"):
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported_modules = [node.module or ""]
            else:
                continue

            for imported_module in imported_modules:
                if imported_module.startswith("runtime.services"):
                    invalid_imports.append(f"{source_file.name}: {imported_module}")

    assert invalid_imports == []


def test_agent_services_do_not_restore_test_only_entry_points():
    retired_names = {
        "load_default_agents_json_file",
        "insert_related_agent_impl",
        "get_agent_id_by_name",
        "delete_related_agent_impl",
        "get_runtime_sub_agent_adapter",
        "list_runtime_sub_agent_adapters",
    }
    assert not (MANAGEMENT_SERVICES / "agent/runtime_sub_agent_adapter.py").exists()
    for source_file in (MANAGEMENT_SERVICES / "agent").glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        definitions = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        assert not definitions & retired_names, source_file


def test_agent_shared_types_and_utilities_have_canonical_locations():
    shared_types = {
        "AgentModelProjection", "AgentRunContext", "SystemAgentRef", "WorkbenchReleaseManifest",
        "OptimizeRequest", "OptimizeResult",
    }
    contract = ast.parse((BACKEND_ROOT / "contracts/agent.py").read_text(encoding="utf-8"))
    # The business file also owns the API request models after their migration.
    assert shared_types <= {node.name for node in contract.body if isinstance(node, ast.ClassDef)}
    for source in (MANAGEMENT_SERVICES / "agent").glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        assert not {node.name for node in tree.body if isinstance(node, ast.ClassDef)} & shared_types
    for name in (
        "agent_profile_utils", "agent_stream_utils", "agent_transfer_utils", "context_utils",
        "time_context_utils", "prompt_template_utils", "memory_tool_prompt", "automation_tool_prompt",
        "final_answer_projection", "content_classifier_utils",
    ):
        assert not (BACKEND_ROOT / "utils" / f"{name}.py").exists()


def test_skill_knowledge_utilities_have_canonical_locations():
    for name in ("skill_import_utils", "skill_params_utils", "document_vector_utils", "task_status_utils"):
        assert not (BACKEND_ROOT / "utils" / f"{name}.py").exists()
    assert not (MANAGEMENT_SERVICES / "skill/support.py").exists()
    for source in (BACKEND_ROOT / "management/db").glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("management.services"), source
