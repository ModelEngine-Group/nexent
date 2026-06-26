"""Provider prompt-cache capability, directive, and usage helpers.

Context partitioning, stable-prefix ordering, fingerprints, and change reasons
are owned by ContextManager.  Provider adapters must decide only whether their
API requires cache-related request fields, using provider/model configuration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Tuple


PROMPT_CACHE_CAPABILITY_VERSION = "w3.capabilities.v1"


# Conservative allow-list.  Unknown providers must not receive cache-specific
# request fields merely because they speak an OpenAI-compatible protocol.
APPROVED_PROVIDER_PROMPT_CACHE_PROFILES: Dict[str, Dict[str, Any]] = {
    "openai": {
        "mode": "openai_automatic",
        "enabled": True,
        "metrics_available": True,
        "cached_input_discount": 0.5,
        "serialization_version": "openai_chat_completions.v1",
        "capability_version": PROMPT_CACHE_CAPABILITY_VERSION,
    },
}


@dataclass(frozen=True)
class CacheDirectiveAdvice:
    mode: str = "unknown"
    supported: bool = False
    directives: Tuple[str, ...] = ()
    reason: str = "capability_unknown"


@dataclass(frozen=True)
class PromptCacheUsage:
    cached_input_tokens: int
    uncached_input_tokens: int
    provider_cache_hit: bool
    hit_ratio: float
    metrics_source: str
    estimated_saved_input_tokens: float = 0.0
    estimated_input_savings_ratio: float = 0.0

    def to_attributes(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_prompt_cache_profile(
    provider: Optional[str],
    explicit_profile: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Return a normalized, explicitly approved provider cache profile."""
    provider_name = (provider or "").lower()
    profile: Optional[Mapping[str, Any]] = explicit_profile
    if profile is None:
        profile = APPROVED_PROVIDER_PROMPT_CACHE_PROFILES.get(provider_name)
    if not profile:
        return None

    normalized = _normalize_capability_profile(profile)
    normalized.setdefault("provider", provider_name or "unknown")
    normalized.setdefault("capability_version", PROMPT_CACHE_CAPABILITY_VERSION)
    normalized.setdefault("serialization_version", _serialization_version(provider_name))
    return normalized


def cache_directive_advice(
    capability_profile: Optional[Mapping[str, Any]],
) -> CacheDirectiveAdvice:
    """Decide provider protocol behavior from provider/model config only."""
    return _directive_advice(_normalize_capability_profile(capability_profile or {}))


