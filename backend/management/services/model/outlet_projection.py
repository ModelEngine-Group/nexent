# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Memory-only legacy API views of saved outlets; never recompose or persist projections."""

from nexent.core.model_service.profiles.outlet_storage import ProfileStorageError, decode_resolved_model_profile
from nexent.core.model_service.profiles.request_parameters import apply_extra_api_parameters
from nexent.core.model_service.registry import model_service_references


def project_saved_outlet(row):
    """Return compatible read fields and review state without modifying the stored row."""
    remainder = row.get("resolved_profile")
    if row.get("profile_schema_version") is None:
        if isinstance(remainder, dict) and "migration_error" in remainder:
            return {"migration_status": "failed", "migration_diagnostic": remainder["migration_error"]}
        return None
    try:
        profile = decode_resolved_model_profile(row, registered_references=model_service_references())
    except ProfileStorageError:
        return {"migration_status": "failed", "migration_diagnostic": {"category": "PROFILE_STORAGE_INVALID"}}
    controls = []
    levels = []
    primary = "toggle"
    for control in profile.capabilities.reasoning.controls or []:
        primary = control.mode
        item = {"type": control.mode}
        if control.mode == "effort":
            item["values"] = list(control.values)
            levels = [value for value in control.values if isinstance(value, str)]
        elif control.mode == "budget_tokens":
            item.update(min=control.min, max=control.max)
        controls.append(item)
    params = {key: value for key, value in profile.parameter_values.items()
              if key not in {"temperature", "top_p", "max_output_tokens", "max_tokens"}}
    custom = apply_extra_api_parameters({}, profile.extra_api_parameters)
    if custom:
        params["__custom__"] = custom
    result = {"extra_params": params or None,
        "max_tokens": profile.parameter_values.get("max_output_tokens", profile.capabilities.context.output_limit),
        "reasoning_capability": {"status": profile.capabilities.reasoning.status, "control": primary,
            "levels": levels, "controls": controls, "default": profile.parameter_values.get("reasoning_effort", "auto"),
            "provider_id": profile.identity.provider_id, "matched_model_id": profile.identity.request_model_id,
            "matched_api": profile.connection.base_url, "source": "operator"},
        "profile_schema_version": profile.schema_version, "config_revision": profile.config_revision}
    migration = profile.provenance.provider_metadata.get("migration")
    if isinstance(migration, dict):
        result.update(migration_status="migrated", migration_review_required=
            migration.get("reviewed_revision") != profile.config_revision,
            migration_details={key: migration.get(key) for key in ("from_version", "version", "migrated_at",
                "defaulted_fields", "unmatched_atoms", "unbound_legacy_parameters")})
    return result
