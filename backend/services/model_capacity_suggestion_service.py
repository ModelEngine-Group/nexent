import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from consts.const import CAPACITY_SUGGESTION_ENABLED

logger = logging.getLogger(__name__)

# OpenTelemetry instruments for W11 catalog match observability.
# Spec lines 706-708. Guarded the same way as the SDK monitor module: if
# OpenTelemetry is not installed (some deployments run without it), the
# instruments are None and the recording becomes a no-op.
try:
    from opentelemetry import metrics as _otel_metrics

    _suggestion_meter = _otel_metrics.get_meter(__name__)
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


ProfileKey = tuple[str, str]
CapabilityProfileLike = Any


class CapacitySuggestionMatchKind(str, Enum):
    CATALOG_EXACT = "catalog_exact"
    CATALOG_FUZZY = "catalog_fuzzy"
    PROVIDER_DISCOVERY = "provider_discovery"
    NONE = "none"


class CapacitySuggestionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class CapacitySuggestionFields:
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None
    tokenizer_family: Optional[str] = None


@dataclass(frozen=True)
class CapacitySuggestionResult:
    suggestions: Optional[CapacitySuggestionFields]
    match_kind: CapacitySuggestionMatchKind
    match_confidence: Optional[CapacitySuggestionConfidence]
    match_explanation: str
    suggested_provider: Optional[str] = None
    canonical_model_name: Optional[str] = None
    capability_profile_version: Optional[str] = None
    capacity_source_on_accept: Optional[str] = None


# Substring patterns matched against the lower-cased base_url. Order matters:
# `in` returns the first hit, so place more-specific patterns before broader
# ones (e.g. `dashscope` before `aliyuncs`). Patterns mirror frontend
# PROVIDER_HINTS in `frontend/const/modelConfig.ts` so backend provider-by-URL
# detection stays consistent with the icon the user sees in the UI.
HOST_PROVIDER_PATTERNS = (
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

SUPPORTED_SUGGESTION_MODEL_TYPES = {"llm", "vlm", "vlm2", "vlm3"}


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
    from consts.capability_profiles import CATALOG

    return CATALOG


def suggest_capacity(
    model_name: str,
    base_url: Optional[str] = None,
    provider_hint: Optional[str] = None,
    model_type: Optional[str] = None,
    api_key: Optional[str] = None,
    catalog: Optional[Mapping[ProfileKey, CapabilityProfileLike]] = None,
    enabled: bool = CAPACITY_SUGGESTION_ENABLED,
) -> CapacitySuggestionResult:
    start_perf = time.perf_counter()
    result = _suggest_capacity_inner(
        model_name=model_name,
        base_url=base_url,
        provider_hint=provider_hint,
        model_type=model_type,
        api_key=api_key,
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


def _suggest_capacity_inner(
    model_name: str,
    base_url: Optional[str],
    provider_hint: Optional[str],
    model_type: Optional[str],
    api_key: Optional[str],
    catalog: Optional[Mapping[ProfileKey, CapabilityProfileLike]],
    enabled: bool,
) -> CapacitySuggestionResult:
    del api_key

    if not enabled:
        return _none_result("Capacity suggestion is disabled")

    clean_model_name = (model_name or "").strip()
    if not clean_model_name:
        raise ValueError("model_name is required")

    if len(clean_model_name) > 512:
        raise ValueError("model_name is too long")

    if model_type and model_type.lower() not in SUPPORTED_SUGGESTION_MODEL_TYPES:
        return _none_result(f"Capacity suggestion is not supported for model_type={model_type}")

    active_catalog = catalog if catalog is not None else _get_default_catalog()

    provider = pick_provider(provider_hint, base_url, clean_model_name, active_catalog)
    if not provider:
        return _none_result("No provider candidate could be inferred")

    exact_key = (provider, clean_model_name)
    exact_profile = active_catalog.get(exact_key)
    if exact_profile:
        return _result_from_profile(
            provider,
            clean_model_name,
            exact_profile,
            CapacitySuggestionMatchKind.CATALOG_EXACT,
        )

    normalized_exact_key = None
    for catalog_key in _provider_catalog(active_catalog, provider).keys():
        if _normalize_catalog_exact_name(catalog_key[1]) == _normalize_catalog_exact_name(clean_model_name):
            normalized_exact_key = catalog_key
            break

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

    return _none_result(f"No approved catalog profile matched provider={provider}, model={clean_model_name}")
