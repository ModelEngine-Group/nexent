"""Normalized, content-free usage records for physical provider calls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, Optional
from uuid import uuid4


PROVIDER_USAGE_SCHEMA_VERSION = 3


def resolve_provider_usage_profile(
    provider: Optional[str],
    capability_profile_version: Optional[str] = None,
) -> dict[str, Any]:
    """Return conservative semantics for the approved OpenAI-compatible providers."""
    name = str(provider or "unknown").lower()
    common = {
        "capability_profile_version": capability_profile_version,
        "reasoning_usage_semantics": "unavailable",
    }
    if name == "dashscope":
        return {**common, "cache_partition_semantics": "disjoint_inclusive"}
    if name == "siliconflow":
        return {
            **common,
            "cache_write_semantics": "unsupported",
            "cache_hit_miss_semantics": "disjoint_inclusive",
        }
    return common


@dataclass(frozen=True)
class NormalizedTokenUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    fresh_input_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    visible_output_tokens: Optional[int] = None
    total_source: str = "missing"


@dataclass(frozen=True)
class UsageQuality:
    degraded: bool = False
    reasons: tuple[str, ...] = ()


@dataclass
class ProviderCallUsage:
    """Final record for exactly one physical provider request."""

    call_id: str = field(default_factory=lambda: str(uuid4()))
    turn_id: Optional[str] = None
    step_number: Optional[int] = None
    purpose: str = "main_agent"
    attempt: int = 0
    provider: str = "unknown"
    model: str = "unknown"
    capability_profile_version: Optional[str] = None
    source: str = "missing"
    status: str = "failed"
    usage: NormalizedTokenUsage = field(default_factory=NormalizedTokenUsage)
    quality: UsageQuality = field(default_factory=UsageQuality)
    finish_reason: Optional[str] = None
    duration_ms: Optional[int] = None
    time_to_first_token_ms: Optional[int] = None
    provider_metadata: dict[str, int] = field(default_factory=dict)
    context_composition: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = PROVIDER_USAGE_SCHEMA_VERSION
        return {"schema_version": payload.pop("schema_version"), **payload}


def normalize_provider_usage(
    raw_usage: Any,
    *,
    provider: Optional[str],
    model: Optional[str],
    capability_profile: Optional[Mapping[str, Any]] = None,
) -> tuple[NormalizedTokenUsage, UsageQuality, str, dict[str, int]]:
    """Normalize OpenAI-compatible usage without turning missing fields into zero."""

    profile = dict(capability_profile or {})
    reasons: list[str] = []
    metadata: dict[str, int] = {}

    input_tokens = _first_token_value(
        raw_usage, ("prompt_tokens", "input_tokens"), "input_tokens", reasons
    )
    output_tokens = _first_token_value(
        raw_usage, ("completion_tokens", "output_tokens"), "output_tokens", reasons
    )
    provider_total = _first_token_value(
        raw_usage, ("total_tokens",), "total_tokens", reasons
    )

    source = "provider" if raw_usage is not None and (input_tokens is not None or output_tokens is not None) else "missing"
    if input_tokens is None and output_tokens is None:
        source = "missing"

    cache_read = _first_nested_token_value(
        raw_usage,
        (
            ("prompt_tokens_details", "cached_tokens"),
            ("input_tokens_details", "cached_tokens"),
            (None, "prompt_cache_hit_tokens"),
            (None, "cache_read_input_tokens"),
        ),
        "cache_read_tokens",
        reasons,
        metadata,
    )
    cache_write = _first_nested_token_value(
        raw_usage,
        (
            ("prompt_tokens_details", "cache_creation_input_tokens"),
            ("input_tokens_details", "cache_creation_input_tokens"),
            (None, "cache_creation_input_tokens"),
        ),
        "cache_write_tokens",
        reasons,
        metadata,
    )
    cache_miss = _first_nested_token_value(
        raw_usage,
        ((None, "prompt_cache_miss_tokens"),),
        "prompt_cache_miss_tokens",
        reasons,
        metadata,
    )

    if profile.get("cache_read_semantics") == "unsupported":
        cache_read = 0
    if profile.get("cache_write_semantics") == "unsupported":
        cache_write = 0

    fresh_input: Optional[int] = None
    cache_semantics = profile.get("cache_partition_semantics")
    if input_tokens is not None and cache_read is not None and cache_write is not None:
        if cache_semantics == "disjoint_inclusive":
            if cache_read + cache_write > input_tokens:
                reasons.append("cache_partition_exceeds_input")
            fresh_input = max(0, input_tokens - cache_read - cache_write)
        elif cache_read or cache_write:
            reasons.append("cache_partition_semantics_unknown")
    if cache_miss is not None and input_tokens is not None:
        if cache_read is not None and cache_read + cache_miss != input_tokens:
            reasons.append("cache_hit_miss_input_conflict")
        elif profile.get("cache_hit_miss_semantics") == "disjoint_inclusive":
            fresh_input = cache_miss

    reasoning = _first_nested_token_value(
        raw_usage,
        (
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
            (None, "reasoning_tokens"),
        ),
        "reasoning_tokens",
        reasons,
        metadata,
    )
    reasoning_semantics = profile.get("reasoning_usage_semantics", "unavailable")
    visible_output: Optional[int] = None
    if reasoning is not None and output_tokens is not None:
        if reasoning_semantics == "included":
            if reasoning > output_tokens:
                reasons.append("reasoning_exceeds_output")
            visible_output = max(0, output_tokens - reasoning)
        else:
            reasons.append("reasoning_semantics_unknown")
    elif reasoning_semantics == "unsupported" and output_tokens is not None:
        reasoning = 0
        visible_output = output_tokens

    if provider_total is not None:
        total_tokens = provider_total
        total_source = "provider"
        if input_tokens is not None and output_tokens is not None and provider_total != input_tokens + output_tokens:
            reasons.append("total_tokens_inconsistent")
    elif input_tokens is not None or output_tokens is not None:
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
        total_source = "derived"
    else:
        total_tokens = None
        total_source = "missing"

    normalized = NormalizedTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        fresh_input_tokens=fresh_input,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=reasoning,
        visible_output_tokens=visible_output,
        total_source=total_source,
    )
    unique_reasons = tuple(dict.fromkeys(reasons))
    return normalized, UsageQuality(bool(unique_reasons), unique_reasons), source, metadata


def _valid_estimate(value: Any) -> Optional[int]:
    parsed = _coerce_non_negative_int(value)
    return parsed if parsed is not None else None


def _first_token_value(
    value: Any,
    keys: tuple[str, ...],
    field_name: str,
    reasons: list[str],
) -> Optional[int]:
    for key in keys:
        candidate = _get_value(value, key)
        if candidate is None:
            continue
        parsed = _coerce_non_negative_int(candidate)
        if parsed is None:
            reasons.append(f"invalid_{field_name}")
            continue
        return parsed
    return None


def _first_nested_token_value(
    value: Any,
    paths: tuple[tuple[Optional[str], str], ...],
    field_name: str,
    reasons: list[str],
    metadata: dict[str, int],
) -> Optional[int]:
    for parent, child in paths:
        container = _get_value(value, parent) if parent else value
        candidate = _get_value(container, child)
        if candidate is None:
            continue
        parsed = _coerce_non_negative_int(candidate)
        if parsed is None:
            reasons.append(f"invalid_{field_name}")
            continue
        metadata[child] = parsed
        return parsed
    return None


def _coerce_non_negative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        return None
    return int(numeric)


def _get_value(value: Any, key: Optional[str]) -> Any:
    if value is None or key is None:
        return value
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)
