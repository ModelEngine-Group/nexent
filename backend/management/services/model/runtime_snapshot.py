# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Restore trusted saved outlets for runtime; never infer profiles from aliases."""

import json


def restore_runtime_model_snapshot(record, tenant_id, *, strict=True):
    """Leave unmigrated records to legacy consumers; fail closed on corrupt saved profiles."""
    envelope = record.get("runtime_outlet_snapshot")
    if envelope is None and record.get("profile_schema_version") is None:
        return None
    from nexent.core.model_service.profiles.outlet_storage import (
        decode_resolved_model_profile,
    )
    from nexent.core.model_service.registry import model_service_references

    try:
        if record.get("tenant_id") != tenant_id:
            raise ValueError("MODEL_OUTLET_TENANT_MISMATCH")
        stored = record
        if envelope is not None:
            from management.services.model.runtime_provisioning import (
                MAX_RUNTIME_SNAPSHOT_BYTES,
                model_source_fingerprint,
            )

            if (not isinstance(envelope, dict) or type(envelope.get("version")) is not int or envelope["version"] != 1
                    or len(json.dumps(envelope, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                    > MAX_RUNTIME_SNAPSHOT_BYTES
                    or envelope.get("source_fingerprint") != model_source_fingerprint(record)):
                raise ValueError("MODEL_OUTLET_STALE_SNAPSHOT")
            stored = envelope.get("row")
            if not isinstance(stored, dict):
                raise ValueError("MODEL_OUTLET_PROVISIONING_REQUIRED")
            if (stored.get("model_id") != record.get("model_id") or stored.get("tenant_id") != tenant_id
                    or envelope.get("revision") != stored.get("config_revision")):
                raise ValueError("MODEL_OUTLET_IDENTITY_MISMATCH")
        return decode_resolved_model_profile(stored, registered_references=model_service_references(),
            protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
    except (ValueError, TypeError, KeyError):
        if strict:
            raise
        # Unselected/legacy consumers must not be broken by another outlet's bad snapshot.
        # Jiuwen rejects a missing selected profile explicitly during preflight.
        return None
