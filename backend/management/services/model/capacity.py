# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
import logging
import re
import threading
import time
from typing import Any, Dict, Mapping, Optional

from consts.const import CAPACITY_SUGGESTION_ENABLED, CAPACITY_VISIBILITY_ENABLED, NEXENT_LITELLM_JSON
from contracts.model import CapabilityProfileLike, CapacitySuggestionConfidence, CapacitySuggestionFields, CapacitySuggestionMatchKind, CapacitySuggestionResult, ProfileKey
from management.db.model.repository import get_model_records
from management.services.model.names import add_repo_to_name

logger = logging.getLogger(__name__)

# OpenTelemetry instruments for W11 catalog match observability.
# Spec lines 706-708. Guarded the same way as the SDK monitor module: if
# OpenTelemetry is not installed (some deployments run without it), the
# instruments are None and the recording becomes a no-op.
try:
    from opentelemetry import metrics as _otel_metrics

    _suggestion_meter = _otel_metrics.get_meter("management.services.model.capacity")
    _capacity_suggestion_requests_total = _suggestion_meter.create_counter(
        name="model_capacity_suggestion_requests_total",
        description=(
            "Count of capacity-suggestion service invocations, labelled by "
            "match_kind, model_type, and inferred provider. Drives the SLO "
            "'at least 70% of new manual-add LLM rows produce match_kind "
            "!= none' (W11 spec)."
        ),
        unit="requests",
    )
    _capacity_suggestion_latency_ms = _suggestion_meter.create_histogram(
        name="model_capacity_suggestion_latency_ms",
        description=(
            "End-to-end latency of suggest_capacity, labelled by match_kind "
            "and provider. Used to verify provider-discovery p95 stays under "
            "the model-add latency budget (W11 spec)."
        ),
        unit="ms",
    )
except Exception:  # pragma: no cover - OTel is optional at runtime
    _capacity_suggestion_requests_total = None
    _capacity_suggestion_latency_ms = None


def _record_suggestion_request(
    match_kind: str,
    provider: Optional[str],
    model_type: Optional[str],
    duration_ms: float,
) -> None:
    """Emit the requests_total counter and latency_ms histogram for one call.

    Recording never raises -- a broken telemetry stack must not break the
    suggestion path.
    """
    safe_provider = (provider or "unknown").lower()
    if _capacity_suggestion_requests_total is not None:
        try:
            _capacity_suggestion_requests_total.add(
                1,
                {
                    "match_kind": match_kind,
                    "model_type": (model_type or "unknown").lower(),
                    "provider": safe_provider,
                },
            )
        except Exception:  # pragma: no cover
            pass
    if _capacity_suggestion_latency_ms is not None:
        try:
            _capacity_suggestion_latency_ms.record(
                duration_ms,
                {"match_kind": match_kind, "provider": safe_provider},
            )
        except Exception:  # pragma: no cover
            pass


# Substring patterns matched against the lower-cased base_url. Order matters:
# `in` returns the first hit, so place more-specific patterns before broader
# ones (e.g. `dashscope` before `aliyuncs`). Patterns mirror frontend
# PROVIDER_HINTS in `frontend/const/modelConfig.ts` so backend provider-by-URL
# detection stays consistent with the icon the user sees in the UI.
HOST_PROVIDER_PATTERNS = (
    ("open/router", "modelengine"),
    ("dashscope", "dashscope"),
    ("aliyuncs", "dashscope"),
    ("siliconflow", "silicon"),
    ("silicon", "silicon"),
    ("modelengine", "modelengine"),
    ("openai", "openai"),
    ("deepseek", "deepseek"),
    ("jina", "jina"),
    ("tokenpony", "tokenpony"),
    ("bytedance", "volcengine"),
)

SUPPORTED_SUGGESTION_MODEL_TYPES = {"llm", "vlm", "vlm2", "vlm3", "vlm4"}


def pick_provider_from_base_url(base_url: Optional[str]) -> Optional[str]:
    # Match the entire lower-cased base_url, mirroring the frontend
    # detectProviderFromUrl helper. Substring `in` check, first hit wins.
    if not base_url:
        return None

    lowered = base_url.lower()
    for pattern, provider in HOST_PROVIDER_PATTERNS:
        if pattern in lowered:
            return provider
    return None


