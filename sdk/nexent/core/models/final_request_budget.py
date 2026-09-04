"""Trusted final Provider-request metering and bounded usage calibration.

The request passed here is the already-rendered adapter payload.  This module
never stores request content: evidence consists only of hashes, classifications
and numerical counts.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from ..utils.token_estimation import estimate_tokens_text


ESTIMATOR_VERSION = "final-request-v1"
DEFAULT_CORRECTION_MULTIPLIER = 1.15
MIN_CALIBRATION_SAMPLES = 20
MAX_CALIBRATION_SAMPLES = 256
CALIBRATION_TTL_SECONDS = 24 * 60 * 60
MAX_OBSERVED_RATIO = 4.0
MAX_GATE_MULTIPLIER = 2.0
TOOL_PROTOCOL_OVERHEAD_TOKENS = 208

RequestShape = Literal["text", "tools", "media", "tools_media"]
CountSource = Literal["provider", "tokenizer", "estimated", "provider_anchor_delta"]
SideEffectState = Literal[
    "pristine", "response_started", "tool_effect", "application_effect", "persisted"
]

_TRANSPORT_KEYS = frozenset(
    {
        "stream",
        "stream_options",
        "timeout",
        "request_timeout",
        "http_client",
    }
)
_NON_TOKEN_CONTROL_KEYS = frozenset(
    {
        "model",
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "n",
        "stop",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "parallel_tool_calls",
        "tool_choice",
    }
)
_REASONING_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_effort",
        "thinking",
        "enable_thinking",
        "chat_template_kwargs",
    }
)
_MEDIA_TYPES = frozenset(
    {
        "image",
        "image_url",
        "input_image",
        "audio",
        "input_audio",
        "file",
        "document",
    }
)


class FinalRequestBudgetError(Exception):
    reason_code = "final_request_budget_error"


class FinalRequestOverHardBudget(FinalRequestBudgetError):
    reason_code = "final_request_over_hard_budget"

    def __init__(
        self,
        *,
        actual: int,
        hard_budget: int,
        preflight: Optional["FinalRequestPreflight"] = None,
    ) -> None:
        self.actual = actual
        self.hard_budget = hard_budget
        self.preflight = preflight
        super().__init__(
            f"{self.reason_code}: final request {actual} exceeds hard budget {hard_budget}"
        )


class StaleRequestBudgetIdentity(FinalRequestBudgetError):
    reason_code = "stale_request_budget_identity"


class FinalRequestSoftBudgetExceeded(FinalRequestBudgetError):
    reason_code = "final_request_over_soft_budget"

    def __init__(self, preflight: "FinalRequestPreflight") -> None:
        self.preflight = preflight
        super().__init__(
            f"{self.reason_code}: final request {preflight.soft_count} exceeds "
            f"soft budget {preflight.soft_budget}"
        )


class ProviderContextOverflow(FinalRequestBudgetError):
    reason_code = "provider_context_overflow"


class ProviderContextOverflowRetryUnsafe(FinalRequestBudgetError):
    reason_code = "provider_context_overflow_retry_unsafe"


class ProviderContextOverflowRetryExhausted(FinalRequestBudgetError):
    reason_code = "provider_context_overflow_retry_exhausted"


class CompactionNoReduction(FinalRequestBudgetError):
    reason_code = "compaction_no_reduction"


class ContextRebuildOverBudget(FinalRequestBudgetError):
    """A source-backed rebuild could not satisfy its requested input target."""

    reason_code = "context_rebuild_over_budget"

    def __init__(self, *, failure_reason: str, actual: int, hard_budget: int) -> None:
        self.context_rebuild_over_budget = True
        self.failure_reason = failure_reason
        self.actual = actual
        self.hard_budget = hard_budget
        super().__init__(
            f"{failure_reason}: Context input remains over the model hard budget "
            f"after compaction: {actual} > {hard_budget} tokens"
        )


class RequestSideEffectGuard:
    """Monotonic proof that a physical request is still safe to rebuild."""

    _ORDER = {
        "pristine": 0,
        "response_started": 1,
        "tool_effect": 2,
        "application_effect": 3,
        "persisted": 4,
    }

    def __init__(self) -> None:
        self._state: SideEffectState = "pristine"
        self._lock = threading.Lock()

    @property
    def state(self) -> SideEffectState:
        with self._lock:
            return self._state

    @property
    def recovery_safe(self) -> bool:
        return self.state == "pristine"

    def mark(self, state: SideEffectState) -> None:
        with self._lock:
            if self._ORDER[state] > self._ORDER[self._state]:
                self._state = state


def is_provider_context_overflow(error: BaseException) -> bool:
    """Classify structured OpenAI-compatible overflow errors conservatively."""
    code = getattr(error, "code", None)
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        nested = body.get("error") if isinstance(body.get("error"), Mapping) else body
        code = code or nested.get("code") or nested.get("type")
    if str(code or "").lower() in {
        "context_length_exceeded",
        "max_tokens_exceeded",
        "input_too_long",
    }:
        return True
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "context_length_exceeded",
            "maximum context length",
            "input tokens exceed",
            "too many tokens",
        )
    )


@dataclass(frozen=True)
class FinalRequestIdentity:
    endpoint_fingerprint: str
    credential_scope_fingerprint: str
    canonical_model_id: str
    provider: str
    model_name: str
    w1_fingerprint: str
    w2_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "endpoint": self.endpoint_fingerprint,
                "scope": self.credential_scope_fingerprint,
                "canonical_model": self.canonical_model_id,
                "provider": self.provider,
                "model": self.model_name,
                "w1": self.w1_fingerprint,
                "w2": self.w2_fingerprint,
            }
        )


@dataclass(frozen=True)
class RequestComponentCounts:
    message_text: int = 0
    message_framing: int = 0
    tools: int = 0
    media: int = 0
    reasoning: int = 0
    other_semantic: int = 0

    @property
    def raw_total(self) -> int:
        return max(
            1,
            self.message_text
            + self.message_framing
            + self.tools
            + self.media
            + self.reasoning
            + self.other_semantic,
        )


@dataclass(frozen=True)
class FinalRequestShape:
    fingerprint: str
    request_shape: RequestShape
    reasoning_mode: str
    semantic_request: Mapping[str, Any] = field(repr=False, compare=False)
    components: RequestComponentCounts = field(default_factory=RequestComponentCounts)


@dataclass(frozen=True)
class CalibrationKey:
    endpoint_fingerprint: str
    credential_scope_fingerprint: str
    canonical_model_id: str
    request_shape: RequestShape
    reasoning_mode: str
    estimator_version: str = ESTIMATOR_VERSION

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.__dict__)


@dataclass(frozen=True)
class CalibrationStats:
    sample_count: int = 0
    mature: bool = False
    p95: Optional[float] = None
    p99: Optional[float] = None


@dataclass(frozen=True)
class FinalRequestPreflight:
    request_id: str
    request_fingerprint: str
    identity_fingerprint: str
    request_shape: RequestShape
    reasoning_mode: str
    count_source: CountSource
    components: RequestComponentCounts
    raw_estimate: int
    provider_count: Optional[int]
    soft_count: int
    hard_count: int
    soft_budget: int
    hard_budget: int
    soft_exceeded: bool
    hard_exceeded: bool
    calibration_key_fingerprint: str
    calibration_sample_count: int
    calibration_p95: Optional[float]
    calibration_p99: Optional[float]
    fallback_reason: Optional[str]
    stable_semantic_fingerprint: str = ""
    context_stable_fingerprint: str = ""
    message_fingerprints: tuple[str, ...] = ()
    anchor_input_tokens: Optional[int] = None
    estimated_delta_tokens: Optional[int] = None
    anchor_invalidation_reason: Optional[str] = None
    retry_ordinal: int = 0
    estimator_version: str = ESTIMATOR_VERSION


@dataclass(frozen=True)
class _Sample:
    request_id: str
    ratio: float
    observed_at: float


@dataclass(frozen=True)
class _ObservedRequestAnchor:
    identity_fingerprint: str
    stable_semantic_fingerprint: str
    context_stable_fingerprint: str
    message_fingerprints: tuple[str, ...]
    input_tokens: int


class CalibrationStore:
    """Bounded, expiring and request-id-deduplicated calibration samples."""

    def __init__(
        self,
        *,
        max_samples: int = MAX_CALIBRATION_SAMPLES,
        ttl_seconds: int = CALIBRATION_TTL_SECONDS,
        minimum_samples: int = MIN_CALIBRATION_SAMPLES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_samples = max_samples
        self.ttl_seconds = ttl_seconds
        self.minimum_samples = minimum_samples
        self._clock = clock
        self._samples: dict[CalibrationKey, deque[_Sample]] = {}
        self._lock = threading.Lock()

    def observe(
        self,
        key: CalibrationKey,
        *,
        request_id: str,
        raw_estimate: int,
        provider_prompt_tokens: int,
    ) -> bool:
        if raw_estimate <= 0 or provider_prompt_tokens <= 0:
            return False
        now = self._clock()
        ratio = min(
            MAX_OBSERVED_RATIO,
            max(0.5, provider_prompt_tokens / raw_estimate),
        )
        with self._lock:
            samples = self._prune_locked(key, now)
            if any(sample.request_id == request_id for sample in samples):
                return False
            samples.append(_Sample(request_id, ratio, now))
            while len(samples) > self.max_samples:
                samples.popleft()
        return True

    def stats(self, key: CalibrationKey) -> CalibrationStats:
        with self._lock:
            samples = list(self._prune_locked(key, self._clock()))
        ratios = sorted(sample.ratio for sample in samples)
        if not ratios:
            return CalibrationStats()
        return CalibrationStats(
            sample_count=len(ratios),
            mature=len(ratios) >= self.minimum_samples,
            p95=_nearest_rank(ratios, 0.95),
            p99=_nearest_rank(ratios, 0.99),
        )

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def _prune_locked(self, key: CalibrationKey, now: float) -> deque[_Sample]:
        samples = self._samples.setdefault(key, deque())
        cutoff = now - self.ttl_seconds
        while samples and samples[0].observed_at < cutoff:
            samples.popleft()
        if not samples:
            self._samples.pop(key, None)
            samples = self._samples.setdefault(key, deque())
        return samples


GLOBAL_CALIBRATION_STORE = CalibrationStore()


def build_final_request_shape(completion_kwargs: Mapping[str, Any]) -> FinalRequestShape:
    semantic = {
        str(key): _normalize(value)
        for key, value in completion_kwargs.items()
        if key not in _TRANSPORT_KEYS
    }
    messages = semantic.get("messages")
    message_list = messages if isinstance(messages, list) else []
    message_text_parts: list[str] = []
    media_count = 0
    for message in message_list:
        message_text_parts.append(_extract_text(message))
        media_count += _count_media(message)
    framing = (3 * len(message_list) + (3 if message_list else 0))
    tools = semantic.get("tools") or semantic.get("functions")
    tool_tokens = (
        _json_tokens(tools) + TOOL_PROTOCOL_OVERHEAD_TOKENS
        if tools
        else 0
    )
    media_tokens = media_count * 256

    reasoning_values: dict[str, Any] = {}
    for key in _REASONING_KEYS:
        if key in semantic:
            reasoning_values[key] = semantic[key]
    extra_body = semantic.get("extra_body")
    if isinstance(extra_body, Mapping):
        for key, value in extra_body.items():
            if key in _REASONING_KEYS:
                reasoning_values[key] = value

    consumed = {
        "messages",
        "tools",
        "functions",
        *_NON_TOKEN_CONTROL_KEYS,
        *reasoning_values.keys(),
    }
    other = {
        key: value
        for key, value in semantic.items()
        if key not in consumed and key != "extra_body"
    }
    if isinstance(extra_body, Mapping):
        remaining_extra = {
            key: value for key, value in extra_body.items() if key not in _REASONING_KEYS
        }
        if remaining_extra:
            other["extra_body"] = remaining_extra

    has_tools = bool(tools)
    has_media = media_count > 0
    shape: RequestShape = (
        "tools_media" if has_tools and has_media else
        "tools" if has_tools else
        "media" if has_media else
        "text"
    )
    reasoning_mode = _fingerprint(reasoning_values)[:12] if reasoning_values else "default"
    components = RequestComponentCounts(
        message_text=estimate_tokens_text("".join(message_text_parts)) if message_text_parts else 0,
        message_framing=framing,
        tools=tool_tokens,
        media=media_tokens,
        reasoning=_json_tokens(reasoning_values) if reasoning_values else 0,
        other_semantic=_json_tokens(other) if other else 0,
    )
    return FinalRequestShape(
        fingerprint=_fingerprint(semantic),
        request_shape=shape,
        reasoning_mode=reasoning_mode,
        semantic_request=semantic,
        components=components,
    )


class FinalRequestMeter:
    def __init__(self, calibration_store: CalibrationStore = GLOBAL_CALIBRATION_STORE) -> None:
        self.calibration_store = calibration_store
        self._observed_anchor: Optional[_ObservedRequestAnchor] = None
        self._anchor_lock = threading.Lock()

    def clear_observed_anchor(self) -> None:
        with self._anchor_lock:
            self._observed_anchor = None

    def observe_request_input(
        self,
        preflight: FinalRequestPreflight,
        identity: FinalRequestIdentity,
        *,
        provider_prompt_tokens: int,
    ) -> None:
        if provider_prompt_tokens <= 0 or preflight.identity_fingerprint != identity.fingerprint:
            return
        with self._anchor_lock:
            self._observed_anchor = _ObservedRequestAnchor(
                identity_fingerprint=identity.fingerprint,
                stable_semantic_fingerprint=preflight.stable_semantic_fingerprint,
                context_stable_fingerprint=preflight.context_stable_fingerprint,
                message_fingerprints=preflight.message_fingerprints,
                input_tokens=provider_prompt_tokens,
            )

    def estimate_context_candidate(
        self, messages: Sequence[Any], tools: Sequence[Any]
    ) -> Optional[int]:
        message_fingerprints = tuple(_fingerprint(message) for message in messages)
        context_stable = _fingerprint({"tools": list(tools)})
        with self._anchor_lock:
            anchor = self._observed_anchor
        if anchor is None or anchor.context_stable_fingerprint != context_stable:
            return None
        if message_fingerprints[: len(anchor.message_fingerprints)] != anchor.message_fingerprints:
            return None
        delta = _estimate_message_delta(messages[len(anchor.message_fingerprints) :])
        return anchor.input_tokens + math.ceil(delta * DEFAULT_CORRECTION_MULTIPLIER)

    def _anchor_delta(
        self,
        *,
        identity: FinalRequestIdentity,
        stable_semantic_fingerprint: str,
        message_fingerprints: tuple[str, ...],
        messages: Sequence[Any],
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        with self._anchor_lock:
            anchor = self._observed_anchor
        if anchor is None:
            return None, None, None
        if anchor.identity_fingerprint != identity.fingerprint:
            return None, None, "anchor_identity_changed"
        if anchor.stable_semantic_fingerprint != stable_semantic_fingerprint:
            return None, None, "anchor_semantics_changed"
        if message_fingerprints[: len(anchor.message_fingerprints)] != anchor.message_fingerprints:
            return None, None, "anchor_non_append_only"
        delta = _estimate_message_delta(messages[len(anchor.message_fingerprints) :])
        return anchor.input_tokens, delta, None

    def measure(
        self,
        completion_kwargs: Mapping[str, Any],
        *,
        identity: FinalRequestIdentity,
        soft_budget: int,
        hard_budget: int,
        provider_count: Optional[int] = None,
        tokenizer_count: Optional[int] = None,
        fallback_reason: Optional[str] = None,
        retry_ordinal: int = 0,
        request_id: Optional[str] = None,
    ) -> FinalRequestPreflight:
        shape = build_final_request_shape(completion_kwargs)
        messages = list(shape.semantic_request.get("messages") or [])
        message_fingerprints = tuple(_fingerprint(message) for message in messages)
        stable_semantic_fingerprint = _fingerprint(
            {key: value for key, value in shape.semantic_request.items() if key != "messages"}
        )
        context_stable_fingerprint = _fingerprint(
            {"tools": shape.semantic_request.get("tools") or []}
        )
        raw = shape.components.raw_total
        key = CalibrationKey(
            endpoint_fingerprint=identity.endpoint_fingerprint,
            credential_scope_fingerprint=identity.credential_scope_fingerprint,
            canonical_model_id=identity.canonical_model_id,
            request_shape=shape.request_shape,
            reasoning_mode=shape.reasoning_mode,
        )
        stats = self.calibration_store.stats(key)
        anchor_input, estimated_delta, anchor_reason = self._anchor_delta(
            identity=identity,
            stable_semantic_fingerprint=stable_semantic_fingerprint,
            message_fingerprints=message_fingerprints,
            messages=messages,
        )
        if provider_count is not None:
            if provider_count <= 0:
                raise ValueError("provider_count must be positive")
            source: CountSource = "provider"
            soft_count = hard_count = provider_count
        elif anchor_input is not None and estimated_delta is not None:
            source = "provider_anchor_delta"
            soft_count = hard_count = anchor_input + math.ceil(
                estimated_delta * DEFAULT_CORRECTION_MULTIPLIER
            )
        else:
            base = tokenizer_count if tokenizer_count is not None else raw
            if base <= 0:
                raise ValueError("tokenizer_count must be positive")
            source = "tokenizer" if tokenizer_count is not None else "estimated"
            if stats.mature:
                soft_multiplier = _gate_multiplier(stats.p95)
                hard_multiplier = _gate_multiplier(stats.p99)
            else:
                soft_multiplier = hard_multiplier = DEFAULT_CORRECTION_MULTIPLIER
            soft_count = math.ceil(base * soft_multiplier)
            hard_count = math.ceil(base * hard_multiplier)
        preflight = FinalRequestPreflight(
            request_id=request_id or uuid.uuid4().hex,
            request_fingerprint=shape.fingerprint,
            identity_fingerprint=identity.fingerprint,
            request_shape=shape.request_shape,
            reasoning_mode=shape.reasoning_mode,
            count_source=source,
            components=shape.components,
            raw_estimate=raw,
            provider_count=provider_count,
            soft_count=soft_count,
            hard_count=hard_count,
            soft_budget=soft_budget,
            hard_budget=hard_budget,
            soft_exceeded=soft_count > soft_budget,
            hard_exceeded=hard_count > hard_budget,
            calibration_key_fingerprint=key.fingerprint,
            calibration_sample_count=stats.sample_count,
            calibration_p95=stats.p95,
            calibration_p99=stats.p99,
            fallback_reason=fallback_reason,
            stable_semantic_fingerprint=stable_semantic_fingerprint,
            context_stable_fingerprint=context_stable_fingerprint,
            message_fingerprints=message_fingerprints,
            anchor_input_tokens=anchor_input,
            estimated_delta_tokens=estimated_delta,
            anchor_invalidation_reason=anchor_reason,
            retry_ordinal=retry_ordinal,
        )
        if provider_count is not None:
            self.observe_request_input(
                preflight, identity, provider_prompt_tokens=provider_count
            )
        return preflight

    def observe_usage(
        self,
        preflight: FinalRequestPreflight,
        identity: FinalRequestIdentity,
        *,
        provider_prompt_tokens: int,
    ) -> bool:
        key = CalibrationKey(
            endpoint_fingerprint=identity.endpoint_fingerprint,
            credential_scope_fingerprint=identity.credential_scope_fingerprint,
            canonical_model_id=identity.canonical_model_id,
            request_shape=preflight.request_shape,
            reasoning_mode=preflight.reasoning_mode,
        )
        if key.fingerprint != preflight.calibration_key_fingerprint:
            raise StaleRequestBudgetIdentity("calibration identity changed")
        return self.calibration_store.observe(
            key,
            request_id=preflight.request_id,
            raw_estimate=preflight.raw_estimate,
            provider_prompt_tokens=provider_prompt_tokens,
        )


def _nearest_rank(values: Sequence[float], quantile: float) -> float:
    index = max(0, math.ceil(quantile * len(values)) - 1)
    return values[index]


def _gate_multiplier(value: Optional[float]) -> float:
    return min(MAX_GATE_MULTIPLIER, max(1.0, value or 1.0))


def _json_tokens(value: Any) -> int:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return estimate_tokens_text(encoded)


def _estimate_message_delta(messages: Sequence[Any]) -> int:
    if not messages:
        return 0
    return build_final_request_shape({"messages": list(messages)}).components.raw_total


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _normalize(value: Any, *, _depth: int = 0) -> Any:
    if _depth >= 32:
        return {"__max_depth__": type(value).__name__}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item, _depth=_depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item, _depth=_depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        return _normalize(value.model_dump(mode="json"), _depth=_depth + 1)
    return str(value)


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        if str(value.get("type", "")).lower() in _MEDIA_TYPES:
            return ""
        return "".join(
            _extract_text(item)
            for key, item in value.items()
            if key not in {"image_url", "url", "data", "audio", "file"}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "".join(_extract_text(item) for item in value)
    return ""


def _count_media(value: Any) -> int:
    if isinstance(value, Mapping):
        own = 1 if str(value.get("type", "")).lower() in _MEDIA_TYPES else 0
        return own + sum(
            _count_media(item)
            for key, item in value.items()
            if key not in {"image_url", "url", "data", "audio", "file"}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_count_media(item) for item in value)
    return 0
