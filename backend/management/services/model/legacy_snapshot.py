# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""One-time import of historical model envelopes into standard outlet storage."""

import hashlib
import json

from contracts.errors.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.outlet_storage import decode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references


_SOURCE_FIELDS = (
    "model_id", "tenant_id", "model_type", "model_repo", "model_name", "model_factory", "display_name",
    "base_url", "ssl_verify", "timeout_seconds", "concurrency_limit", "max_tokens", "max_output_tokens",
    "context_window_tokens", "max_input_tokens", "default_output_reserve_tokens", "tokenizer_family",
    "capacity_source", "capability_profile_version", "temperature", "top_p", "extra_params",
    "native_tool_call_supported", "reasoning_supported",
)
_MAX_SNAPSHOT_BYTES = 1024 * 1024


def model_source_fingerprint(record):
    """Detect unsynchronized legacy writes without storing or hashing credentials."""
    source = {key: record.get(key) for key in _SOURCE_FIELDS}
    source["uses_credential"] = bool(record.get("api_key"))
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()



def restore_legacy_outlet_snapshot(record):
    """Import only validated frozen data; never infer capabilities or write an envelope."""
    if record.get("profile_schema_version") is not None:
        return decode_resolved_model_profile(record, registered_references=model_service_references())
    envelope = record.get("_legacy_outlet_snapshot")
    if envelope is None:
        return None
    try:
        if (not isinstance(envelope, dict) or type(envelope.get("version")) is not int
                or envelope["version"] != 1
                or len(json.dumps(envelope, ensure_ascii=False, allow_nan=False).encode("utf-8")) > _MAX_SNAPSHOT_BYTES):
            raise ModelOutletValidationError("LEGACY_SNAPSHOT_INVALID")
        if envelope.get("source_fingerprint") != model_source_fingerprint(record):
            raise ModelOutletValidationError("LEGACY_SNAPSHOT_STALE")
        row = envelope.get("row")
        if (not isinstance(row, dict) or type(envelope.get("revision")) is not int
                or row.get("model_id") != record.get("model_id")
                or row.get("tenant_id") != record.get("tenant_id")
                or envelope["revision"] != row.get("config_revision")):
            raise ModelOutletValidationError("LEGACY_SNAPSHOT_IDENTITY_INVALID")
        profile = decode_resolved_model_profile(row, registered_references=model_service_references(),
            protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
        from management.services.model.names import add_repo_to_name

        if (profile.identity.request_model_id != add_repo_to_name(record.get("model_repo") or "", record["model_name"])
                or profile.identity.provider_id != (record.get("model_factory") or "custom")
                or profile.connection.base_url.rstrip("/") != record["base_url"].rstrip("/")
                or (profile.connection.credential_ref.kind == "model_record") != bool(record.get("api_key"))):
            raise ModelOutletValidationError("LEGACY_SNAPSHOT_IDENTITY_INVALID")
        return profile
    except ModelOutletValidationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ModelOutletValidationError("LEGACY_SNAPSHOT_INVALID") from None