def _normalize_provider(provider: Optional[str]) -> Optional[str]:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    if normalized in {"", "openai-api-compatible"}:
        return None
    if normalized == "siliconflow":
        return "silicon"
    return normalized


def normalize_model_name(model_name: str) -> str:
    return re.sub(r"[-_./\s]+", "", model_name.strip().lower())


def _normalize_catalog_exact_name(model_name: str) -> str:
    return model_name.strip().lower()


def _profile_to_suggestion(profile: CapabilityProfileLike) -> CapacitySuggestionFields:
    return CapacitySuggestionFields(
        context_window_tokens=profile.context_window_tokens,
        max_input_tokens=profile.max_input_tokens,
        max_output_tokens=profile.max_output_tokens,
        default_output_reserve_tokens=profile.default_output_reserve_tokens,
        tokenizer_family=profile.tokenizer_family,
    )


def _result_from_profile(
    provider: str,
    model_name: str,
    profile: CapabilityProfileLike,
    match_kind: CapacitySuggestionMatchKind,
) -> CapacitySuggestionResult:
    confidence = (
        CapacitySuggestionConfidence.HIGH
        if match_kind == CapacitySuggestionMatchKind.CATALOG_EXACT
        else CapacitySuggestionConfidence.MEDIUM
    )
    return CapacitySuggestionResult(
        suggestions=_profile_to_suggestion(profile),
        match_kind=match_kind,
        match_confidence=confidence,
        match_explanation=f"Matched approved catalog profile {profile.capability_profile_version}",
        suggested_provider=provider,
        canonical_model_name=model_name,
        capability_profile_version=profile.capability_profile_version,
        capacity_source_on_accept="operator",
    )


def _none_result(explanation: str) -> CapacitySuggestionResult:
    return CapacitySuggestionResult(
        suggestions=None,
        match_kind=CapacitySuggestionMatchKind.NONE,
        match_confidence=None,
        match_explanation=explanation,
    )


def _provider_catalog(
    catalog: Mapping[ProfileKey, CapabilityProfileLike],
    provider: str,
) -> dict[ProfileKey, CapabilityProfileLike]:
    return {
        (catalog_provider, catalog_model): profile
        for (catalog_provider, catalog_model), profile in catalog.items()
        if catalog_provider == provider
    }


def _unique_final_segment_match(
    model_name: str,
    catalog: Mapping[ProfileKey, CapabilityProfileLike],
    provider: str,
) -> Optional[tuple[ProfileKey, CapabilityProfileLike]]:
    requested = normalize_model_name(model_name)
    matches: list[tuple[ProfileKey, CapabilityProfileLike]] = []
    for key, profile in _provider_catalog(catalog, provider).items():
        catalog_model = key[1]
        final_segment = catalog_model.split("/")[-1]
        if normalize_model_name(final_segment) == requested:
            matches.append((key, profile))

    if len(matches) == 1:
        return matches[0]
    return None


def _fuzzy_catalog_match(
    model_name: str,
    catalog: Mapping[ProfileKey, CapabilityProfileLike],
    provider: str,
) -> Optional[tuple[ProfileKey, CapabilityProfileLike]]:
    requested = normalize_model_name(model_name)
    matches: list[tuple[ProfileKey, CapabilityProfileLike]] = []
    for key, profile in _provider_catalog(catalog, provider).items():
        if normalize_model_name(key[1]) == requested:
            matches.append((key, profile))

    if len(matches) == 1:
        return matches[0]

    return _unique_final_segment_match(model_name, catalog, provider)


def _unique_catalog_provider_for_model(
    model_name: str,
    catalog: Mapping[ProfileKey, CapabilityProfileLike],
) -> Optional[str]:
    requested = normalize_model_name(model_name)
    providers = {
        provider
        for provider, catalog_model in catalog.keys()
        if normalize_model_name(catalog_model) == requested
        or normalize_model_name(catalog_model.split("/")[-1]) == requested
    }
    if len(providers) == 1:
        return next(iter(providers))
    return None


