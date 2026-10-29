# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolve run budgets and own capacity warning and telemetry state."""

import logging
import threading
from typing import Any, Dict, Optional

from management.services.model.catalog import CATALOG as CAPABILITY_CATALOG
from management.services.configuration.tenant.settings import tenant_config_manager
from nexent.core.models.capacity_budget import (
    ContextBudgetCalculator,
    ContextBudgetSnapshot,
    RequestBudgetOverrides,
    UncertaintyReserveBasisUnknown,
)
from nexent.core.models.capacity_resolver import (
    ModelCapacitySnapshot,
    ProviderCapabilityUnknown,
    ResolverError,
    resolve_capacity,
)

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)

_TOKEN_THRESHOLD_LEGACY_FALLBACK = 32768

_OPERATOR_OVERRIDE_FIELDS = (
    "context_window_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "default_output_reserve_tokens",
    "tokenizer_family",
)

_CAPACITY_WARNING_EMITTED: set = set()

_CAPACITY_WARNING_LOCK = threading.Lock()

try:
    from opentelemetry import metrics as _otel_metrics

    _capacity_dispatch_meter = _otel_metrics.get_meter("agents.create_agent_info")
    _capacity_dispatch_profile_hit_total = _capacity_dispatch_meter.create_counter(
        name="model_capacity_suggestion_dispatch_profile_hit_total",
        description=(
            "Count of agent dispatches where the resolved W1 capacity "
            "snapshot reports a non-null capability_profile_version "
            "(i.e. the runtime profile match succeeded). Labelled by "
            "provider."
        ),
        unit="dispatches",
    )
except Exception:  # pragma: no cover - OTel is optional at runtime
    _capacity_dispatch_profile_hit_total = None


def _record_dispatch_profile_hit(provider: Optional[str]) -> None:
    """Emit dispatch_profile_hit_total for one successful runtime profile match."""
    if _capacity_dispatch_profile_hit_total is None:
        return
    try:
        _capacity_dispatch_profile_hit_total.add(
            1,
            {"provider": (provider or "unknown").lower()},
        )
    except Exception:  # pragma: no cover - never break agent run for telemetry
        pass


def _operator_overrides_from_model_info(model_info: Optional[dict]) -> dict:
    """Extract the W1 operator-override fields from a model_record_t row."""
    if not isinstance(model_info, dict):
        return {}
    overrides = {}
    for field in _OPERATOR_OVERRIDE_FIELDS:
        value = model_info.get(field)
        if value is not None:
            overrides[field] = value
    if (model_info.get("profile_schema_version") is not None
            and model_info.get("default_max_output_tokens") is not None):
        overrides["default_output_reserve_tokens"] = model_info["default_max_output_tokens"]
    return overrides




def _dominant_capacity_source(field_sources: dict) -> Optional[str]:
    values = [value for value in field_sources.values() if value]
    if not values:
        return None
    for preferred in (
        "operator",
        "profile",
        "provider_candidate",
        "legacy",
        "default",
        "unknown",
    ):
        if preferred in values:
            return preferred
    return values[0]


def _capacity_snapshot_for_monitoring(snapshot: Any) -> dict:
    data = snapshot.model_dump() if hasattr(snapshot, "model_dump") else dict(snapshot)
    return {
        "provider": data.get("provider"),
        "model_name": data.get("model_name"),
        "context_window_tokens": data.get("context_window_tokens"),
        "default_output_reserve_tokens": data.get("default_output_reserve_tokens"),
        "capability_profile_version": data.get("capability_profile_version"),
        "capacity_source": _dominant_capacity_source(data.get("field_sources") or {}),
        "requested_output_tokens": data.get("requested_output_tokens"),
        "provider_input_limit_tokens": data.get("provider_input_limit_tokens"),
        "tokenizer_family": data.get("tokenizer_family"),
        "counting_mode": data.get("counting_mode"),
        "unknown_capabilities": data.get("unknown_capabilities") or [],
        "capacity_fingerprint": data.get("fingerprint"),
    }


