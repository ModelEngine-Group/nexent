"""Management-only compatibility provisioning of canonical model outlet snapshots."""

import hashlib
import json
from datetime import UTC, datetime

SOURCE_FIELDS = (
    "model_id", "tenant_id", "model_type", "model_repo", "model_name", "model_factory", "display_name",
    "base_url", "ssl_verify", "timeout_seconds", "concurrency_limit", "max_tokens", "max_output_tokens",
    "context_window_tokens", "max_input_tokens", "default_output_reserve_tokens", "tokenizer_family",
    "capacity_source", "capability_profile_version", "temperature", "top_p", "extra_params",
    "native_tool_call_supported", "reasoning_supported",
)
MAX_RUNTIME_SNAPSHOT_BYTES = 1024 * 1024


def model_source_fingerprint(record):
    """Detect unsynchronized legacy writes without storing or hashing credentials."""
    source = {key: record.get(key) for key in SOURCE_FIELDS}
    source["uses_credential"] = bool(record.get("api_key"))
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def build_runtime_outlet_snapshot(record):
    """Run only on management save/migration, never in the Agent runtime path."""
    if record.get("model_type") not in {"llm", "chat"}:
        return None
    from configs.model_catalog_loader import resolve_reasoning_capability
    from nexent.core.model_service.profiles.outlet_storage import (
        decode_resolved_model_profile,
        encode_resolved_model_profile,
    )
    from nexent.core.model_service.registry import model_service_references
    from services.model_outlet_migration_service import build_legacy_outlet_snapshot
    from utils.model_name_utils import add_repo_to_name

    fingerprint = model_source_fingerprint(record)
    current = record.get("runtime_outlet_snapshot") or {}
    if not isinstance(current, dict):
        current = {}
    if current.get("source_fingerprint") == fingerprint and current.get("row"):
        from services.model_runtime_snapshot_service import (
            restore_runtime_model_snapshot,
        )

        if restore_runtime_model_snapshot(record, record["tenant_id"], strict=False) is not None:
            return current
    previous_row = current.get("row")
    previous_revision = current.get("revision")
    if type(previous_revision) is not int:
        previous_revision = previous_row.get("config_revision", 0) if isinstance(previous_row, dict) else 0
    revision = (previous_revision if type(previous_revision) is int and previous_revision > 0 else 0) + 1
    try:
        name = add_repo_to_name(record.get("model_repo") or "", record["model_name"])
        previous = None
        if isinstance(current.get("row"), dict):
            try:
                previous = decode_resolved_model_profile(current["row"], registered_references=model_service_references(),
                    protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
            except ValueError:
                pass
        if (previous is not None and previous.outlet_id == record["model_id"]
                and previous.identity.tenant_id == record["tenant_id"]
                and previous.identity.request_model_id == name
                and previous.identity.provider_id == (record.get("model_factory") or "custom")):
            from services.model_runtime_refresh_service import refresh_saved_outlet

            profile = refresh_saved_outlet(record, previous, revision)
        else:
            capability = resolve_reasoning_capability(name, record.get("base_url"), record.get("model_factory"))
            profile = build_legacy_outlet_snapshot(
                {**record, "config_revision": revision}, legacy_capability=capability,
                migrated_at=datetime.now(UTC).isoformat(),
            )
        data = profile.model_dump()
        data["provenance"]["provider_metadata"]["legacy_context_columns"] = {
            key: record.get(key) for key in (
                "context_window_tokens", "max_input_tokens", "max_output_tokens", "default_output_reserve_tokens",
                "tokenizer_family", "capacity_source", "capability_profile_version",
            )
        }
        profile = type(profile).model_validate(data)
        encoded = encode_resolved_model_profile(profile, registered_references=model_service_references(),
            protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
        envelope = {"version": 1, "revision": revision, "source_fingerprint": fingerprint, "row": encoded}
        if len(json.dumps(envelope, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RUNTIME_SNAPSHOT_BYTES:
            raise ValueError("MODEL_OUTLET_SNAPSHOT_TOO_LARGE")
        return envelope
    except (ValueError, TypeError, KeyError):
        # Preserve legacy management behavior; an unusable snapshot is never executable.
        # Diagnostics contain categories only, never submitted values or credentials.
        return {"version": 1, "revision": revision, "source_fingerprint": fingerprint,
                "error": "MODEL_OUTLET_PROVISIONING_FAILED"}


def create_model_record(model_data, user_id, tenant_id):
    """Provision the snapshot in the same management transaction as insertion."""
    from database.model_management_db import create_model_record as persist

    return persist(model_data, user_id, tenant_id, runtime_profile_builder=build_runtime_outlet_snapshot)


def update_model_record(model_id, update_data, user_id=None, tenant_id=None):
    """Provision under the management row lock, retaining the legacy return contract."""
    from database.model_management_db import update_model_record as persist

    return persist(model_id, update_data, user_id, tenant_id, runtime_profile_builder=build_runtime_outlet_snapshot)