def pick_provider(
    provider_hint: Optional[str],
    base_url: Optional[str],
    model_name: str,
    catalog: Optional[Mapping[ProfileKey, CapabilityProfileLike]] = None,
) -> Optional[str]:
    active_catalog = catalog if catalog is not None else _get_default_catalog()
    explicit_provider = _normalize_provider(provider_hint)
    if explicit_provider:
        return explicit_provider

    inferred_provider = pick_provider_from_base_url(base_url)
    if inferred_provider:
        return inferred_provider

    return _unique_catalog_provider_for_model(model_name, active_catalog)


def _get_default_catalog() -> Mapping[ProfileKey, CapabilityProfileLike]:
    from contracts.constants.model import CATALOG

    return CATALOG


def suggest_capacity(
    model_name: str,
    base_url: Optional[str] = None,
    provider_hint: Optional[str] = None,
    model_type: Optional[str] = None,
    catalog: Optional[Mapping[ProfileKey, CapabilityProfileLike]] = None,
    enabled: bool = CAPACITY_SUGGESTION_ENABLED,
) -> CapacitySuggestionResult:
    start_perf = time.perf_counter()
    result = _suggest_capacity_inner(
        model_name=model_name,
        base_url=base_url,
        provider_hint=provider_hint,
        model_type=model_type,
        catalog=catalog,
        enabled=enabled,
    )
    duration_ms = (time.perf_counter() - start_perf) * 1000.0
    _record_suggestion_request(
        match_kind=result.match_kind.value,
        provider=result.suggested_provider,
        model_type=model_type,
        duration_ms=duration_ms,
    )
    return result


def _find_normalized_exact_key(
    clean_model_name: str,
    provider: str,
    active_catalog: Mapping[ProfileKey, CapabilityProfileLike],
) -> Optional[ProfileKey]:
    """Case/punctuation-insensitive exact match inside one provider's entries."""
    wanted = _normalize_catalog_exact_name(clean_model_name)
    for catalog_key in _provider_catalog(active_catalog, provider).keys():
        if _normalize_catalog_exact_name(catalog_key[1]) == wanted:
            return catalog_key
    return None


def _catalog_match(
    clean_model_name: str,
    provider: str,
    active_catalog: Mapping[ProfileKey, CapabilityProfileLike],
) -> Optional[CapacitySuggestionResult]:
    """Try the catalog match ladder: exact, normalized-exact, then fuzzy."""
    exact_profile = active_catalog.get((provider, clean_model_name))
    if exact_profile:
        return _result_from_profile(
            provider,
            clean_model_name,
            exact_profile,
            CapacitySuggestionMatchKind.CATALOG_EXACT,
        )

    normalized_exact_key = _find_normalized_exact_key(
        clean_model_name, provider, active_catalog
    )
    if normalized_exact_key:
        return _result_from_profile(
            normalized_exact_key[0],
            normalized_exact_key[1],
            active_catalog[normalized_exact_key],
            CapacitySuggestionMatchKind.CATALOG_EXACT,
        )

    fuzzy_match = _fuzzy_catalog_match(clean_model_name, active_catalog, provider)
    if fuzzy_match:
        fuzzy_key, profile = fuzzy_match
        return _result_from_profile(
            fuzzy_key[0],
            fuzzy_key[1],
            profile,
            CapacitySuggestionMatchKind.CATALOG_FUZZY,
        )
    return None


