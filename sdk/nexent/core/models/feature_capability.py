"""Model-level reasoning and prompt-cache capability resolution.

The OpenAI ``/models`` schema only guarantees identity fields.  Compatible
providers may add capability fields, so this module consumes a strict allow
list of such extensions and otherwise resolves a backend-supplied catalog.
It never performs inference probes and never reads environment variables.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping, Optional, Sequence


FEATURE_CAPABILITY_SCHEMA_VERSION = 1
UNKNOWN_FEATURE_CAPABILITIES = {
    "reasoning": {
        "supported": None,
        "mode": "unknown",
        "request_style": "unknown",
        "efforts": [],
        "default_effort": None,
    },
    "prompt_cache": {
        "supported": None,
        "mode": "unknown",
        "metrics_available": None,
    },
}

_REASONING_BOOL_KEYS = (
    "reasoning_supported",
    "supports_reasoning",
    "thinking_supported",
    "supports_thinking",
)
_CACHE_BOOL_KEYS = (
    "prompt_cache_supported",
    "supports_prompt_cache",
    "cache_supported",
    "supports_caching",
)
_PARAMETER_KEYS = ("supported_parameters", "supported_params", "parameters")
_NESTED_KEYS = ("capabilities", "features", "model_info", "inference_metadata")
_VALID_REASONING_MODES = {"always", "toggle", "effort", "none", "unknown"}
_VALID_REQUEST_STYLES = {
    "openai_reasoning_effort",
    "extra_body_enable_thinking",
    "none",
    "unknown",
}
_VALID_CACHE_MODES = {
    "openai_automatic",
    "provider_automatic",
    "anthropic_ephemeral",
    "none",
    "unknown",
}


def _mapping_candidates(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates = [raw]
    for key in _NESTED_KEYS:
        nested = raw.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    return candidates


def _first_bool(candidates: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> Optional[bool]:
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if isinstance(value, bool):
                return value
    return None


def _parameter_names(candidates: Sequence[Mapping[str, Any]]) -> set[str]:
    names: set[str] = set()
    for candidate in candidates:
        for key in _PARAMETER_KEYS:
            values = candidate.get(key)
            if isinstance(values, (list, tuple, set)):
                names.update(str(value).strip().lower() for value in values if str(value).strip())
    return names


def extract_provider_feature_candidate(raw: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Extract explicit provider extensions without retaining the raw row."""
    if not isinstance(raw, Mapping):
        return None
    candidates = _mapping_candidates(raw)
    parameters = _parameter_names(candidates)
    reasoning_supported = _first_bool(candidates, _REASONING_BOOL_KEYS)
    cache_supported = _first_bool(candidates, _CACHE_BOOL_KEYS)

    request_style = "unknown"
    if "reasoning_effort" in parameters or "reasoning.effort" in parameters:
        reasoning_supported = True if reasoning_supported is None else reasoning_supported
        request_style = "openai_reasoning_effort"
    elif "enable_thinking" in parameters:
        reasoning_supported = True if reasoning_supported is None else reasoning_supported
        request_style = "extra_body_enable_thinking"

    cache_mode = "unknown"
    if "cache_control" in parameters:
        cache_supported = True if cache_supported is None else cache_supported
        cache_mode = "anthropic_ephemeral"
    elif "prompt_cache_key" in parameters or "prompt_cache_retention" in parameters:
        cache_supported = True if cache_supported is None else cache_supported
        cache_mode = "openai_automatic"

    efforts: list[str] = []
    for candidate in candidates:
        value = candidate.get("reasoning_efforts") or candidate.get("supported_reasoning_efforts")
        if isinstance(value, (list, tuple)):
            efforts = [str(item).strip().lower() for item in value if str(item).strip()]
            break
    default_effort = None
    for candidate in candidates:
        value = candidate.get("default_reasoning_effort") or candidate.get("reasoning_effort_default")
        if isinstance(value, str) and value.strip():
            default_effort = value.strip().lower()
            break

    if reasoning_supported is None and cache_supported is None:
        return None

    warnings: list[str] = []
    if reasoning_supported is False and (request_style != "unknown" or efforts):
        warnings.append("conflicting_reasoning_extension")
        reasoning_supported = None
        request_style = "unknown"
        efforts = []
    if cache_supported is False and cache_mode != "unknown":
        warnings.append("conflicting_prompt_cache_extension")
        cache_supported = None
        cache_mode = "unknown"

    return {
        "schema_version": FEATURE_CAPABILITY_SCHEMA_VERSION,
        "reasoning": {
            "supported": reasoning_supported,
            "mode": "effort" if request_style == "openai_reasoning_effort" else (
                "toggle" if request_style == "extra_body_enable_thinking" else (
                    "none" if reasoning_supported is False else "unknown"
                )
            ),
            "request_style": request_style if reasoning_supported is not False else "none",
            "efforts": efforts,
            "default_effort": default_effort,
        },
        "prompt_cache": {
            "supported": cache_supported,
            "mode": cache_mode if cache_supported is not False else "none",
            "metrics_available": None,
        },
        "source": "provider_extension",
        "warnings": warnings,
    }