def apply_cache_directives(
    completion_kwargs: Mapping[str, Any],
    advice: CacheDirectiveAdvice,
) -> Dict[str, Any]:
    """Apply provider-specific cache directives without reordering payloads."""
    request = dict(completion_kwargs)
    if "cache_control:ephemeral" not in advice.directives:
        return request

    messages = [_copy_request_message(message) for message in request.get("messages", [])]
    last_stable_index = -1
    for index, message in enumerate(messages):
        if message.get("role") in {"system", "developer"}:
            last_stable_index = index
        else:
            break
    if last_stable_index < 0:
        return request

    content = messages[last_stable_index].get("content")
    if isinstance(content, str):
        messages[last_stable_index]["content"] = [
            {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
        ]
    elif isinstance(content, list) and content:
        blocks = [_normalize_for_json(block) for block in content]
        if isinstance(blocks[-1], dict):
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
        messages[last_stable_index]["content"] = blocks
    request["messages"] = messages
    return request


def extract_prompt_cache_usage(
    usage: Any,
    input_tokens: int,
    capability_profile: Optional[Mapping[str, Any]] = None,
) -> PromptCacheUsage:
    """Extract provider-reported cache metrics without inventing cache hits."""
    if capability_profile is None:
        return PromptCacheUsage(
            cached_input_tokens=0,
            uncached_input_tokens=max(0, input_tokens or 0),
            provider_cache_hit=False,
            hit_ratio=0.0,
            metrics_source="capability_unknown",
        )

    cached, source = _extract_cached_input_tokens(usage)
    uncached = max(0, (input_tokens or 0) - cached)
    total = cached + uncached
    profile = _normalize_capability_profile(capability_profile or {})
    discount = profile.get("cached_input_discount", 0.0)
    try:
        discount = max(0.0, min(float(discount), 1.0))
    except (TypeError, ValueError):
        discount = 0.0
    return PromptCacheUsage(
        cached_input_tokens=cached,
        uncached_input_tokens=uncached,
        provider_cache_hit=cached > 0,
        hit_ratio=round(cached / total, 4) if total else 0.0,
        metrics_source=source,
        estimated_saved_input_tokens=round(cached * discount, 2),
        estimated_input_savings_ratio=round((cached * discount) / total, 4) if total else 0.0,
    )


def _normalize_capability_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    candidate: Any = profile.get("prompt_cache", profile)
    if isinstance(candidate, str):
        candidate = {"mode": candidate}
    if not isinstance(candidate, Mapping):
        return {"mode": "unknown", "enabled": False}
    normalized = dict(candidate)
    mode = str(normalized.get("mode") or "unknown").lower()
    normalized["mode"] = mode
    normalized["enabled"] = bool(normalized.get("enabled", mode not in {"unknown", "none", "disabled", ""}))
    return normalized


def _directive_advice(profile: Optional[Mapping[str, Any]]) -> CacheDirectiveAdvice:
    if not profile:
        return CacheDirectiveAdvice(reason="capability_profile_missing")
    mode = str(profile.get("mode") or "unknown").lower()
    if not profile.get("enabled") or mode in {"unknown", "none", "disabled", ""}:
        return CacheDirectiveAdvice(mode=mode, reason="capability_unknown")
    if mode in {"openai_automatic", "provider_automatic", "automatic"}:
        return CacheDirectiveAdvice(mode=mode, supported=True, reason="provider_automatic_cache")
    if mode == "anthropic_ephemeral":
        return CacheDirectiveAdvice(
            mode=mode,
            supported=True,
            directives=("cache_control:ephemeral",),
            reason="provider_declares_cache_control",
        )
    return CacheDirectiveAdvice(mode=mode, reason="unrecognized_mode")


def _extract_cached_input_tokens(usage: Any) -> Tuple[int, str]:
    candidates = (
        ("prompt_tokens_details", "cached_tokens", "openai_prompt_tokens_details"),
        ("input_tokens_details", "cached_tokens", "openai_input_tokens_details"),
        ("input_token_details", "cache_read", "anthropic_input_token_details"),
        ("input_token_details", "cache_read_input_tokens", "anthropic_input_token_details"),
        (None, "cached_tokens", "top_level_fallback"),
        (None, "cache_read_input_tokens", "top_level_fallback"),
    )
    for parent_name, child_name, source in candidates:
        value = _get_value(_get_value(usage, parent_name), child_name) if parent_name else _get_value(usage, child_name)
        if value is None:
            continue
        try:
            cached = int(value)
        except (TypeError, ValueError):
            continue
        return max(cached, 0), source
    return 0, "none"


def _get_value(value: Any, key: Optional[str]) -> Any:
    if key is None:
        return value
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _copy_request_message(message: Any) -> Dict[str, Any]:
    normalized = _normalize_for_json(message)
    if isinstance(normalized, Mapping):
        return dict(normalized)
    return {"role": getattr(message, "role", "user"), "content": str(message)}


def _normalize_for_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_for_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_json(item) for item in value]
    if hasattr(value, "model_dump"):
        return _normalize_for_json(value.model_dump())
    if hasattr(value, "__dict__"):
        return _normalize_for_json(vars(value))
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


def _serialization_version(provider: str) -> str:
    return {
        "openai": "openai_chat_completions.v1",
        "anthropic": "anthropic_messages.v1",
    }.get((provider or "").lower(), "unknown")