def _suggest_capacity_inner(
    model_name: str,
    base_url: Optional[str],
    provider_hint: Optional[str],
    model_type: Optional[str],
    catalog: Optional[Mapping[ProfileKey, CapabilityProfileLike]],
    enabled: bool,
) -> CapacitySuggestionResult:
    if not enabled:
        return _none_result("Capacity suggestion is disabled")

    clean_model_name = (model_name or "").strip()
    if not clean_model_name:
        raise ValueError("model_name is required")

    if len(clean_model_name) > 512:
        raise ValueError("model_name is too long")

    if model_type and model_type.lower() not in SUPPORTED_SUGGESTION_MODEL_TYPES:
        return _none_result(
            f"Capacity suggestion is not supported for model_type={model_type}"
        )

    active_catalog = catalog if catalog is not None else _get_default_catalog()

    provider = pick_provider(provider_hint, base_url, clean_model_name, active_catalog)
    if not provider:
        # Provider can't be inferred (e.g. base_url still empty while the user
        # is typing). The catalog needs a provider, but the bundled LiteLLM
        # JSON can still be matched by bare model name — give that a try
        # before giving up.
        litellm_result = _litellm_lookup(clean_model_name, None)
        if litellm_result is not None:
            return litellm_result
        return _none_result("No provider candidate could be inferred")

    catalog_result = _catalog_match(clean_model_name, provider, active_catalog)
    if catalog_result is not None:
        return catalog_result

    litellm_result = _litellm_lookup(clean_model_name, provider)
    if litellm_result is not None:
        return litellm_result

    return _none_result(
        f"No approved catalog profile matched provider={provider}, model={clean_model_name}"
    )


# =============================================================================
# LiteLLM lookup (match_kind=LITELLM_LOOKUP)
# =============================================================================
# When the catalog has no entry for a model, look it up in the bundled
# LiteLLM model_prices_and_context_window.json (3818 models, fetched at
# image build time so it works offline / without VPN). We map
# max_input_tokens -> context_window and max_output_tokens -> max_output;
# max_input / reserve stay None (SDK derives them from the combined window).

_LITELLM_JSON_PATH = NEXENT_LITELLM_JSON
_LITELLM_CACHE: Optional[dict] = None


def _litellm_cache() -> Optional[dict]:
    """Load the bundled LiteLLM JSON once and cache it in memory."""
    global _LITELLM_CACHE
    if _LITELLM_CACHE is not None:
        return _LITELLM_CACHE
    try:
        with open(_LITELLM_JSON_PATH, "r", encoding="utf-8") as f:
            _LITELLM_CACHE = json.load(f)
    except Exception as exc:
        logger.debug("LiteLLM JSON load failed (%s): %s", _LITELLM_JSON_PATH, exc)
        _LITELLM_CACHE = {}
    return _LITELLM_CACHE


def _litellm_exact_entry(
    cache: dict, target: str, provider: Optional[str]
) -> Optional[dict]:
    """Find the first cache entry whose key is one of the exact candidates."""
    candidates = []
    if provider:
        candidates.append(f"{provider}/{target}")
    candidates.append(target)
    # try matching by final segment (handles "org/model" naming)
    final_segment = target.split("/")[-1]
    if final_segment != target:
        candidates.append(final_segment)

    for cand in candidates:
        if cand in cache:
            return cache[cand]
    return None


def _litellm_cross_provider_entry(cache: dict, final_segment: str) -> Optional[dict]:
    """Find an entry across all providers whose final segment matches.

    Collects all case-insensitive matches and prefers one that has BOTH
    context and max_output (some providers leave max_output as null).
    """
    lowered = final_segment.lower()
    matches = [v for k, v in cache.items() if k.split("/")[-1].lower() == lowered]
    return next(
        (
            m
            for m in matches
            if m.get("max_input_tokens") and m.get("max_output_tokens")
        ),
        matches[0] if matches else None,
    )


def _positive_int(value: Any) -> Optional[int]:
    """Coerce to a positive int; None for missing/invalid/non-positive values."""
    if value is None:
        return None
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if n > 0 else None


def _litellm_lookup(
    model_name: str,
    provider: Optional[str],
) -> Optional[CapacitySuggestionResult]:
    """Look up model_name in the bundled LiteLLM JSON.

    Tries exact key match first (preferring the LiteLLM provider that maps to
    nexent's provider), then falls back to matching by the final path segment
    (e.g. deepseek-ai/DeepSeek-V4-Flash -> DeepSeek-V4-Flash) across all
    providers. Returns None if nothing usable is found.
    """
    cache = _litellm_cache()
    if not cache:
        return None

    target = model_name.strip()
    if not target:
        return None

    entry = _litellm_exact_entry(cache, target, provider)
    if entry is None:
        entry = _litellm_cross_provider_entry(cache, target.split("/")[-1])
    if not entry or not isinstance(entry, dict):
        return None

    # LiteLLM's max_input_tokens is the total context window (input+output);
    # max_output_tokens is the output cap. Map accordingly.
    context = _positive_int(entry.get("max_input_tokens"))
    max_output = _positive_int(entry.get("max_output_tokens"))
    if context is None and max_output is None:
        return None

    fields = CapacitySuggestionFields(
        context_window_tokens=context,
        max_input_tokens=None,
        max_output_tokens=max_output,
        default_output_reserve_tokens=None,
        tokenizer_family=None,
    )
    return CapacitySuggestionResult(
        suggestions=fields,
        match_kind=CapacitySuggestionMatchKind.LITELLM_LOOKUP,
        match_confidence=CapacitySuggestionConfidence.MEDIUM,
        match_explanation=f"Matched LiteLLM bundled catalog (3818 models) for {target}",
        suggested_provider=provider,
        canonical_model_name=target,
        capacity_source_on_accept="operator",
    )