def _normalize_branch(profile: Mapping[str, Any], branch: str) -> dict[str, Any]:
    defaults = deepcopy(UNKNOWN_FEATURE_CAPABILITIES[branch])
    value = profile.get(branch)
    if not isinstance(value, Mapping):
        return defaults
    defaults.update({key: deepcopy(item) for key, item in value.items() if key in defaults})
    if defaults["supported"] not in (True, False, None):
        return deepcopy(UNKNOWN_FEATURE_CAPABILITIES[branch])
    if branch == "reasoning":
        if defaults["mode"] not in _VALID_REASONING_MODES:
            defaults["mode"] = "unknown"
        if defaults["request_style"] not in _VALID_REQUEST_STYLES:
            defaults["request_style"] = "unknown"
        if not isinstance(defaults["efforts"], list):
            defaults["efforts"] = []
        defaults["efforts"] = [
            str(item).strip().lower()
            for item in defaults["efforts"]
            if str(item).strip()
        ]
        default_effort = defaults.get("default_effort")
        if not isinstance(default_effort, str) or default_effort.lower() not in defaults["efforts"]:
            defaults["default_effort"] = None
        else:
            defaults["default_effort"] = default_effort.lower()
    elif defaults["mode"] not in _VALID_CACHE_MODES:
        defaults["mode"] = "unknown"
    return defaults