def _resolve_context_budget(
    *,
    capacity_snapshot: Optional[ModelCapacitySnapshot],
    tenant_id: str,
    agent_requested_output_tokens: Optional[int],
    request_requested_output_tokens: Optional[int],
) -> Optional[ContextBudgetSnapshot]:
    """Resolve the complete canonical W2 snapshot before context assembly."""
    if capacity_snapshot is None:
        return None

    request_overrides = None
    if request_requested_output_tokens is not None:
        request_overrides = RequestBudgetOverrides(
            requested_output_tokens=request_requested_output_tokens,
        )

    output_reserve_source = (
        "agent" if agent_requested_output_tokens is not None else "model_default"
    )
    try:
        snapshot = ContextBudgetCalculator().calculate_context_budget(
            capacity_snapshot=capacity_snapshot,
            reserve_policy=tenant_config_manager.get_capacity_reserve_policy(tenant_id),
            request_overrides=request_overrides,
            requested_output_tokens=agent_requested_output_tokens,
            output_reserve_source=output_reserve_source,
        )
    except UncertaintyReserveBasisUnknown as exc:
        # W2 uncertainty reserve needs context_window_tokens as the 10% basis.
        # Falls through here when a model row has max_input_tokens set but
        # context_window_tokens is NULL - possible for rows imported before
        # W11 V1 save-time defaults landed, or for rows written directly via
        # SQL/legacy import. Degrade to the same "no W2 snapshot" branch the
        # caller already handles (falls back to W1 input_budget).
        logger.warning(
            "W2 context budget unavailable (tenant_id=%s model=%s): %s - "
            "falling back to W1 input_budget. Fill context_window_tokens on the "
            "model record to enable W2 enforcement.",
            tenant_id,
            capacity_snapshot.model_name,
            exc,
        )
        return None
    logger.debug(
        "W2 context budget resolved: tenant_id=%s model=%s requested_output_tokens=%s "
        "compaction_trigger_threshold_tokens=%s compaction_target_tokens=%s "
        "fingerprint=%s warnings=%s",
        tenant_id,
        snapshot.model_name,
        snapshot.requested_output_tokens,
        snapshot.compaction_trigger_threshold_tokens,
        snapshot.compaction_target_tokens,
        snapshot.fingerprint,
        list(snapshot.warnings),
    )
    return snapshot


def _resolve_input_budget(
    model_info: Optional[dict],
) -> tuple[int, Optional[dict], Optional[ModelCapacitySnapshot]]:
    """Resolve the context-manager input budget for a model_record_t row.

    Calls ModelCapacityResolver with the catalog + operator overrides. Returns
    snapshot.provider_input_limit_tokens and monitoring fields on success.
    Falls back to _TOKEN_THRESHOLD_LEGACY_FALLBACK with no snapshot when
    capacity is unknown - this is the migration-window behavior before all
    model rows are backfilled.
    """
    if not isinstance(model_info, dict):
        return _TOKEN_THRESHOLD_LEGACY_FALLBACK, None, None
    provider_raw = model_info.get("model_factory")
    provider = provider_raw.lower().strip() if isinstance(provider_raw, str) else ""
    model_id = model_info.get("model_name") or ""
    provider_missing_detail = None
    if not provider:
        provider_missing_detail = (
            "model_factory/provider is missing; capacity catalog matching is disabled"
        )
    try:
        operator_overrides = _operator_overrides_from_model_info(model_info)
        snapshot = resolve_capacity(
            model_id=model_id,
            provider=provider,
            operator_overrides=operator_overrides,
            capability_profiles={} if model_info.get("profile_schema_version") is not None else CAPABILITY_CATALOG,
        )
        logger.debug(
            "Capacity resolved for (%s, %s): input_limit=%s source=%s profile=%s fingerprint=%s",
            provider,
            model_id,
            snapshot.provider_input_limit_tokens,
            dict(snapshot.field_sources),
            snapshot.capability_profile_version,
            snapshot.fingerprint,
        )
        if snapshot.capability_profile_version:
            _record_dispatch_profile_hit(provider)
        return (
            snapshot.provider_input_limit_tokens,
            _capacity_snapshot_for_monitoring(snapshot),
            snapshot,
        )
    except ProviderCapabilityUnknown:
        _warn_missing_capacity_once(
            model_info,
            provider,
            model_id,
            detail=provider_missing_detail,
        )
        return _TOKEN_THRESHOLD_LEGACY_FALLBACK, None, None
    except ResolverError as exc:
        _warn_missing_capacity_once(
            model_info,
            provider,
            model_id,
            detail=str(exc),
        )
        return _TOKEN_THRESHOLD_LEGACY_FALLBACK, None, None


def _warn_missing_capacity_once(
    model_info: Optional[dict],
    provider: str,
    model_id_str: str,
    detail: Optional[str] = None,
) -> None:
    """Log one WARNING per process per model when capacity is not configured.

    Plain-English message aimed at operators reading backend logs. Tells
    them what is disabled, which model is affected, and how to fix it
    through the existing UI.
    """
    db_model_id = model_info.get("model_id") if isinstance(model_info, dict) else None
    dedup_key = db_model_id if db_model_id is not None else f"{provider}/{model_id_str}"
    # Test-and-set inside the lock so concurrent first-time callers don't
    # both make it past the membership check. Logging happens outside the
    # lock to avoid serialising I/O across all warning paths.
    with _CAPACITY_WARNING_LOCK:
        if dedup_key in _CAPACITY_WARNING_EMITTED:
            return
        _CAPACITY_WARNING_EMITTED.add(dedup_key)

    reason = (
        f"resolver error: {detail}"
        if detail
        else "no context_window_tokens or max_output_tokens configured"
    )
    logger.warning(
        "Output token cap and budget consistency check are not enforced for "
        "model '%s' (model_id=%s, provider=%s) because %s. "
        "To enable enforcement, open the Nexent model management UI, edit "
        "this model, and fill in 'Context window tokens' and 'Max output "
        "tokens'. Falling back to a default context threshold of %s tokens.",
        model_id_str,
        db_model_id,
        provider,
        reason,
        _TOKEN_THRESHOLD_LEGACY_FALLBACK,
    )