CAPACITY_COVERAGE_MODEL_TYPES = {"llm", "vlm", "vlm2", "vlm3", "vlm4"}

# OpenTelemetry counter for silent catalog-matcher failures during the
# capacity-coverage scan. The matcher is called per row so we cannot raise --
# but the silent fallback to suggestion_available=False would hide a corrupt
# catalog entry that turns every "available" hint into "false" across a whole
# tenant. The counter gives staging/CI a single number to watch.
#
# Guarded the same way as the SDK monitor module: if OpenTelemetry is not
# installed (some deployments run without it), the counter is None and the
# increment becomes a no-op.
try:
    from opentelemetry import metrics as _otel_metrics

    _capacity_suggestion_meter = _otel_metrics.get_meter(
        "management.services.model.management"
    )
    _capacity_suggestion_coverage_errors_total = (
        _capacity_suggestion_meter.create_counter(
            name="model_capacity_suggestion_coverage_errors_total",
            description=(
                "Count of catalog-matcher exceptions raised while computing the "
                "per-row `suggestion_available` flag in /model/capacity-coverage. "
                "Non-zero means catalog data or matcher logic is broken; "
                "operators see every row as suggestion_available=False."
            ),
            unit="errors",
        )
    )
    # W11 spec line 709: emitted when the operator clicks "Use suggestion" and
    # saves. Combined with model_capacity_suggestion_dispatch_profile_hit_total
    # at /agent/run, gives the "95% of accepted catalog suggestions produce
    # the expected runtime capability_profile_version" SLO ratio.
    _capacity_suggestion_accept_total = _capacity_suggestion_meter.create_counter(
        name="model_capacity_suggestion_accept_total",
        description=(
            "Count of model save events that carried an accepted W11 "
            "capacity suggestion, labelled by match_kind and provider. "
            "Audit signal only -- not persisted to model_record_t."
        ),
        unit="accepts",
    )
except Exception:  # pragma: no cover - OTel is optional at runtime
    _capacity_suggestion_coverage_errors_total = None
    _capacity_suggestion_accept_total = None


# Per-process dedup for the warning log emitted when the catalog-matcher
# raises during /capacity-coverage. The OTel counter still increments per
# failure (no monitoring impact); only the log line is deduped, so a global
# catalog bug surfaces once per (model_id, error_type) instead of flooding
# logs on every endpoint call. Same pattern as
# `_warn_missing_capacity_once` in `backend/agents/create_agent_info.py`.
_CAPACITY_SUGGESTION_ERROR_EMITTED: set = set()
_CAPACITY_SUGGESTION_ERROR_LOCK = threading.Lock()


def _record_capacity_coverage_error(model_id: Optional[Any], exc: Exception) -> None:
    if _capacity_suggestion_coverage_errors_total is None:
        return
    try:
        _capacity_suggestion_coverage_errors_total.add(
            1,
            {
                "model_id": str(model_id) if model_id is not None else "unknown",
                "error_type": type(exc).__name__,
            },
        )
    except Exception:  # pragma: no cover - never break coverage for telemetry
        pass


# Wire-only fields the frontend ships when the operator clicks "Use suggestion"
# and saves. They are audit/metrics input; runtime never reads them. The app
# layer pops them off the request payload via `pop_capacity_accept_signal` so
# the service/DB layer never sees them.
_ACCEPT_SIGNAL_KEYS = (
    "accepted_suggestion_match_kind",
    "accepted_capability_profile_version",
)


