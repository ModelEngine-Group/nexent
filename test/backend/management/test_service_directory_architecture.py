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
    'agent/a2a/adapter.py',
    'agent/a2a/catalog.py',
    'agent/a2a/http_client.py',
    'agent/a2a/nacos.py',
    'agent/a2a/service.py',
    'agent/a2a/validation.py',
    'agent/agentos_events.py',
    'agent/artifacts.py',
    'agent/authorization.py',
    'agent/background.py',
    'agent/background_compatibility.py',
    'agent/context.py',
    'agent/conversation_preparation.py',
    'agent/conversation_submission.py',
    'agent/core_policy.py',
    'agent/creator_run.py',
    'agent/icon.py',
    'agent/management.py',
    'agent/mcp_passthrough.py',
    'agent/model_parameters.py',
    'agent/naming.py',
    'agent/nl2agent.py',
    'agent/nl2agent_callback.py',
    'agent/nl2agent_tools.py',
    'agent/persistence.py',
    'agent/policy.py',
    'agent/preparation/analysis.py',
    'agent/preparation/compiler.py',
    'agent/preparation/evaluation_snapshot.py',
    'agent/preparation/inputs.py',
    'agent/preparation/knowledge_search.py',
    'agent/preparation/langchain_tool.py',
    'agent/preparation/local_tool.py',
    'agent/preparation/model_bindings.py',
    'agent/preparation/request.py',
    'agent/preparation/resources.py',
    'agent/preparation/run.py',
    'agent/preparation/tools.py',
    'agent/prepared_projection.py',
    'agent/prepared_turn.py',
    'agent/preprocessing.py',
    'agent/profile.py',
    'agent/prompt.py',
    'agent/prompt_generation.py',
    'agent/read.py',
    'agent/replay.py',
    'agent/reasoning.py',
    'agent/resource_resolver.py',
    'agent/runtime_client.py',
    'agent/runtime_config.py',
    'agent/service.py',
    'agent/stream.py',
    'agent/system.py',
    'agent/system_initialize.py',
    'agent/system_release.py',
    'agent/tool_identity.py',
    'agent/transfer.py',
    'agent/versions.py',
    'agent/workbench.py',
    'agent/workbench_debug_grant.py',
    'automation/agent_identity.py',
    'automation/agentos_callback.py',
    'automation/capabilities.py',
    'automation/conversation.py',
    'automation/intent.py',
    'automation/intent_parser.py',
    'automation/prompt.py',
    'automation/proposal.py',
    'automation/runner.py',
    'automation/scheduler.py',
    'automation/service.py',
    'configuration/tenant/quotas.py',
    'configuration/tenant/service.py',
    'configuration/tenant/settings.py',
    'configuration/user/memory.py',
    'configuration/user/quotas.py',
    'conversation/agent_history.py',
    'conversation/creation_history.py',
    'conversation/creation_mode.py',
    'conversation/creator_checkpoints.py',
    'conversation/creator_events.py',
    'conversation/creator_execution.py',
    'conversation/creator_histories.py',
    'conversation/creator_replay.py',
    'conversation/creator_runtime.py',
    'conversation/creator_targets.py',
    'conversation/model_preferences.py',
    'conversation/nexent_output.py',
    'conversation/pins.py',
    'conversation/runtime_output.py',
    'conversation/service.py',
    'conversation/sharing.py',
    'evaluation/analysis.py',
    'evaluation/case_generation.py',
    'evaluation/common.py',
    'evaluation/dispatch.py',
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
    'file/cleanse.py',
    'file/cleanse_authorization.py',
    'file/cleanse_cancellation.py',
    'file/cleanse_consumer.py',
    'file/cleanse_execution.py',
    'file/cleanse_executor.py',
    'file/cleanse_jobs.py',
    'file/cleanse_lease.py',
    'file/cleanse_lifespan.py',
    'file/cleanse_release.py',
    'file/cleanse_root.py',
    'file/cleanse_service.py',
    'file/cleanse_worker.py',
    'file/image_content.py',
    'file/image_proxy.py',
    'file/knowledge_artifact_cleanup.py',
    'file/knowledge_cleanse_release.py',
    'file/knowledge_cleanse_service.py',
    'file/local_knowledge_source.py',
    'file/local_source_staging.py',
    'file/office_preview.py',
    'file/preview.py',
    'file/process_cleanse_executor.py',
    'file/run_cleanse_authorization.py',
    'file/run_cleanse_service.py',
    'file/service.py',
    'file/source_finalize.py',
    'file/source_publish.py',
    'file/source_reconcile.py',
    'file/source_recovery.py',
    'file/source_upload.py',
    'file/staged_local_binding.py',
    'file/staged_local_source.py',
    'file/upload.py',
    'file/upload_admission.py',
    'file/upload_quota.py',
    'file/upload_quota_read.py',
    'file/upload_context.py',
    'knowledge_base/admission.py',
    'knowledge_base/catalog_policy.py',
    'knowledge_base/chunk_browser.py',
    'knowledge_base/chunk_creation.py',
    'knowledge_base/chunk_deletion.py',
    'knowledge_base/chunk_payload.py',
    'knowledge_base/chunk_update.py',
    'knowledge_base/chunk_write_authorization.py',
    'knowledge_base/chunks_authorization.py',
    'knowledge_base/collection_authorization.py',
    'knowledge_base/collection_metadata_authorization.py',
    'knowledge_base/creation.py',
    'knowledge_base/document_admission.py',
    'knowledge_base/document_append.py',
    'knowledge_base/document_images.py',
    'knowledge_base/documents.py',
    'knowledge_base/inventory.py',
    'knowledge_base/inventory_records.py',
    'knowledge_base/names.py',
    'knowledge_base/providers/catalog.py',
    'knowledge_base/providers/configuration.py',
    'knowledge_base/quota_rules.py',
    'knowledge_base/quota_read.py',
    'knowledge_base/quota_allocation_read.py',
    'knowledge_base/quota_write.py',
    'knowledge_base/quota_allocation_rules.py',
    'knowledge_base/quota_usage_read.py',
    'knowledge_base/quota_usage.py',
    'knowledge_base/platform_quota.py',
    'knowledge_base/platform_quota_read.py',
    'knowledge_base/usage_projection.py',
    'knowledge_base/quota_authorization.py',
    'knowledge_base/seed_documents.py',
    'knowledge_base/source_reference.py',
    'knowledge_base/summary_metadata.py',
    'knowledge_base/authorization.py',
    'knowledge_base/base_deletion.py',
    'knowledge_base/base_deletion_authorization.py',
    'knowledge_base/base_deletion_coordinator.py',
    'knowledge_base/base_deletion_public.py',
    'knowledge_base/base_metadata.py',
    'knowledge_base/clustering.py',
    'knowledge_base/common.py',
    'knowledge_base/content.py',
    'knowledge_base/content_authorization.py',
    'knowledge_base/deletion.py',
    'knowledge_base/deletion_coordinator.py',
    'knowledge_base/deletion_journal.py',
    'knowledge_base/deletion_public.py',
    'knowledge_base/deletion_selection.py',
    'knowledge_base/deprovision.py',
    'knowledge_base/external_unlink.py',
    'knowledge_base/file_authorization.py',
    'knowledge_base/file_projection.py',
    'knowledge_base/file_reader.py',
    'knowledge_base/file_selection.py',
    'knowledge_base/file_listing.py',
    'knowledge_base/file_source_display.py',
    'knowledge_base/ingestion.py',
    'knowledge_base/ingestion_coordinator.py',
    'knowledge_base/ingestion_dispatch.py',
    'knowledge_base/ingestion_journal.py',
    'knowledge_base/ingestion_selection.py',
    'knowledge_base/legacy_tasks.py',
    'knowledge_base/legacy_migration.py',
    'knowledge_base/legacy_task_archive.py',
    'knowledge_base/legacy_vectors.py',
    'knowledge_base/listing.py',
    'knowledge_base/management.py',
    'knowledge_base/mount.py',
    'knowledge_base/owner_cleanup.py',
    'knowledge_base/permission.py',
    'knowledge_base/runtime_inspection.py',
    'knowledge_base/providers/aidp.py',
    'knowledge_base/providers/datamate.py',
    'knowledge_base/providers/dify.py',
    'knowledge_base/providers/haotian.py',
    'knowledge_base/providers/idata.py',
    'knowledge_base/providers/ragflow.py',
    'knowledge_base/providers/shared_aidp.py',
    'knowledge_base/quota.py',
    'knowledge_base/quota_common.py',
    'knowledge_base/quota_formatting.py',
    'knowledge_base/recommendation.py',
    'knowledge_base/scope.py',
    'knowledge_base/search_authorization.py',
    'knowledge_base/service.py',
    'knowledge_base/source_deletion.py',
    'knowledge_base/source_inspection.py',
    'knowledge_base/storage.py',
    'knowledge_base/summary.py',
    'knowledge_base/summary_coordinator.py',
    'knowledge_base/summary_dispatch.py',
    'knowledge_base/summary_schedule.py',
    'knowledge_base/summary_service.py',
    'knowledge_base/summary_settings.py',
    'knowledge_base/tag_projection.py',
    'knowledge_base/task_state.py',
    'knowledge_base/tool_files.py',
    'knowledge_base/usage.py',
    'knowledge_base/usage_cache.py',
    'mcp/addressing.py',
    'mcp/common.py',
    'mcp/containers.py',
    'mcp/health.py',
    'mcp/openapi.py',
    'mcp/provisioning.py',
    'mcp/registration.py',
    'mcp/service.py',
    'mcp/tools.py',
    'memory/agentos_callback.py',
    'memory/context.py',
    'memory/dreaming/scheduler.py',
    'memory/dreaming/service.py',
    'memory/dreaming/summarizer.py',
    'memory/embedding.py',
    'memory/extraction.py',
    'memory/index.py',
    'memory/ingestion.py',
    'memory/long_term.py',
    'memory/prepared_completion.py',
    'memory/provider.py',
    'memory/providers/configuration.py',
    'memory/providers/plugins.py',
    'memory/providers/service.py',
    'memory/records.py',
    'memory/retrieval.py',
    'model/adapter.py',
    'model/capacity.py',
    'model/catalog.py',
    'model/commands.py',
    'model/creator_snapshot.py',
    'model/invocation.py',
    'model/legacy_snapshot.py',
    'model/management.py',
    'model/media.py',
    'model/names.py',
    'model/outlet_legacy.py',
    'model/outlet_migration.py',
    'model/outlet_projection.py',
    'model/profiles.py',
    'model/reasoning.py',
    'model/resolver.py',
    'model/run_bindings.py',
    'model/run_budget.py',
    'model/run_controls.py',
    'model/runtime_options.py',
    'model/text.py',
    'monitor/audit.py',
    'monitor/identity.py',
    'northbound.py',
    'notification/service.py',
    'permission/api_keys.py',
    'permission/asset_owner.py',
    'permission/identity/authentication.py',
    'permission/identity/cas.py',
    'permission/identity/credentials.py',
    'permission/identity/display.py',
    'permission/identity/gateway_lookup.py',
    'permission/identity/groups.py',
    'permission/identity/invitations.py',
    'permission/identity/northbound.py',
    'permission/identity/oauth.py',
    'permission/identity/registration.py',
    'permission/identity/roles.py',
    'permission/identity/session.py',
    'permission/identity/signatures.py',
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
    'skill/creation.py',
    'skill/files.py',
    'skill/local_config.py',
    'skill/naming.py',
    'skill/nl2skill.py',
    'skill/params.py',
    'skill/permission.py',
    'skill/service.py',
    'skill/stream_parser.py',
    'skill/transfer.py',
    'skill/yaml_cache.py',
    'tag/identity.py',
    'tag/library.py',
    'tag/projection.py',
    'tag/document_projection.py',
    'tag/resources.py',
    'tool/catalog.py',
    'tool/common.py',
    'tool/configuration.py',
    'tool/discovery.py',
    'tool/knowledge_validation.py',
    'tool/langchain.py',
    'tool/text_validation.py',
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