def normalize_feature_profile(profile: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Validate a persisted or catalog profile and discard unknown fields."""
    if not isinstance(profile, Mapping):
        return None
    return {
        "schema_version": FEATURE_CAPABILITY_SCHEMA_VERSION,
        "reasoning": _normalize_branch(profile, "reasoning"),
        "prompt_cache": _normalize_branch(profile, "prompt_cache"),
        "source": str(profile.get("source") or "unknown"),
        "match_kind": str(profile.get("match_kind") or "unknown"),
        "profile_version": profile.get("profile_version"),
        "catalog_revision": profile.get("catalog_revision"),
        "evidence": [str(item) for item in profile.get("evidence", []) if isinstance(item, str)],
        "warnings": [str(item) for item in profile.get("warnings", []) if isinstance(item, str)],
    }


def resolve_feature_capabilities(
    provider: Optional[str],
    model: Optional[str],
    *,
    provider_candidate: Optional[Mapping[str, Any]] = None,
    exact_catalog: Optional[Mapping[tuple[str, str], Mapping[str, Any]]] = None,
    family_rules: Sequence[Mapping[str, Any]] = (),
    catalog_revision: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve one model profile with deterministic, fail-closed precedence."""
    provider_key = str(provider or "").strip().lower()
    model_key = str(model or "").strip()

    normalized_candidate = normalize_feature_profile(provider_candidate)
    if normalized_candidate and provider_candidate:
        has_explicit_value = any(
            normalized_candidate[branch]["supported"] is not None
            for branch in ("reasoning", "prompt_cache")
        )
        if has_explicit_value:
            normalized_candidate.update({
                "source": "provider_extension",
                "match_kind": "provider_extension",
                "catalog_revision": catalog_revision,
            })
            return normalized_candidate

    catalog = exact_catalog or {}
    exact = next(
        (
            value for (row_provider, row_model), value in catalog.items()
            if str(row_provider).lower() == provider_key and str(row_model).lower() == model_key.lower()
        ),
        None,
    )
    if exact is not None:
        result = normalize_feature_profile(exact) or normalize_feature_profile({})
        result.update({"source": "catalog_exact", "match_kind": "catalog_exact", "catalog_revision": catalog_revision})
        return result

    for rule in family_rules:
        if str(rule.get("provider") or "").lower() != provider_key:
            continue
        pattern = rule.get("pattern")
        if not isinstance(pattern, str) or not re.fullmatch(pattern, model_key, flags=re.IGNORECASE):
            continue
        exclusions = rule.get("exclusions") or ()
        if any(re.fullmatch(str(item), model_key, flags=re.IGNORECASE) for item in exclusions):
            continue
        result = normalize_feature_profile(rule) or normalize_feature_profile({})
        result.update({"source": "catalog_family", "match_kind": "catalog_family", "catalog_revision": catalog_revision})
        return result

    result = normalize_feature_profile({})
    result.update({"source": "unknown", "match_kind": "none", "catalog_revision": catalog_revision})
    return result


def resolve_effective_feature_policy(
    feature_capabilities: Optional[Mapping[str, Any]],
    preferences: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Resolve runtime behavior without mutating model capability facts.

    Confirmed capabilities are enabled by default. Optional preferences are a
    future-facing override contract and can narrow, but never expand, confirmed
    model support.
    """
    profile = normalize_feature_profile(feature_capabilities) or normalize_feature_profile({})
    preference_map = preferences if isinstance(preferences, Mapping) else {}
    reasoning_preference = preference_map.get("reasoning")
    reasoning_preference = reasoning_preference if isinstance(reasoning_preference, Mapping) else {}
    cache_preference = preference_map.get("prompt_cache")
    cache_preference = cache_preference if isinstance(cache_preference, Mapping) else {}
    warnings: list[str] = []

    reasoning = profile["reasoning"]
    reasoning_supported = reasoning.get("supported") is True
    reasoning_mode = str(reasoning.get("mode") or "unknown")
    reasoning_enabled = reasoning_supported
    requested_reasoning_enabled = reasoning_preference.get("enabled")
    effort = reasoning.get("default_effort") if reasoning_mode == "effort" else None

    preferred_effort = reasoning_preference.get("effort")
    if isinstance(preferred_effort, str):
        preferred_effort = preferred_effort.strip().lower()
        if preferred_effort in reasoning.get("efforts", []):
            effort = preferred_effort
        elif preferred_effort:
            warnings.append("unsupported_reasoning_effort_preference")

    if requested_reasoning_enabled is False and reasoning_supported:
        if reasoning_mode == "always":
            warnings.append("reasoning_disable_unsupported")
        elif reasoning_mode == "effort" and "none" in reasoning.get("efforts", []):
            reasoning_enabled = False
            effort = "none"
        elif reasoning_mode == "toggle":
            reasoning_enabled = False
        else:
            warnings.append("reasoning_disable_unsupported")
    elif requested_reasoning_enabled is True and not reasoning_supported:
        warnings.append("reasoning_enable_unsupported")

    cache = profile["prompt_cache"]
    cache_supported = cache.get("supported") is True
    cache_enabled = cache_supported
    requested_cache_enabled = cache_preference.get("enabled")
    if requested_cache_enabled is False:
        cache_enabled = False
    elif requested_cache_enabled is True and not cache_supported:
        warnings.append("prompt_cache_enable_unsupported")

    return {
        "reasoning": {
            "supported": reasoning.get("supported"),
            "enabled": reasoning_enabled,
            "mode": reasoning_mode,
            "request_style": reasoning.get("request_style") or "unknown",
            "effort": effort,
        },
        "prompt_cache": {
            "supported": cache.get("supported"),
            "enabled": cache_enabled,
            "mode": cache.get("mode") or "unknown",
        },
        "source": "user_preference" if preference_map else "nexent_default",
        "warnings": warnings,
    }


def apply_reasoning_request_policy(
    completion_kwargs: Mapping[str, Any],
    effective_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply one normalized reasoning policy to an OpenAI-compatible payload."""
    request = dict(completion_kwargs)
    extra_body = request.get("extra_body")
    safe_extra_body = dict(extra_body) if isinstance(extra_body, Mapping) else {}

    request.pop("reasoning_effort", None)
    safe_extra_body.pop("enable_thinking", None)
    safe_extra_body.pop("reasoning", None)
    template_kwargs = safe_extra_body.get("chat_template_kwargs")
    if isinstance(template_kwargs, Mapping) and "enable_thinking" in template_kwargs:
        retained_template_kwargs = {
            key: value for key, value in template_kwargs.items() if key != "enable_thinking"
        }
        if retained_template_kwargs:
            safe_extra_body["chat_template_kwargs"] = retained_template_kwargs
        else:
            safe_extra_body.pop("chat_template_kwargs", None)

    reasoning = effective_policy.get("reasoning")
    reasoning = reasoning if isinstance(reasoning, Mapping) else {}
    enabled = reasoning.get("enabled") is True
    mode = str(reasoning.get("mode") or "unknown")
    request_style = str(reasoning.get("request_style") or "unknown")
    if request_style == "openai_reasoning_effort" and mode == "effort":
        effort = reasoning.get("effort")
        if isinstance(effort, str) and effort:
            request["reasoning_effort"] = effort
    elif request_style == "extra_body_enable_thinking" and mode == "toggle":
        safe_extra_body["enable_thinking"] = enabled

    if safe_extra_body:
        request["extra_body"] = safe_extra_body
    else:
        request.pop("extra_body", None)
    return request