def pop_capacity_accept_signal(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Strip audit-only accept-signal fields from a save payload and return them.

    Returns the popped values as {'match_kind': ..., 'capability_profile_version': ...}
    when match_kind is present, else None. Callers forward the dict to
    `_record_capacity_suggestion_accept` once the model_factory is known.
    """
    if not isinstance(payload, dict):
        return None
    popped = {key: payload.pop(key, None) for key in _ACCEPT_SIGNAL_KEYS}
    match_kind = popped.get("accepted_suggestion_match_kind")
    if not match_kind:
        return None
    return {
        "match_kind": match_kind,
        "capability_profile_version": popped.get("accepted_capability_profile_version"),
    }


def _record_capacity_suggestion_accept(
    match_kind: str, provider: Optional[str]
) -> None:
    """Emit the accept_total counter for one operator-accepted suggestion save."""
    if _capacity_suggestion_accept_total is None:
        return
    try:
        _capacity_suggestion_accept_total.add(
            1,
            {
                "match_kind": match_kind,
                "provider": (provider or "unknown").lower(),
            },
        )
    except Exception:  # pragma: no cover - never break save for telemetry
        pass


def _is_bare_capacity_model(model: Dict[str, Any]) -> bool:
    return (
        model.get("context_window_tokens") is None
        or model.get("max_output_tokens") is None
    )


def _capacity_suggestion_available(model: Dict[str, Any]) -> bool:
    if not CAPACITY_SUGGESTION_ENABLED:
        return False

    try:
        model_name = add_repo_to_name(
            model.get("model_repo", ""), model.get("model_name", "")
        )
        result = suggest_capacity(
            model_name=model_name,
            base_url=model.get("base_url"),
            provider_hint=model.get("model_factory"),
            model_type=model.get("model_type"),
            enabled=CAPACITY_SUGGESTION_ENABLED,
        )
        return result.match_kind != CapacitySuggestionMatchKind.NONE
    except Exception as exc:
        # A catalog-matcher exception must not break /capacity-coverage --
        # the endpoint scans every LLM/VLM row, and one bad row would make
        # the whole tenant view explode. We fall back to False and emit a
        # counter so a corrupt catalog is visible in metrics instead of
        # silently turning every row into "no suggestion available".
        dedup_key = (model.get("model_id"), type(exc).__name__)
        should_log = False
        with _CAPACITY_SUGGESTION_ERROR_LOCK:
            if dedup_key not in _CAPACITY_SUGGESTION_ERROR_EMITTED:
                _CAPACITY_SUGGESTION_ERROR_EMITTED.add(dedup_key)
                should_log = True
        if should_log:
            logger.warning(
                "Capacity coverage suggestion check failed for model_id=%s: %s "
                "(per-process dedup; OTel counter still increments per failure)",
                model.get("model_id"),
                exc,
            )
        _record_capacity_coverage_error(model.get("model_id"), exc)
        return False


def get_capacity_coverage(tenant_id: str) -> Dict[str, Any]:
    """Return bare-capacity LLM/VLM coverage for one tenant."""
    if not CAPACITY_VISIBILITY_ENABLED:
        return {
            "total_llm_vlm": 0,
            "bare_count": 0,
            "bare_models": [],
        }

    records = get_model_records(None, tenant_id)
    scoped_records = [
        model
        for model in records
        if model.get("model_type") in CAPACITY_COVERAGE_MODEL_TYPES
    ]
    bare_models = [
        {
            "model_id": model["model_id"],
            "model_name": add_repo_to_name(
                model.get("model_repo", ""), model.get("model_name", "")
            ),
            "model_factory": model.get("model_factory"),
            "model_type": model.get("model_type"),
            "max_tokens": model.get("max_tokens"),
            "suggestion_available": _capacity_suggestion_available(model),
        }
        for model in scoped_records
        if _is_bare_capacity_model(model)
    ]

    return {
        "total_llm_vlm": len(scoped_records),
        "bare_count": len(bare_models),
        "bare_models": bare_models,
    }
