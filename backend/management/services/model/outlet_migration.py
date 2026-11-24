# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""One-time legacy LLM snapshot construction; database ownership stays in the DAL."""

from copy import deepcopy

from contracts.errors.exceptions import ModelOutletValidationError
from contracts.model import ModelProfilePreviewRequest
from nexent.core.agents.contracts.config import ModelConfig
from nexent.core.model_service.compatibility.legacy_config import legacy_agent_request_parameters, legacy_thinking_enabled
from nexent.core.model_service.profiles.outlet_storage import decode_resolved_model_profile, encode_resolved_model_profile
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.registry import model_service_references
from pydantic import ValidationError
from management.services.model.profiles import build_outlet_draft
from management.services.model.names import add_repo_to_name

MIGRATION_VERSION = "legacy_llm_outlet_v2"


from nexent.core.model_service.compatibility.legacy_outlet import _pointer as _pointer


from nexent.core.model_service.compatibility.legacy_outlet import _leaves as _leaves


from nexent.core.model_service.compatibility.legacy_outlet import _rule as _rule


from nexent.core.model_service.compatibility.legacy_outlet import _parameters as _parameters


def build_legacy_outlet_snapshot(row, *, legacy_capability, migrated_at, from_version="pre-profile"):
    from nexent.core.model_service.compatibility.legacy_outlet import build_legacy_outlet_snapshot as compile_legacy

    return compile_legacy(row, legacy_capability=legacy_capability, migrated_at=migrated_at,
                          from_version=from_version, compose=build_outlet_draft)


def migrate_legacy_outlets(*, dry_run=False, batch_size=100):
    """Process each legacy LLM once per invocation, retaining sanitized failure diagnostics."""
    from datetime import datetime, timezone

    from configs.model_catalog_loader import resolve_reasoning_capability
    from management.db.model.outlets import migrate_legacy_model_records

    migrated_at = datetime.now(timezone.utc).isoformat()

    def construct(record):
        from management.services.model.legacy_snapshot import restore_legacy_outlet_snapshot

        frozen = restore_legacy_outlet_snapshot(record)
        if frozen is not None:
            return frozen
        name = add_repo_to_name(record.get("model_repo") or "", record["model_name"])
        capability = resolve_reasoning_capability(name, record.get("base_url"), record.get("model_factory"),
                                                  allow_gateway_fallback=False)
        return build_legacy_outlet_snapshot(record, legacy_capability=capability, migrated_at=migrated_at)

    results = []
    cursor = 0
    while True:
        batch = migrate_legacy_model_records(construct, registered_references=model_service_references(),
            batch_size=batch_size, after_model_id=cursor, dry_run=dry_run, include_legacy_snapshot=True)
        if not batch:
            break
        results.extend(batch)
        cursor = max(item["model_id"] for item in batch)
    return {"migration_version": MIGRATION_VERSION, "dry_run": dry_run,
            "migrated": sum(item["status"] == "migrated" for item in results),
            "ready": sum(item["status"] == "ready" for item in results),
            "failed": sum(item["status"] == "failed" for item in results), "items": results}
