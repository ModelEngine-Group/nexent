"""Validation and read-only auditing for persisted model capacity contracts."""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from consts.exceptions import ModelCapacityConfigError


CAPACITY_MODEL_TYPES = frozenset({"llm", "vlm", "vlm2", "vlm3"})
CAPACITY_FIELDS = (
    "context_window_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "default_output_reserve_tokens",
)
DEFAULT_REQUESTED_OUTPUT_TOKENS = 4096


def _fail(reason: str, message: str, *, field: Optional[str] = None) -> None:
    raise ModelCapacityConfigError(
        f"capacity_config_invalid.{reason}", message, field=field
    )


def merged_capacity_contract(
    payload: Mapping[str, Any], existing: Optional[Mapping[str, Any]] = None
) -> dict[str, Any]:
    """Return capacity-relevant values after applying a partial payload."""
    merged = dict(existing or {})
    merged.update(payload)
    if merged.get("model_type") is None and existing is not None:
        merged["model_type"] = existing.get("model_type")
    return merged


def validate_capacity_contract(
    payload: Mapping[str, Any],
    *,
    existing: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Validate one create or merged partial-update capacity contract.

    Unknown capacity is valid during the P0 migration. When a hard input
    constraint is present, the resulting W2 estimated budget must be positive.
    """
    contract = merged_capacity_contract(payload, existing)
    if contract.get("model_type") not in CAPACITY_MODEL_TYPES:
        return contract

    for field in CAPACITY_FIELDS:
        value = contract.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            _fail(
                "non_positive_or_non_integer",
                f"{field} must be a positive integer",
                field=field,
            )

    context = contract.get("context_window_tokens")
    max_input = contract.get("max_input_tokens")
    max_output = contract.get("max_output_tokens")
    default_output = contract.get("default_output_reserve_tokens")

    if context is not None and max_output is not None and max_output >= context:
        _fail(
            "max_output_not_below_context",
            "max_output_tokens must be lower than context_window_tokens",
            field="max_output_tokens",
        )
    if context is not None and max_input is not None and max_input > context:
        _fail(
            "max_input_exceeds_context",
            "max_input_tokens must not exceed context_window_tokens",
            field="max_input_tokens",
        )
    if (
        default_output is not None
        and max_output is not None
        and default_output > max_output
    ):
        _fail(
            "default_output_exceeds_max_output",
            "default_output_reserve_tokens must not exceed max_output_tokens",
            field="default_output_reserve_tokens",
        )

    if context is None and max_input is None:
        return contract

    requested_output = default_output or DEFAULT_REQUESTED_OUTPUT_TOKENS
    if max_output is not None and requested_output > max_output:
        _fail(
            "requested_output_exceeds_max_output",
            "resolved requested output exceeds max_output_tokens",
            field="default_output_reserve_tokens",
        )

    limits = []
    if max_input is not None:
        limits.append(max_input)
    if context is not None:
        limits.append(context - requested_output)
    provider_input_limit = min(limits)
    if provider_input_limit <= 0:
        _fail(
            "non_positive_provider_input_limit",
            "capacity values leave no provider input capacity",
        )

    uncertainty_reserve = math.ceil(provider_input_limit * 0.10)
    if provider_input_limit - uncertainty_reserve <= 0:
        _fail(
            "non_positive_hard_input_budget",
            "capacity values leave no safe input budget",
        )
    return contract


def audit_capacity_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one row without mutating it or exposing credentials."""
    reasons: list[str] = []
    status = "valid"
    try:
        contract = validate_capacity_contract(record)
    except ModelCapacityConfigError as exc:
        contract = dict(record)
        status = "invalid"
        reasons.append(exc.reason_code)

    if contract.get("model_type") in CAPACITY_MODEL_TYPES:
        context = contract.get("context_window_tokens")
        max_input = contract.get("max_input_tokens")
        max_output = contract.get("max_output_tokens")
        source = contract.get("capacity_source")
        if context is None and max_input is None:
            status = "unknown" if status == "valid" else status
            reasons.append("capacity_unknown")
        if context == 32768 and max_output == 4096 and source == "operator":
            status = "suspicious" if status == "valid" else status
            reasons.append("operator_shaped_ui_default")
        if (
            isinstance(context, int)
            and isinstance(max_input, int)
            and max_input > 0
            and max_input < math.ceil(context * 0.10)
        ):
            status = "suspicious" if status == "valid" else status
            reasons.append("independent_input_unusually_small")

    return {
        "model_id": record.get("model_id"),
        "model_name": record.get("model_name"),
        "model_type": record.get("model_type"),
        "status": status,
        "reasons": reasons,
    }


def audit_capacity_records(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Return sanitized row classifications and aggregate counts."""
    rows = [audit_capacity_record(record) for record in records]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"counts": counts, "rows": rows}
