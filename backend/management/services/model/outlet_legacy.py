# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Translate old LLM configuration payloads at the service boundary only."""

from copy import deepcopy
from datetime import UTC, datetime

from contracts.errors.exceptions import ModelOutletValidationError


def create_legacy_llm_outlet(model_data, user_id, tenant_id):
    """Save an old create request as a complete outlet; never insert a legacy row."""
    from configs.model_catalog_loader import resolve_reasoning_capability
    from management.db.model.outlets import create_resolved_model_record
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
    from nexent.core.model_service.registry import model_service_references
    from management.services.model.outlet_migration import build_legacy_outlet_snapshot
    from management.services.model.names import add_repo_to_name

    row = {**deepcopy(model_data), "model_id": 1, "tenant_id": tenant_id}
    name = add_repo_to_name(row.get("model_repo") or "", row["model_name"])
    capability = resolve_reasoning_capability(name, row.get("base_url"), row.get("model_factory"))
    profile = build_legacy_outlet_snapshot(row, legacy_capability=capability,
        migrated_at=datetime.now(UTC).isoformat())
    data = profile.model_dump(mode="json")
    data["outlet_id"] = None
    data["connection"]["credential_ref"]["model_id"] = None
    # This is a newly created outlet, not a migrated historical record.
    data["provenance"]["provider_metadata"].pop("migration", None)
    return create_resolved_model_record(ResolvedModelProfile.model_validate(data), user_id, tenant_id,
        registered_references=model_service_references(), api_key=model_data.get("api_key"),
        connect_status=model_data.get("connect_status") or "not_detected")


def update_legacy_llm_outlet(record, changes, user_id, tenant_id):
    """Translate partial old updates using saved rules, without consulting current TOML."""
    from contracts.model import ModelOutletPatchRequest
    from nexent.core.agents.agent_model import ModelConfig
    from nexent.core.model_service.profiles.outlet_storage import (
        decode_resolved_model_profile,
    )
    from nexent.core.model_service.registry import model_service_references
    from management.services.model.outlet_migration import _leaves
    from management.services.model.profiles import update_model_outlet
    from management.services.model.names import add_repo_to_name

    if not record.get("profile_schema_version"):
        return _repair_legacy_outlet(record, changes, user_id, tenant_id)
    profile = decode_resolved_model_profile(record, registered_references=model_service_references())
    if "model_name" in changes:
        name = add_repo_to_name(changes.get("model_repo") or "", changes["model_name"])
        if name != profile.identity.request_model_id:
            raise ModelOutletValidationError("OUTLET_IDENTITY_IMMUTABLE", "/model_name")
    if changes.get("model_factory", profile.identity.provider_id) != profile.identity.provider_id:
        raise ModelOutletValidationError("OUTLET_IDENTITY_IMMUTABLE", "/model_factory")
    values = {key: changes[key] for key in ("temperature", "top_p") if key in changes}
    extra = changes.get("extra_params")
    if "extra_params" in changes and extra is not None and not isinstance(extra, dict):
        raise ModelOutletValidationError()
    if extra is not None:
        values.update({key: value for key, value in extra.items() if key != "__custom__"})
    if "max_output_tokens" in changes or "max_tokens" in changes:
        config = ModelConfig(cite_name=profile.identity.display_name, model_name=profile.identity.request_model_id,
            url=profile.connection.base_url, max_output_tokens=changes.get("max_output_tokens"),
            max_tokens=changes.get("max_tokens"))
        values["max_output_tokens"] = config.max_output_tokens
    patch = {"expected_revision": changes.get("config_revision", profile.config_revision), "parameter_values": values}
    for field in ("display_name", "api_key"):
        if field in changes:
            patch[field] = changes[field]
    connection = {key: changes[key] for key in ("base_url", "ssl_verify", "timeout_seconds", "concurrency_limit")
                  if key in changes}
    if connection:
        patch["connection"] = connection
    if "extra_params" in changes:
        extra = extra or {}
        raw_custom = extra.get("__custom__")
        if raw_custom is None:
            raw_custom = {}
        if not isinstance(raw_custom, dict):
            raise ModelOutletValidationError()
        patch["extra_api_parameters"] = [{"path": path, "value": value} for path, value in _leaves(raw_custom)]
        # The old extra_params field is a replacement bag, unlike the new PATCH contract.
        previous_extra_keys = set(profile.parameter_values) - {"temperature", "top_p", "max_output_tokens", "max_tokens"}
        patch["delete_parameters"] = sorted(previous_extra_keys - values.keys())
    context = {field: changes[column] for field, column in (("combined_window", "context_window_tokens"),
        ("input_limit", "max_input_tokens"), ("output_limit", "max_output_tokens")) if column in changes}
    if context:
        patch["context_limits"] = context
    configuration = {field: changes[column] for field, column in (("output_reserve_tokens", "default_output_reserve_tokens"),
        ("tokenizer_family", "tokenizer_family"), ("capacity_source", "capacity_source"),
        ("capability_profile_version", "capability_profile_version")) if column in changes}
    if configuration:
        patch["context_configuration"] = configuration
    return update_model_outlet(record["model_id"], ModelOutletPatchRequest(**patch), user_id, tenant_id)


def _repair_legacy_outlet(record, changes, user_id, tenant_id):
    from configs.model_catalog_loader import resolve_reasoning_capability
    from management.db.model.outlets import repair_legacy_model_record
    from nexent.core.model_service.registry import model_service_references
    from management.services.model.outlet_migration import build_legacy_outlet_snapshot
    from management.services.model.names import add_repo_to_name

    allowed = {"display_name", "model_name", "model_repo", "model_factory", "base_url", "api_key", "ssl_verify",
        "timeout_seconds", "concurrency_limit", "temperature", "top_p", "extra_params", "max_tokens",
        "max_output_tokens", "context_window_tokens", "max_input_tokens", "default_output_reserve_tokens",
        "tokenizer_family", "capacity_source", "capability_profile_version"}

    def construct(current):
        current.update({key: value for key, value in changes.items() if key in allowed})
        name = add_repo_to_name(current.get("model_repo") or "", current["model_name"])
        capability = resolve_reasoning_capability(name, current.get("base_url"), current.get("model_factory"))
        profile = build_legacy_outlet_snapshot(current, legacy_capability=capability,
            migrated_at=datetime.now(UTC).isoformat())
        return profile, current.get("api_key")

    return repair_legacy_model_record(record["model_id"], tenant_id, user_id,
        changes.get("config_revision", record.get("config_revision") or 1), construct,
        registered_references=model_service_references())
