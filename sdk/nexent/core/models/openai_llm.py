from ...monitor import get_monitoring_manager
from ...monitor.monitoring import (
    _MonitoredClient,
    _monitoring_operation,
    _monitoring_display_name,
    _detect_model_type,
    OPENINFERENCE_INPUT_VALUE,
)
from ..utils.token_estimation import estimate_tokens_text
import logging
import threading
import asyncio
import time
import json
import re
from typing import Callable, List, Optional, Dict, Any

from smolagents import Tool
from smolagents.models import OpenAIServerModel, ChatMessage, MessageRole

from .capacity_budget import (
    CallerMaxTokensOverrideForbidden,
    SafeInputBudgetCapacityMismatch,
    SafeInputBudgetFingerprintMismatch,
    SafeInputBudgetSnapshot,
    compute_w2_fingerprint,
)
from .capacity_resolver import derive_output_protection_tokens
from .feature_capability import (
    apply_reasoning_request_policy,
    resolve_effective_feature_policy,
)
from ..utils.observer import MessageObserver, ProcessType
from .prompt_cache import (
    apply_cache_directives,
    cache_directive_advice,
    extract_prompt_cache_usage,
    resolve_prompt_cache_profile,
)
from .message_utils import (
    content_has_multimodal_blocks,
    prepare_messages_for_smolagents_text_flattening,
)
from .retry import DEFAULT_MODEL_RETRY, ModelRetryConfig, classify_model_error
from .final_request_budget import (
    FinalRequestIdentity,
    FinalRequestMeter,
    FinalRequestPreflight,
    FinalRequestSoftBudgetExceeded,
    CompactionNoReduction,
    ContextRebuildOverBudget,
    ProviderContextOverflowRetryExhausted,
    ProviderContextOverflowRetryUnsafe,
    RequestSideEffectGuard,
    build_final_request_shape,
    is_provider_context_overflow,
)
from .provider_request_count import count_final_request, endpoint_fingerprint
from .provider_usage import (
    ProviderCallUsage,
    normalize_provider_usage,
    resolve_provider_usage_profile,
)
from .tokenizer_registry import resolve as resolve_tokenizer

logger = logging.getLogger("openai_llm")

STOP_EVENT_INTERRUPTED_MESSAGE = "Model is interrupted by stop event"


def _token_usage(*, input_tokens: int, output_tokens: int) -> Any:
    """Create TokenUsage without making lightweight model imports load monitoring."""
    from smolagents.monitoring import TokenUsage

    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)


class EmptyModelResponseError(RuntimeError):
    """Raised when a completed provider stream contains no user-visible content."""


class IncompleteToolCallError(RuntimeError):
    """Raised when a length stop leaves tool-call arguments incomplete."""


def _merge_continuation_text(existing: str, continuation: str) -> tuple[str, bool]:
    """Join an automatic continuation while removing a repeated boundary prefix."""
    if not continuation.strip():
        return existing, False
    max_overlap = min(len(existing), len(continuation), 2048)
    for overlap in range(max_overlap, 0, -1):
        if existing[-overlap:] == continuation[:overlap]:
            continuation = continuation[overlap:]
            break
    if not continuation.strip():
        return existing, False
    return existing + continuation, True


class OpenAIModel(OpenAIServerModel):
    # Public SDK constructor: keep common kwargs explicit and read extension
    # kwargs below to preserve backward-compatible keyword call sites.
    def __init__(self, observer: MessageObserver = MessageObserver, temperature=0.2, top_p=0.95,
                 ssl_verify=True, model_factory: Optional[str] = None,
                 display_name: Optional[str] = None,
                 extra_body: Optional[Dict[str, Any]] = None,
                 max_output_tokens: Optional[int] = None,
                 max_tokens: Optional[int] = None,
                 flatten_messages_as_text: Optional[bool] = None,
                 safe_input_budget_snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]] = None,
                 timeout_seconds: Optional[float] = None,
                 retry_config: Optional[ModelRetryConfig] = None,
                 *args, **kwargs):
        """
        Initialize OpenAI Model with observer and SSL verification option.

        Args:
            observer: MessageObserver instance for tracking model output
            temperature: Sampling temperature (default: 0.2)
            top_p: Top-p sampling parameter (default: 0.95)
            ssl_verify: Whether to verify SSL certificates (default: True).
                       Set to False for local services without SSL support.
            timeout_seconds: Timeout in seconds for HTTP requests (default: None, uses client default).
            model_factory: Provider identifier (e.g., openai, modelengine)
            display_name: Human-readable display name for monitoring
            extra_body: Optional dict merged into every chat.completions.create
                       request body. Defaults to None so production behaviour
                       is unchanged for callers that do not opt in.
            max_output_tokens: Per-call completion output cap. Preferred name
                       per W1 ADR. Defaults to None so production keeps the
                       provider default (unbounded / model max). Benchmarks set
                       this explicitly (e.g. 4096) to bound degenerate generation
                       loops on long contexts.
            max_tokens: DEPRECATED alias for max_output_tokens retained during
                       the W1 migration. If max_output_tokens is supplied it
                       wins; otherwise max_tokens is copied into it.
            flatten_messages_as_text: Override message flattening for this
                       model instance. Defaults to ModelEngine text-model
                       behavior; multimodal adapters must pass False to retain
                       typed media blocks.
            capacity_snapshot: Optional model capacity snapshot accepted via
                       kwargs for backward-compatible keyword call sites.
            prompt_cache: Selected prompt-cache capability profile accepted via
                       kwargs. Unknown or absent capability disables provider
                       cache directives.
            *args: Additional positional arguments for OpenAIServerModel
            **kwargs: Additional keyword arguments for OpenAIServerModel
        """
        capacity_snapshot: Optional[Dict[str, Any]] = kwargs.pop("capacity_snapshot", None)
        prompt_cache: Optional[Dict[str, Any]] = kwargs.pop("prompt_cache", None)
        self.feature_capabilities: Optional[Dict[str, Any]] = kwargs.pop(
            "feature_capabilities", None
        )
        self.feature_preferences: Optional[Dict[str, Any]] = kwargs.pop(
            "feature_preferences", None
        )
        self.provider_usage_profile: Optional[Dict[str, Any]] = kwargs.pop(
            "provider_usage_profile", None
        )
        self.canonical_model_id = kwargs.pop("canonical_model_id", None)
        self.model_identity_metadata = kwargs.pop("model_identity_metadata", None)
        self.tokenizer_match_metadata = kwargs.pop("tokenizer_match_metadata", None)
        self.tokenizer_family = kwargs.pop("tokenizer_family", None)
        self.token_count_probe_metadata = kwargs.pop("token_count_probe_metadata", None)
        self._token_count_api_base = str(kwargs.get("api_base") or "")
        self._token_count_api_key = str(kwargs.get("api_key") or "")
        self._token_count_ssl_verify = bool(ssl_verify)

        self.observer = observer
        self.temperature = temperature
        self.top_p = top_p
        self.stop_event = threading.Event()
        self._monitoring = get_monitoring_manager()
        self.model_factory = (model_factory or "").lower()
        self.provider_usage_profile = self.provider_usage_profile or resolve_provider_usage_profile(
            self.model_factory,
            getattr(self, "capability_profile_version", None),
        )
        self.flatten_messages_as_text = flatten_messages_as_text
        self.display_name = display_name
        self.extra_body = extra_body or None
        self.prompt_cache = prompt_cache or None
        self.last_provider_cache_advice = None
        self.last_prompt_cache_usage = None
        self.last_cached_input_token_count = 0
        self.last_response_diagnostics = None
        self.last_effective_feature_policy = None
        self.provider_call_usages: list[ProviderCallUsage] = []
        self.turn_provider_call_usages: list[ProviderCallUsage] = []
        self._provider_usage_turn_id: Optional[str] = None
        self.last_provider_call_usage: Optional[ProviderCallUsage] = None
        self.last_final_request_preflight: Optional[FinalRequestPreflight] = None
        self.last_recovery_state = "not_needed"
        self.context_budget_step_number = 0
        self._final_request_meter = FinalRequestMeter()
        self.safe_input_budget_snapshot = safe_input_budget_snapshot
        self.capacity_snapshot = capacity_snapshot
        if max_output_tokens is None and max_tokens is not None:
            logger.debug(
                "OpenAIModel received legacy max_tokens=%s; treating as max_output_tokens. "
                "Update callers to pass max_output_tokens directly.",
                max_tokens,
            )
            max_output_tokens = max_tokens
        self.max_output_tokens = max_output_tokens
        # Legacy alias kept readable for any caller still reading .max_tokens.
        self.max_tokens = max_output_tokens
        self.retry_config = retry_config or DEFAULT_MODEL_RETRY
        self.last_retry_count = 0

        # Create http_client based on ssl_verify parameter and timeout
        if not ssl_verify or timeout_seconds is not None:
            from openai import DefaultHttpxClient
            client_config = {"verify": ssl_verify}
            if timeout_seconds is not None:
                client_config["timeout"] = timeout_seconds
            http_client = DefaultHttpxClient(**client_config)
            client_kwargs = kwargs.get('client_kwargs', {})
            client_kwargs['http_client'] = http_client
            kwargs['client_kwargs'] = client_kwargs

        super().__init__(*args, **kwargs)

        # Wrap the OpenAI client with monitoring interceptor
        model_type = _detect_model_type(self)
        model_id = getattr(self, "model_id", None)
        base_client = getattr(self, "client", None)
        if base_client is not None and model_id is not None:
            self.client = _MonitoredClient(base_client, model_id, model_type)
        else:
            logger.warning(
                "OpenAIModel: no `client` attribute after init; "
                "skipping monitored wrapper (model_id=%s, type=%s)",
                model_id,
                model_type,
            )
        if self.display_name:
            _monitoring_display_name.set(self.display_name)

    def __call__(self, messages: List[Dict[str, Any]], stop_sequences: Optional[List[str]] = None,
                 response_format: dict[str, str] | None = None, tools_to_call_from: Optional[List[Tool]] = None,
                 _token_tracker=None, safe_input_budget_snapshot: Optional[SafeInputBudgetSnapshot] = None,
                 context_rebuild: Optional[Callable[[int], Any]] = None,
                 _budget_retry_ordinal: int = 0,
                 _soft_rebuild_attempted: bool = False,
                 _previous_preflight: Optional[FinalRequestPreflight] = None,
                 _side_effect_guard: Optional[RequestSideEffectGuard] = None,
                 _recovery_original_hard_count: Optional[int] = None,
                 _provider_safe_limit: Optional[int] = None,
                 _length_continuation_ordinal: int = 0,
                 _transport_retry_ordinal: int = 0,
                 usage_purpose: str = "main_agent",
                 usage_turn_id: Optional[str] = None,
                 **kwargs, ) -> ChatMessage:
        _monitoring_operation.set("chat_completion")
        side_effect_guard = _side_effect_guard or RequestSideEffectGuard()

        if _token_tracker is None:
            effective_turn_id = usage_turn_id or getattr(
                self, "default_usage_turn_id", None
            )
            self.provider_call_usages = []
            self.last_provider_call_usage = None
            self._active_usage_purpose = usage_purpose
            self._active_usage_turn_id = effective_turn_id
            if effective_turn_id != self._provider_usage_turn_id:
                self.turn_provider_call_usages = []
                self._final_request_meter.clear_observed_anchor()
                self._provider_usage_turn_id = effective_turn_id
            trusted_budget_snapshot = (
                safe_input_budget_snapshot or self.safe_input_budget_snapshot
                or (self._provisional_budget_snapshot() if context_rebuild is not None else None)
            )
            invocation_parameters = {
                "temperature": self.temperature,
                "top_p": self.top_p,
                **{k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool))},
            }
            trace_attributes = {
                "llm.invocation_parameters": json.dumps(invocation_parameters, ensure_ascii=False),
                "model_id": self.model_id,
            }
            input_attr_key = (
                OPENINFERENCE_INPUT_VALUE
                if isinstance(OPENINFERENCE_INPUT_VALUE, str)
                else "input.value"
            )
            trace_attributes[input_attr_key] = messages or []
            trace_attributes.update(
                self._safe_input_budget_trace_attributes(trusted_budget_snapshot)
            )

            with self._monitoring.trace_llm_request(
                f"{self.display_name or self.model_id}.generate",
                self.model_id,
                **trace_attributes,
            ) as span:
                token_tracker = self._monitoring.create_token_tracker(
                    self.model_id, span)
                return self.__call__(
                    messages=messages,
                    stop_sequences=stop_sequences,
                    response_format=response_format,
                    tools_to_call_from=tools_to_call_from,
                    _token_tracker=token_tracker,
                    safe_input_budget_snapshot=safe_input_budget_snapshot,
                    context_rebuild=context_rebuild,
                    _budget_retry_ordinal=_budget_retry_ordinal,
                    _soft_rebuild_attempted=_soft_rebuild_attempted,
                    _previous_preflight=_previous_preflight,
                    _side_effect_guard=side_effect_guard,
                    _recovery_original_hard_count=_recovery_original_hard_count,
                    _provider_safe_limit=_provider_safe_limit,
                    _length_continuation_ordinal=_length_continuation_ordinal,
                    _transport_retry_ordinal=_transport_retry_ordinal,
                    usage_purpose=usage_purpose,
                    usage_turn_id=usage_turn_id,
                    **kwargs,
                )

        token_tracker = _token_tracker or self._monitoring.create_token_tracker(
            self.model_id)
        if _transport_retry_ordinal == 0:
            self.last_retry_count = 0
        if self.stop_event.is_set():
            if token_tracker:
                self._monitoring.add_span_event(
                    "model_stopped", {"reason": "stop_event_set"}
                )
            raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)

        def retry_transport_error(error: BaseException) -> ChatMessage:
            is_empty_stop = (
                isinstance(error, EmptyModelResponseError)
                and self.last_finish_reason in (None, "stop")
            )
            max_attempts = (
                min(self.retry_config.max_attempts, 2)
                if is_empty_stop
                else self.retry_config.max_attempts
            )
            retryable = is_empty_stop or classify_model_error(error) == "retryable"
            if (
                not retryable
                or not side_effect_guard.recovery_safe
                or _transport_retry_ordinal + 1 >= max_attempts
            ):
                raise error

            next_ordinal = _transport_retry_ordinal + 1
            backoff = self.retry_config.calculate_backoff(next_ordinal)
            logger.warning(
                "event=model_retry attempt=%d/%d error_type=%s retrying_after_seconds=%.2f",
                next_ordinal,
                max_attempts,
                type(error).__name__,
                backoff,
            )
            self.last_retry_count = next_ordinal
            if self.stop_event.is_set():
                raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)
            self.stop_event.wait(backoff)
            if self.stop_event.is_set():
                raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)
            return self.__call__(
                messages=messages,
                stop_sequences=stop_sequences,
                response_format=response_format,
                tools_to_call_from=tools_to_call_from,
                _token_tracker=token_tracker,
                safe_input_budget_snapshot=safe_input_budget_snapshot,
                context_rebuild=context_rebuild,
                _budget_retry_ordinal=_budget_retry_ordinal,
                _soft_rebuild_attempted=_soft_rebuild_attempted,
                _previous_preflight=_previous_preflight,
                _side_effect_guard=side_effect_guard,
                _recovery_original_hard_count=_recovery_original_hard_count,
                _provider_safe_limit=_provider_safe_limit,
                _length_continuation_ordinal=_length_continuation_ordinal,
                _transport_retry_ordinal=next_ordinal,
                usage_purpose=usage_purpose,
                usage_turn_id=usage_turn_id,
                **kwargs,
            )
        trusted_budget_snapshot = (
            safe_input_budget_snapshot or self.safe_input_budget_snapshot
            or (self._provisional_budget_snapshot() if context_rebuild is not None else None)
        )
        self._using_provisional_capacity = bool(
            trusted_budget_snapshot
            and "provisional_32768_capacity" in getattr(trusted_budget_snapshot, "warnings", ())
        )
        self.last_response_diagnostics = None

        # Normalize incoming messages so we can accept plain dict payloads like
        # {"role": "user", "content": "..."} alongside ChatMessage instances.
        normalized_messages: List[ChatMessage] = []
        for msg in messages or []:
            if isinstance(msg, ChatMessage):
                normalized_messages.append(msg)
            elif isinstance(msg, dict):
                if "role" not in msg or "content" not in msg:
                    raise ValueError(
                        "Each message dict must include 'role' and 'content'.")
                normalized_messages.append(ChatMessage.from_dict({
                    "role": msg["role"],
                    "content": msg["content"],
                    "tool_calls": msg.get("tool_calls"),
                }))
            else:
                raise TypeError(
                    "Messages must be ChatMessage or dict objects.")

        # Add completion started event and model parameters
        if token_tracker:
            self._monitoring.add_span_event("completion_started")
            self._monitoring.set_span_attributes(
                model_id=self.model_id,
                temperature=self.temperature,
                top_p=self.top_p,
                message_count=len(
                    normalized_messages) if normalized_messages else 0,
                **{f"llm.param.{k}": v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool))}
            )

        has_media = any(
            content_has_multimodal_blocks(getattr(message, "content", None))
            for message in normalized_messages
        )
        flatten_messages_as_text = (
            self.model_factory == "modelengine" and not has_media
            if self.flatten_messages_as_text is None
            else self.flatten_messages_as_text
        )
        messages_for_completion = (
            prepare_messages_for_smolagents_text_flattening(normalized_messages)
            if flatten_messages_as_text
            else normalized_messages
        )

        completion_kwargs = self._prepare_completion_kwargs(
            messages=messages_for_completion, stop_sequences=stop_sequences,
            response_format=response_format, tools_to_call_from=tools_to_call_from, model=self.model_id,
            custom_role_conversions=self.custom_role_conversions, convert_images_to_image_urls=True,
            temperature=self.temperature, top_p=self.top_p,
            flatten_messages_as_text=flatten_messages_as_text, **kwargs,
        )

        completion_kwargs["stream_options"] = {"include_usage": True}

        if self.extra_body:
            completion_kwargs["extra_body"] = dict(self.extra_body)
        runtime_feature_capabilities = dict(self.feature_capabilities or {})
        runtime_cache_capability = runtime_feature_capabilities.get("prompt_cache")
        runtime_cache_capability = (
            dict(runtime_cache_capability)
            if isinstance(runtime_cache_capability, dict)
            else {}
        )
        if runtime_cache_capability.get("supported") is None and self.prompt_cache:
            cache_mode = str(self.prompt_cache.get("mode") or "unknown")
            runtime_cache_capability = {
                "supported": bool(
                    self.prompt_cache.get(
                        "enabled",
                        cache_mode not in {"unknown", "none", "disabled", ""},
                    )
                ),
                "mode": cache_mode,
                "metrics_available": self.prompt_cache.get("metrics_available"),
            }
            runtime_feature_capabilities["prompt_cache"] = runtime_cache_capability
        effective_feature_policy = resolve_effective_feature_policy(
            runtime_feature_capabilities,
            self.feature_preferences,
        )
        self.last_effective_feature_policy = effective_feature_policy
        completion_kwargs = apply_reasoning_request_policy(
            completion_kwargs,
            effective_feature_policy,
        )

        trusted_budget_snapshot = (
            safe_input_budget_snapshot or self.safe_input_budget_snapshot
            or (self._provisional_budget_snapshot() if context_rebuild is not None else None)
        )
        if trusted_budget_snapshot is None:
            self.last_final_request_preflight = None

        # Bound completion length unless the caller passed their own override
        # via kwargs (which already landed in completion_kwargs above).
        # OpenAI wire field stays max_tokens; internal name is max_output_tokens.
        # When a W2 snapshot is active, its requested_output_tokens is the sole
        # authority per CM-030 — skip the pre-W2 auto-fill so the dispatch
        # boundary does not see max_output_tokens masquerading as a caller
        # override and reject it via CallerMaxTokensOverrideForbidden.
        if (
            self.max_output_tokens is not None
            and "max_tokens" not in completion_kwargs
            and trusted_budget_snapshot is None
        ):
            completion_kwargs["max_tokens"] = self.max_output_tokens

        cache_enabled = effective_feature_policy["prompt_cache"]["enabled"] is True
        selected_cache_profile = resolve_prompt_cache_profile(
            self.model_factory or "unknown", self.prompt_cache
        ) if cache_enabled else None
        # Provider protocol decisions depend only on the approved provider/model
        # capability profile.  Context partitioning and ordering are owned by
        # ContextManager and are intentionally opaque to this adapter.
        cache_advice = cache_directive_advice(selected_cache_profile)
        self.last_provider_cache_advice = cache_advice
        dispatch_kwargs = apply_cache_directives(
            completion_kwargs, cache_advice
        )
        # The __call__ boundary owns streaming: dispatch below always streams
        # and assembles the result. Drop a stale construction-time ``stream``
        # so it cannot collide with the explicit ``stream=True`` at dispatch.
        dispatch_kwargs.pop("stream", None)
        feature_profile = self.feature_capabilities or {}
        reasoning_profile = feature_profile.get("reasoning") or {}
        cache_profile = feature_profile.get("prompt_cache") or {}
        resolved_reasoning_support = reasoning_profile.get("supported")
        self._monitoring.set_span_attributes(
            **{
                "llm.feature.source": str(feature_profile.get("source") or "unknown"),
                "llm.feature.match_kind": str(
                    feature_profile.get("match_kind") or "unknown"
                ),
                "llm.feature.catalog_revision": str(
                    feature_profile.get("catalog_revision") or ""
                ),
                "llm.feature.profile_version": str(
                    feature_profile.get("profile_version") or ""
                ),
                "llm.reasoning.supported": (
                    resolved_reasoning_support
                    if isinstance(resolved_reasoning_support, bool)
                    else "unknown"
                ),
                "llm.reasoning.mode": str(
                    reasoning_profile.get("mode") or "unknown"
                ),
                "llm.reasoning.request_style": str(
                    reasoning_profile.get("request_style") or "unknown"
                ),
                "llm.reasoning.effective_enabled": bool(
                    effective_feature_policy["reasoning"]["enabled"]
                ),
                "llm.reasoning.effective_effort": str(
                    effective_feature_policy["reasoning"].get("effort") or ""
                ),
                "llm.feature.policy_source": str(
                    effective_feature_policy.get("source") or "nexent_default"
                ),
                "llm.prompt_cache.mode": cache_advice.mode,
                "llm.prompt_cache.supported": cache_advice.supported,
                "llm.prompt_cache.directive_reason": cache_advice.reason,
                "llm.prompt_cache.profile_supported": (
                    cache_profile.get("supported")
                    if isinstance(cache_profile.get("supported"), bool)
                    else "unknown"
                ),
            }
        )
        context_evidence = getattr(self, "last_context_evidence", None)
        if context_evidence is not None:
            self._monitoring.set_span_attributes(
                **{
                    "llm.prompt_cache.stable_prefix_fingerprint": getattr(
                        context_evidence, "stable_prefix_fingerprint", None
                    ) or "",
                    "llm.prompt_cache.prefix_change_reasons": json.dumps(
                        list(getattr(context_evidence, "prefix_change_reasons", ())),
                        ensure_ascii=False,
                    ),
                    "llm.prompt_cache.stable_message_count": getattr(
                        context_evidence, "stable_message_count", 0,
                    ),
                    "llm.prompt_cache.dynamic_message_count": getattr(
                        context_evidence, "dynamic_message_count", 0,
                    ),
                }
            )

        try:
            current_request = self._dispatch_chat_completion(
                safe_input_budget_snapshot=trusted_budget_snapshot,
                capacity_snapshot=(
                    None
                    if "provisional_32768_capacity" in getattr(trusted_budget_snapshot, "warnings", ())
                    else self.capacity_snapshot
                ),
                retry_ordinal=_budget_retry_ordinal,
                request_rebuild_available=context_rebuild is not None,
                soft_rebuild_attempted=_soft_rebuild_attempted,
                previous_preflight=_previous_preflight,
                usage_purpose=usage_purpose,
                usage_turn_id=usage_turn_id,
                stream=True,
                **dispatch_kwargs,
            )
            provider_call_record = self.last_provider_call_usage
        except FinalRequestSoftBudgetExceeded as soft_error:
            return self._rebuild_and_retry(
                soft_error.preflight,
                context_rebuild=context_rebuild,
                token_tracker=token_tracker,
                stop_sequences=stop_sequences,
                response_format=response_format,
                tools_to_call_from=tools_to_call_from,
                trusted_budget_snapshot=trusted_budget_snapshot,
                retry_ordinal=_budget_retry_ordinal,
                soft_rebuild_attempted=True,
                call_kwargs=kwargs,
                recovery_original_hard_count=_recovery_original_hard_count,
                provider_safe_limit=_provider_safe_limit,
            )
        except Exception as error:
            if not is_provider_context_overflow(error):
                return retry_transport_error(error)
            if trusted_budget_snapshot is None:
                raise
            return self._recover_provider_overflow(
                error,
                preflight=self.last_final_request_preflight,
                context_rebuild=context_rebuild,
                token_tracker=token_tracker,
                stop_sequences=stop_sequences,
                response_format=response_format,
                tools_to_call_from=tools_to_call_from,
                trusted_budget_snapshot=trusted_budget_snapshot,
                retry_ordinal=_budget_retry_ordinal,
                call_kwargs=kwargs,
                recovery_original_hard_count=_recovery_original_hard_count,
                provider_safe_limit=_provider_safe_limit,
            )

        # Validate response type: ensure we got a proper iterator, not error strings or dicts
        # Some APIs return error strings like "error: rate limit" or JSON dicts on failure
        if isinstance(current_request, str):
            raise ValueError(f"LLM API returned error string: {current_request}")
        if isinstance(current_request, dict):
            error_msg = current_request.get("error") or current_request.get("message") or str(current_request)
            raise ValueError(f"LLM API returned error: {error_msg}")

        chunk_list = []
        token_join = []
        role = None
        finish_reason = None
        self.last_finish_reason = None
        content_chunk_count = 0
        reasoning_chunk_count = 0
        reasoning_char_count = 0
        empty_choices_chunk_count = 0
        nonstandard_chunk_count = 0
        tool_call_chunk_count = 0
        tool_call_fragments: Dict[int, Dict[str, Any]] = {}

        # Reset output mode
        self.observer.current_mode = ProcessType.MODEL_OUTPUT_THINKING

        # Track streaming metrics
        stream_start_time = time.time()
        first_token_received = False

        try:
            for chunk in current_request:
                # Safety check: skip non-standard chunks that lack expected attributes
                # This handles edge cases where API returns error responses as chunks
                if not hasattr(chunk, 'choices'):
                    # Log warning and continue processing
                    if hasattr(chunk, '__str__'):
                        chunk_str = str(chunk)
                        logger.warning(f"Received non-standard chunk (no 'choices'): {chunk_str[:200]}")
                    chunk_list.append(chunk)
                    nonstandard_chunk_count += 1
                    continue

                if not chunk.choices:
                    chunk_list.append(chunk)
                    empty_choices_chunk_count += 1
                    continue

                chunk_finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                if chunk_finish_reason is not None:
                    finish_reason = str(chunk_finish_reason)

                delta = chunk.choices[0].delta
                delta_role = getattr(delta, "role", None)
                if delta_role is not None:
                    role = delta_role
                new_token = delta.content
                reasoning_content = getattr(
                    delta, 'reasoning_content', None)
                delta_tool_calls = getattr(delta, "tool_calls", None) or []
                # OpenAI emits a concrete sequence. Treat dynamic proxy values
                # (including permissive mocks) as absent instead of inventing a
                # tool side effect that would incorrectly disable safe retries.
                if not isinstance(delta_tool_calls, (list, tuple)):
                    delta_tool_calls = []
                if delta_tool_calls:
                    side_effect_guard.mark("tool_effect")
                for position, tool_call in enumerate(delta_tool_calls):
                    index = getattr(tool_call, "index", position)
                    if not isinstance(index, int):
                        index = position
                    fragment = tool_call_fragments.setdefault(
                        index,
                        {"id": "", "type": "function", "name": "", "arguments": ""},
                    )
                    call_id = getattr(tool_call, "id", None)
                    call_type = getattr(tool_call, "type", None)
                    function = getattr(tool_call, "function", None)
                    if call_id:
                        fragment["id"] += str(call_id)
                    if call_type:
                        fragment["type"] = str(call_type)
                    if function is not None:
                        name = getattr(function, "name", None)
                        arguments = getattr(function, "arguments", None)
                        if name:
                            fragment["name"] += str(name)
                        if arguments:
                            fragment["arguments"] += str(arguments)
                    tool_call_chunk_count += 1

                # Handle reasoning_content if it exists and is not null
                if reasoning_content is not None:
                    reasoning_chunk_count += 1
                    reasoning_char_count += len(str(reasoning_content))
                    self.observer.add_model_reasoning_content(
                        reasoning_content)
                    if token_tracker and not first_token_received:
                        token_tracker.record_first_token()
                        first_token_received = True
                        if provider_call_record is not None:
                            provider_call_record._first_token_at = time.time()

                if new_token is not None:
                    if str(new_token):
                        side_effect_guard.mark("response_started")
                    content_chunk_count += 1
                    # Record first token timing
                    if token_tracker and not first_token_received:
                        token_tracker.record_first_token()
                        first_token_received = True
                        if provider_call_record is not None:
                            provider_call_record._first_token_at = time.time()

                    # Track each token
                    if token_tracker:
                        token_tracker.record_token(new_token)

                    self.observer.add_model_new_token(new_token)
                    token_join.append(new_token)

                chunk_list.append(chunk)
                if self.stop_event.is_set():
                    if token_tracker:
                        self._monitoring.add_span_event("model_stopped", {
                            "reason": "stop_event_set"})
                    raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)

            # Send end marker
            self.observer.flush_remaining_tokens()
            model_output = "".join(token_join)
            tool_calls = [
                {
                    "id": fragment["id"] or f"tool_call_{index}",
                    "type": fragment["type"],
                    "function": {
                        "name": fragment["name"],
                        "arguments": fragment["arguments"],
                    },
                }
                for index, fragment in sorted(tool_call_fragments.items())
            ]
            self.last_finish_reason = finish_reason
            if finish_reason == "length":
                logger.warning(
                    "Model output reached the configured completion token limit; "
                    "the answer is incomplete"
                )
                self._monitoring.add_span_event("completion_truncated", {
                    "finish_reason": finish_reason,
                })

            # Extract token usage
            input_tokens = 0
            output_tokens = 0
            usage = None
            if chunk_list and chunk_list[-1].usage is not None:
                usage = chunk_list[-1].usage
                input_tokens = usage.prompt_tokens
                output_tokens = usage.completion_tokens if hasattr(
                    usage, 'completion_tokens') else usage.total_tokens
                self.last_input_token_count = input_tokens
                self.last_output_token_count = output_tokens
            else:
                input_text = ""
                for msg in normalized_messages:
                    if hasattr(msg, 'content'):
                        content = msg.content
                        if isinstance(content, str):
                            input_text += content
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    input_text += part.get("text", "")
                input_tokens = estimate_tokens_text(input_text)
                output_tokens = estimate_tokens_text(model_output)
                self.last_input_token_count = input_tokens
                self.last_output_token_count = output_tokens
                logger.debug(
                    f"Token usage not returned by API, using estimation: "
                    f"input_tokens={input_tokens}, output_tokens={output_tokens}"
                )

            self._finalize_provider_call_usage(
                provider_call_record,
                raw_usage=usage,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                status="completed",
                finish_reason=finish_reason,
                first_token_received=first_token_received,
            )

            if (
                usage is not None
                and trusted_budget_snapshot is not None
                and self.last_final_request_preflight is not None
            ):
                calibration_added = self._final_request_meter.observe_usage(
                    self.last_final_request_preflight,
                    self._build_final_request_identity(trusted_budget_snapshot),
                    provider_prompt_tokens=input_tokens,
                )
                self._final_request_meter.observe_request_input(
                    self.last_final_request_preflight,
                    self._build_final_request_identity(trusted_budget_snapshot),
                    provider_prompt_tokens=input_tokens,
                )
                self._monitoring.set_span_attributes(
                    **{
                        "context.final_request.calibration_observed": calibration_added,
                        "context.final_request.provider_prompt_tokens": input_tokens,
                    }
                )

            cache_usage = extract_prompt_cache_usage(
                usage, input_tokens, capability_profile=selected_cache_profile
            )
            self.last_prompt_cache_usage = cache_usage
            self.last_cached_input_token_count = cache_usage.cached_input_tokens
            self._monitoring.set_span_attributes(
                **{
                    "llm.prompt_cache.cached_input_tokens": cache_usage.cached_input_tokens,
                    "llm.prompt_cache.uncached_input_tokens": cache_usage.uncached_input_tokens,
                    "llm.prompt_cache.provider_cache_hit": cache_usage.provider_cache_hit,
                    "llm.prompt_cache.hit_ratio": cache_usage.hit_ratio,
                    "llm.prompt_cache.metrics_source": cache_usage.metrics_source,
                    "llm.prompt_cache.estimated_saved_input_tokens": cache_usage.estimated_saved_input_tokens,
                    "llm.prompt_cache.estimated_input_savings_ratio": cache_usage.estimated_input_savings_ratio,
                }
            )

            # Record completion metrics
            if token_tracker:
                token_tracker.record_completion(
                    input_tokens, output_tokens)

            response_diagnostics = {
                "finish_reason": finish_reason,
                "chunk_count": len(chunk_list),
                "content_chunk_count": content_chunk_count,
                "content_char_count": len(model_output),
                "reasoning_chunk_count": reasoning_chunk_count,
                "reasoning_char_count": reasoning_char_count,
                "empty_choices_chunk_count": empty_choices_chunk_count,
                "nonstandard_chunk_count": nonstandard_chunk_count,
                "tool_call_chunk_count": tool_call_chunk_count,
                "tool_call_count": len(tool_calls),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            self.last_response_diagnostics = response_diagnostics
            self._monitoring.set_span_attributes(
                **{f"llm.response.{key}": value for key, value in response_diagnostics.items()}
            )

            if token_tracker:
                total_duration = time.time() - stream_start_time
                self._monitoring.set_openinference_output(model_output)
                self._monitoring.add_span_event("completion_finished", {
                    "total_duration": total_duration,
                    "output_length": len(model_output),
                    "chunk_count": len(chunk_list)
                })

            if not model_output.strip() and not tool_calls:
                logger.warning(
                    "event=empty_model_response model_id=%s provider=%s "
                    "finish_reason=%s chunk_count=%d content_chunk_count=%d "
                    "reasoning_chunk_count=%d reasoning_char_count=%d "
                    "empty_choices_chunk_count=%d nonstandard_chunk_count=%d "
                    "input_tokens=%d output_tokens=%d",
                    self.model_id,
                    self.model_factory or "unknown",
                    finish_reason,
                    len(chunk_list),
                    content_chunk_count,
                    reasoning_chunk_count,
                    reasoning_char_count,
                    empty_choices_chunk_count,
                    nonstandard_chunk_count,
                    input_tokens,
                    output_tokens,
                )
                self._monitoring.add_span_event("empty_model_response", response_diagnostics)
                raise EmptyModelResponseError(
                    "Model stream completed without user-visible content "
                    f"(finish_reason={finish_reason}, reasoning_chunks={reasoning_chunk_count}, "
                    f"output_tokens={output_tokens})"
                )

            message = ChatMessage.from_dict({
                "role": role if role else "assistant",
                "content": model_output or None,
                "tool_calls": tool_calls or None,
            })

            if input_tokens > 0 or output_tokens > 0:
                message.token_usage = _token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens
                )
            message.raw = current_request
            message.provider_call_usages = tuple(self.provider_call_usages)
            message.role = MessageRole.ASSISTANT

            if finish_reason == "length":
                if tool_calls:
                    self._monitoring.add_span_event(
                        "length_continuation_blocked",
                        {"reason": "incomplete_tool_call"},
                    )
                    raise IncompleteToolCallError(
                        "model output limit interrupted a tool call; the partial call was not executed"
                    )
                if _length_continuation_ordinal < 2 and model_output.strip():
                    self._monitoring.add_span_event(
                        "length_continuation_started",
                        {"ordinal": _length_continuation_ordinal + 1},
                    )
                    continuation_messages = [
                        *messages,
                        {"role": "assistant", "content": model_output},
                        {
                            "role": "user",
                            "content": (
                                "Continue the preceding answer exactly where it stopped. "
                                "Do not repeat existing text and do not add a new introduction."
                            ),
                        },
                    ]
                    continuation = self.__call__(
                        messages=continuation_messages,
                        stop_sequences=stop_sequences,
                        response_format=response_format,
                        tools_to_call_from=tools_to_call_from,
                        _token_tracker=token_tracker,
                        safe_input_budget_snapshot=safe_input_budget_snapshot,
                        context_rebuild=context_rebuild,
                        _budget_retry_ordinal=_budget_retry_ordinal,
                        _soft_rebuild_attempted=_soft_rebuild_attempted,
                        _previous_preflight=self.last_final_request_preflight,
                        _side_effect_guard=side_effect_guard,
                        _recovery_original_hard_count=_recovery_original_hard_count,
                        _provider_safe_limit=_provider_safe_limit,
                        _length_continuation_ordinal=_length_continuation_ordinal + 1,
                        usage_purpose=usage_purpose,
                        usage_turn_id=usage_turn_id,
                        **kwargs,
                    )
                    continuation_text = continuation.content or ""
                    merged_content, made_progress = _merge_continuation_text(
                        model_output, continuation_text
                    )
                    if made_progress:
                        continuation.content = merged_content
                        if continuation.token_usage is not None and message.token_usage is not None:
                            continuation.token_usage = _token_usage(
                                input_tokens=(
                                    message.token_usage.input_tokens
                                    + continuation.token_usage.input_tokens
                                ),
                                output_tokens=(
                                    message.token_usage.output_tokens
                                    + continuation.token_usage.output_tokens
                                ),
                            )
                        continuation.provider_call_usages = tuple(self.provider_call_usages)
                        return continuation
            return message

        except Exception as e:
            partial_usage = None
            if chunk_list:
                partial_usage = getattr(chunk_list[-1], "usage", None)
            self._finalize_provider_call_usage(
                locals().get("provider_call_record"),
                raw_usage=partial_usage,
                input_tokens=None,
                output_tokens=None,
                status="partial" if token_join or partial_usage is not None else "failed",
                finish_reason=finish_reason,
                first_token_received=first_token_received,
            )
            if token_tracker:
                self._monitoring.add_span_event("error_occurred", {"error_type": type(
                    e).__name__, "error_message": str(e)})

            if is_provider_context_overflow(e):
                if trusted_budget_snapshot is None:
                    raise ValueError(f"Token limit exceeded: {str(e)}") from e
                partial_prose = "".join(token_join)
                if tool_call_fragments:
                    self._record_recovery_state("retry_unsafe_after_response")
                    raise ProviderContextOverflowRetryUnsafe(
                        "provider overflow arrived after tool-call fragments"
                    ) from e
                if not side_effect_guard.recovery_safe and not partial_prose:
                    self._record_recovery_state("retry_unsafe_after_response")
                    raise ProviderContextOverflowRetryUnsafe(
                        "provider overflow arrived after an observable side effect"
                    ) from e
                recovered = self._recover_provider_overflow(
                    e,
                    preflight=self.last_final_request_preflight,
                    context_rebuild=context_rebuild,
                    token_tracker=token_tracker,
                    stop_sequences=stop_sequences,
                    response_format=response_format,
                    tools_to_call_from=tools_to_call_from,
                    trusted_budget_snapshot=trusted_budget_snapshot,
                    retry_ordinal=_budget_retry_ordinal,
                    call_kwargs=kwargs,
                    recovery_original_hard_count=_recovery_original_hard_count,
                    provider_safe_limit=_provider_safe_limit,
                    continuation_prefix=partial_prose or None,
                )
                if partial_prose:
                    recovered.content = partial_prose + (recovered.content or "")
                return recovered
            return retry_transport_error(e)

    def _dispatch_chat_completion(
        self,
        *,
        safe_input_budget_snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]] = None,
        capacity_snapshot: Optional[Dict[str, Any]] = None,
        retry_ordinal: int = 0,
        request_rebuild_available: bool = False,
        soft_rebuild_attempted: bool = False,
        previous_preflight: Optional[FinalRequestPreflight] = None,
        usage_purpose: str = "main_agent",
        usage_turn_id: Optional[str] = None,
        **completion_kwargs: Any,
    ) -> Any:
        """Dispatch the OpenAI chat completion request.

        When W2 supplied a trusted safe-input-budget snapshot, this method is
        the provider dispatch boundary: caller `max_tokens` overrides must
        match the snapshot, and absent values are filled from the snapshot.

        When the active W1 capacity snapshot is also threaded through, the
        boundary additionally verifies W1->W2 fingerprint and provider/model
        identity to catch a stale or cross-model W2 snapshot before the
        provider call.
        """
        from ...monitor.monitoring import set_monitoring_final_request_evidence
        set_monitoring_final_request_evidence(None)
        snapshot = self._coerce_safe_input_budget_snapshot(safe_input_budget_snapshot)
        if snapshot is not None:
            self._verify_w1_w2_consistency(
                budget_snapshot=snapshot,
                capacity_snapshot=capacity_snapshot,
            )
            request_model = completion_kwargs.get("model")
            if request_model is not None and str(request_model) != snapshot.model_name:
                raise SafeInputBudgetCapacityMismatch(
                    field="model_name",
                    expected=snapshot.model_name,
                    actual=str(request_model),
                )
            # Profile/operator model capacity is the wire authority. The
            # snapshot fallback only keeps legacy SDK callers without a model
            # capacity contract operational during the compatibility window.
            trusted_max_tokens = (
                self.max_output_tokens or snapshot.requested_output_tokens
            )
            caller_max_tokens = completion_kwargs.get("max_tokens")
            if caller_max_tokens is not None and caller_max_tokens != trusted_max_tokens:
                raise CallerMaxTokensOverrideForbidden(
                    snapshot_value=trusted_max_tokens,
                    caller_value=caller_max_tokens,
                )
            completion_kwargs["max_tokens"] = trusted_max_tokens
            self._monitoring.set_span_attributes(
                **{"llm.request.max_output_tokens": trusted_max_tokens}
            )
            identity = self._build_final_request_identity(snapshot)
            final_shape = build_final_request_shape(completion_kwargs)
            provider_count, fallback_reason = count_final_request(
                final_shape,
                metadata=self.token_count_probe_metadata,
                base_url=self._token_count_api_base,
                api_key=self._token_count_api_key,
                model_name=self.model_id,
                canonical_model_id=identity.canonical_model_id,
                ssl_verify=self._token_count_ssl_verify,
            )
            tokenizer_count = self._verified_tokenizer_count(final_shape)
            preflight = self._final_request_meter.measure(
                completion_kwargs,
                identity=identity,
                soft_budget=snapshot.soft_input_budget_tokens,
                hard_budget=snapshot.hard_input_budget_tokens,
                provider_count=provider_count,
                tokenizer_count=tokenizer_count,
                fallback_reason=fallback_reason,
                retry_ordinal=retry_ordinal,
            )
            if retry_ordinal > 0 and previous_preflight is not None and (
                preflight.request_fingerprint == previous_preflight.request_fingerprint
                or preflight.hard_count >= previous_preflight.hard_count
            ):
                self._record_recovery_state("no_reduction")
                raise CompactionNoReduction(
                    "compaction_no_reduction: rebuilt final request did not strictly shrink"
                )
            self.last_final_request_preflight = preflight
            self._record_final_request_preflight(
                preflight,
                recovery_state=(
                    "recovered"
                    if retry_ordinal > 0
                    else "soft_rebuilt"
                    if soft_rebuild_attempted
                    else "not_attempted"
                ),
            )
            if (
                preflight.soft_exceeded
                and request_rebuild_available
                and not soft_rebuild_attempted
            ):
                raise FinalRequestSoftBudgetExceeded(preflight)
        call_record = ProviderCallUsage(
            turn_id=getattr(self, "_active_usage_turn_id", usage_turn_id),
            step_number=self.context_budget_step_number,
            purpose=getattr(self, "_active_usage_purpose", usage_purpose),
            attempt=retry_ordinal,
            provider=self.model_factory or "unknown",
            model=self.model_id,
            capability_profile_version=(self.provider_usage_profile or {}).get(
                "capability_profile_version"
            ),
            status="failed",
        )
        call_record._started_at = time.time()
        self.provider_call_usages.append(call_record)
        self.turn_provider_call_usages.append(call_record)
        self.last_provider_call_usage = call_record
        try:
            logger.info(
                "event=chat_completion_create model_id=%s kwargs=%s",
                self.model_id,
                json.dumps(
                    {key: value for key, value in completion_kwargs.items() if key != "messages"},
                    ensure_ascii=False,
                    default=str,
                ),
            )
            return self.client.chat.completions.create(**completion_kwargs)
        except Exception:
            self._finalize_provider_call_usage(
                call_record,
                raw_usage=None,
                input_tokens=None,
                output_tokens=None,
                status="failed",
                finish_reason=None,
                first_token_received=False,
            )
            raise

    def _finalize_provider_call_usage(
        self,
        record: Optional[ProviderCallUsage],
        *,
        raw_usage: Any,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        status: str,
        finish_reason: Optional[str],
        first_token_received: bool,
    ) -> None:
        """Finalize a physical-call record once without exposing request content."""
        if record is None or record.status in {"completed", "partial"}:
            return
        normalized, quality, source, metadata = normalize_provider_usage(
            raw_usage,
            provider=record.provider,
            model=record.model,
            capability_profile=self.provider_usage_profile,
        )
        started_at = getattr(record, "_started_at", None)
        record.source = source
        record.status = status
        record.usage = normalized
        record.quality = quality
        record.finish_reason = finish_reason
        record.duration_ms = (
            max(0, round((time.time() - started_at) * 1000))
            if started_at is not None
            else None
        )
        first_token_at = getattr(record, "_first_token_at", None)
        record.time_to_first_token_ms = (
            max(0, round((first_token_at - started_at) * 1000))
            if first_token_received and first_token_at is not None and started_at is not None
            else None
        )
        record.provider_metadata = metadata
        from ..agents.context.composition import reconcile_context_composition

        evidence = getattr(self, "last_context_evidence", None)
        raw_composition = dict(
            getattr(evidence, "context_composition_estimate", ()) or ()
        )
        record.context_composition = reconcile_context_composition(
            raw_composition,
            record.usage.input_tokens if record.source == "provider" else None,
        ).to_dict()
        if not getattr(record, "_usage_event_emitted", False):
            usage_event_type = getattr(ProcessType, "LLM_USAGE", None)
            if (
                usage_event_type is not None
                and self.observer is not None
                and hasattr(self.observer, "add_message")
            ):
                self.observer.add_message(
                    "",
                    usage_event_type,
                    json.dumps(record.to_dict(), ensure_ascii=False),
                )
            record._usage_event_emitted = True
        usage_span_attributes = {
            "usage.call_id": record.call_id,
            "usage.source": record.source,
            "usage.status": record.status,
            "usage.input_tokens": record.usage.input_tokens,
            "usage.output_tokens": record.usage.output_tokens,
            "usage.total_tokens": record.usage.total_tokens,
            "usage.fresh_input_tokens": record.usage.fresh_input_tokens,
            "usage.cache_read_tokens": record.usage.cache_read_tokens,
            "usage.cache_write_tokens": record.usage.cache_write_tokens,
            "usage.reasoning_tokens": record.usage.reasoning_tokens,
            "usage.visible_output_tokens": record.usage.visible_output_tokens,
            "usage.quality_reasons": json.dumps(record.quality.reasons),
            **{
                f"context.composition.{name}": value
                for name, value in record.context_composition["segments"].items()
            },
        }
        self._monitoring.set_span_attributes(
            **{
                key: value
                for key, value in usage_span_attributes.items()
                if value is not None
            }
        )

    def _verified_tokenizer_count(self, shape: Any) -> Optional[int]:
        metadata = self.tokenizer_match_metadata or {}
        if (
            shape.request_shape != "text"
            or not self.tokenizer_family
            or metadata.get("auto_applicable") is not True
        ):
            return None
        adapter, mode = resolve_tokenizer(self.tokenizer_family)
        if mode != "exact":
            return None
        messages = shape.semantic_request.get("messages") or []
        message_count = adapter.count_tokens(messages)
        return max(
            1,
            message_count
            + shape.components.reasoning
            + shape.components.other_semantic,
        )

    def _recover_provider_overflow(
        self,
        error: BaseException,
        *,
        preflight: Optional[FinalRequestPreflight],
        context_rebuild: Optional[Callable[[int], Any]],
        token_tracker: Any,
        stop_sequences: Optional[List[str]],
        response_format: Optional[dict[str, str]],
        tools_to_call_from: Optional[List[Tool]],
        trusted_budget_snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]],
        retry_ordinal: int,
        call_kwargs: Dict[str, Any],
        recovery_original_hard_count: Optional[int],
        provider_safe_limit: Optional[int],
        continuation_prefix: Optional[str] = None,
    ) -> ChatMessage:
        if retry_ordinal >= 2:
            self._record_recovery_state("retry_exhausted")
            raise ProviderContextOverflowRetryExhausted(
                "provider context overflow persisted after two safe recovery requests"
            ) from error
        if context_rebuild is None or preflight is None:
            self._record_recovery_state("retry_unsafe")
            raise ProviderContextOverflowRetryUnsafe(
                "provider context overflow cannot be rebuilt from source"
            ) from error
        self._monitoring.add_span_event(
            "provider_context_overflow",
            {"retry_ordinal": retry_ordinal, "recovery_safe": True},
        )
        self._record_recovery_state("retrying")
        original_hard_count = recovery_original_hard_count or preflight.hard_count
        reported_limit = self._provider_context_limit(error) or provider_safe_limit
        return self._rebuild_and_retry(
            preflight,
            context_rebuild=context_rebuild,
            token_tracker=token_tracker,
            stop_sequences=stop_sequences,
            response_format=response_format,
            tools_to_call_from=tools_to_call_from,
            trusted_budget_snapshot=trusted_budget_snapshot,
            retry_ordinal=retry_ordinal + 1,
            soft_rebuild_attempted=True,
            call_kwargs=call_kwargs,
            recovery_original_hard_count=original_hard_count,
            provider_safe_limit=reported_limit,
            continuation_prefix=continuation_prefix,
        )

    def _rebuild_and_retry(
        self,
        preflight: FinalRequestPreflight,
        *,
        context_rebuild: Optional[Callable[[int], Any]],
        token_tracker: Any,
        stop_sequences: Optional[List[str]],
        response_format: Optional[dict[str, str]],
        tools_to_call_from: Optional[List[Tool]],
        trusted_budget_snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]],
        retry_ordinal: int,
        soft_rebuild_attempted: bool,
        call_kwargs: Dict[str, Any],
        recovery_original_hard_count: Optional[int] = None,
        provider_safe_limit: Optional[int] = None,
        continuation_prefix: Optional[str] = None,
    ) -> ChatMessage:
        if context_rebuild is None:
            self._record_recovery_state("retry_unsafe")
            raise ProviderContextOverflowRetryUnsafe(
                "final request needs source-backed rebuild but none is available"
            )
        if recovery_original_hard_count is None:
            target = max(1, min(preflight.soft_budget, int(preflight.hard_count * 0.9)))
        else:
            ratio = 0.75 if retry_ordinal == 1 else 0.5
            target = max(1, int(recovery_original_hard_count * ratio))
            if provider_safe_limit is not None:
                target = min(target, provider_safe_limit)
        if continuation_prefix:
            continuation_instruction = (
                "Continue the interrupted answer exactly where it stopped. "
                "Do not repeat any text already written."
            )
            target = max(
                1,
                target - estimate_tokens_text(continuation_prefix + continuation_instruction),
            )
        try:
            rebuilt = (
                context_rebuild(target, emergency_archive=True)
                if retry_ordinal >= 2
                else context_rebuild(target)
            )
        except Exception as rebuild_error:
            recoverable_reasons = {
                "compaction_no_reduction",
                "final_request_over_hard_budget",
            }
            if (
                getattr(rebuild_error, "context_rebuild_over_budget", False) is True
                and
                recovery_original_hard_count is not None
                and retry_ordinal == 1
                and getattr(rebuild_error, "failure_reason", None) in recoverable_reasons
            ):
                self._monitoring.add_span_event(
                    "provider_context_rebuild_exhausted",
                    {
                        "retry_ordinal": retry_ordinal,
                        "failure_reason": getattr(rebuild_error, "failure_reason", "unknown"),
                        "advancing_to_emergency_archive": True,
                    },
                )
                return self._rebuild_and_retry(
                    preflight,
                    context_rebuild=context_rebuild,
                    token_tracker=token_tracker,
                    stop_sequences=stop_sequences,
                    response_format=response_format,
                    tools_to_call_from=tools_to_call_from,
                    trusted_budget_snapshot=trusted_budget_snapshot,
                    retry_ordinal=2,
                    soft_rebuild_attempted=True,
                    call_kwargs=call_kwargs,
                    recovery_original_hard_count=recovery_original_hard_count,
                    provider_safe_limit=provider_safe_limit,
                    continuation_prefix=continuation_prefix,
                )
            raise
        rebuilt_messages = getattr(rebuilt, "messages", rebuilt)
        if not isinstance(rebuilt_messages, list):
            raise TypeError("context_rebuild must return FinalContext or a message list")
        if continuation_prefix:
            rebuilt_messages = [
                *rebuilt_messages,
                {"role": "assistant", "content": continuation_prefix},
                {
                    "role": "user",
                    "content": (
                        continuation_instruction
                    ),
                },
            ]
        evidence = getattr(rebuilt, "evidence", None)
        if evidence is not None:
            self.last_context_evidence = evidence
        rebuilt_runtime_tools = getattr(rebuilt, "runtime_tools", ())
        if rebuilt_runtime_tools:
            tools_to_call_from = list(rebuilt_runtime_tools)
        return self.__call__(
            messages=rebuilt_messages,
            stop_sequences=stop_sequences,
            response_format=response_format,
            tools_to_call_from=tools_to_call_from,
            _token_tracker=token_tracker,
            safe_input_budget_snapshot=trusted_budget_snapshot,
            context_rebuild=context_rebuild,
            _budget_retry_ordinal=retry_ordinal,
            _soft_rebuild_attempted=soft_rebuild_attempted,
            _previous_preflight=preflight,
            _side_effect_guard=RequestSideEffectGuard(),
            _recovery_original_hard_count=recovery_original_hard_count,
            _provider_safe_limit=provider_safe_limit,
            **call_kwargs,
        )

    @staticmethod
    def _provider_context_limit(error: BaseException) -> Optional[int]:
        """Extract a provider-reported maximum for this run only."""
        for pattern in (
            r"maximum context(?: length)?(?: is|:)?\s*([0-9][0-9,]*)",
            r"max(?:imum)?[_ ]context[_ ](?:length|tokens)(?: is|:|=)?\s*([0-9][0-9,]*)",
            r"context window(?: is|:)?\s*([0-9][0-9,]*)",
        ):
            match = re.search(pattern, str(error), re.IGNORECASE)
            if match:
                return max(1, int(match.group(1).replace(",", "")))
        return None

    def _provisional_budget_snapshot(self) -> SafeInputBudgetSnapshot:
        """Build a non-persisted 32K capacity snapshot for this invocation."""
        requested_output = derive_output_protection_tokens(
            context_window_tokens=32_768,
            max_output_tokens=max(1, int(self.max_output_tokens or 4096)),
        )
        provider_input = max(1, 32_768 - requested_output)
        soft = provider_input
        fields = {
            "requested_output_tokens": "model_default",
            "soft_limit_ratio": "code_default",
            "uncertainty_reserve_tokens": "derived",
            "provider_input_limit_tokens": "derived",
            "hard_input_budget_tokens": "derived",
            "soft_input_budget_tokens": "derived",
        }
        provider = self.model_factory or "unknown"
        w1 = "provisional-32768"
        fingerprint = compute_w2_fingerprint(
            w2_resolver_version="1.1.0", w1_fingerprint=w1,
            provider=provider, model_name=self.model_id,
            requested_output_tokens=requested_output, output_reserve_source="model_default",
            uncertainty_reserve_tokens=0, uncertainty_reserve_basis="none",
            approved_profile_reserve_tokens=None, soft_limit_ratio=0.9,
            soft_limit_ratio_source="code_default", soft_input_budget_tokens=soft,
            hard_input_budget_tokens=provider_input, field_sources=fields,
            warnings=("provisional_32768_capacity",),
        )
        return SafeInputBudgetSnapshot(
            w1_fingerprint=w1, provider=provider, model_name=self.model_id,
            requested_output_tokens=requested_output, output_reserve_source="model_default",
            provider_input_limit_tokens=provider_input, uncertainty_reserve_tokens=0,
            uncertainty_reserve_basis="none", soft_limit_ratio=0.9,
            soft_limit_ratio_source="code_default", soft_input_budget_tokens=soft,
            hard_input_budget_tokens=provider_input, field_sources=fields,
            warnings=("provisional_32768_capacity",), fingerprint=fingerprint,
        )

    def _build_final_request_identity(
        self,
        snapshot: SafeInputBudgetSnapshot | Dict[str, Any],
    ) -> FinalRequestIdentity:
        resolved = self._coerce_safe_input_budget_snapshot(snapshot)
        if resolved is None:  # pragma: no cover - protected by callers
            raise ValueError("safe input budget snapshot is required")
        probe = self.token_count_probe_metadata or {}
        runtime_endpoint = (
            endpoint_fingerprint(self._token_count_api_base)
            if self._token_count_api_base
            else "unknown_endpoint"
        )
        return FinalRequestIdentity(
            endpoint_fingerprint=runtime_endpoint,
            credential_scope_fingerprint=str(
                probe.get("credential_scope_fingerprint") or "unknown_scope"
            ),
            canonical_model_id=str(
                self.canonical_model_id
                or probe.get("model_identity")
                or f"{resolved.provider}:{resolved.model_name}"
            ),
            provider=resolved.provider,
            model_name=resolved.model_name,
            w1_fingerprint=resolved.w1_fingerprint,
            w2_fingerprint=resolved.fingerprint,
        )

    def _record_recovery_state(self, state: str) -> None:
        self.last_recovery_state = state
        from ...monitor.monitoring import update_monitoring_final_request_evidence
        update_monitoring_final_request_evidence(
            recovery_state=state,
            provider_overflow=state in {"retrying", "retry_exhausted", "retry_unsafe", "retry_unsafe_after_response"},
            recovery_attempted=state in {"retrying", "recovered", "retry_exhausted"},
            recovery_succeeded=state == "recovered",
        )
        self._monitoring.set_span_attributes(
            **{"context.final_request.recovery_state": state}
        )

    def _record_final_request_preflight(
        self,
        preflight: FinalRequestPreflight,
        *,
        recovery_state: str,
    ) -> None:
        self.last_recovery_state = recovery_state
        components = preflight.components
        from ...monitor.monitoring import set_monitoring_final_request_evidence
        context_evidence = getattr(self, "last_context_evidence", None)
        set_monitoring_final_request_evidence({
            "schema_version": 1,
            "provider_protocol": getattr(self, "model_factory", None),
            "count_source": getattr(preflight.count_source, "value", str(preflight.count_source)),
            "raw_estimate_tokens": preflight.raw_estimate,
            "hard_count_tokens": preflight.hard_count,
            "context_raw_tokens": int(getattr(context_evidence, "raw_token_estimate", 0) or 0),
            "context_final_tokens": int(getattr(context_evidence, "final_token_estimate", 0) or 0),
            "compression_attempted": bool(getattr(context_evidence, "compression_attempted", False)),
            "request_fingerprint": preflight.request_fingerprint,
            "retry_ordinal": preflight.retry_ordinal,
            "recovery_state": recovery_state,
            "provider_overflow": recovery_state in {"retrying", "retry_exhausted", "retry_unsafe"},
            "recovery_attempted": preflight.retry_ordinal > 0,
            "recovery_succeeded": recovery_state == "recovered",
            "anchor_input_tokens": preflight.anchor_input_tokens,
            "estimated_delta_tokens": preflight.estimated_delta_tokens,
            "anchor_invalidation_reason": preflight.anchor_invalidation_reason,
        })
        context_budget_type = getattr(ProcessType, "CONTEXT_BUDGET", None)
        if self.observer is not None and context_budget_type is not None:
            # Keep Agent-layer event projection optional for lightweight SDK
            # integrations that import the model package without Agent modules.
            from ..agents.context_budget_event import build_context_budget_event

            budget_event = build_context_budget_event(
                preflight, context_evidence,
                step_number=self.context_budget_step_number,
                recovery_state=recovery_state,
                recovery=(
                    {
                        "trigger": "provider_overflow" if preflight.retry_ordinal else "preflight",
                        "phase": "archive" if getattr(context_evidence, "archive_active", False) else "compression",
                        "attempt": int(preflight.retry_ordinal),
                        "maximum_attempts": 2,
                        "compression_target": int(preflight.hard_budget),
                        "provisional_capacity": bool(getattr(self, "_using_provisional_capacity", False)),
                    }
                    if preflight.retry_ordinal or getattr(self, "_using_provisional_capacity", False)
                    else None
                ),
            )
            self.observer.add_message(
                "", context_budget_type,
                json.dumps(budget_event, ensure_ascii=False),
            )
        self._monitoring.set_span_attributes(
            **{
                "context.final_request.fingerprint": preflight.request_fingerprint,
                "context.final_request.identity_fingerprint": preflight.identity_fingerprint,
                "context.final_request.shape": preflight.request_shape,
                "context.final_request.count_source": preflight.count_source,
                "context.final_request.raw_estimate": preflight.raw_estimate,
                "context.final_request.soft_count": preflight.soft_count,
                "context.final_request.hard_count": preflight.hard_count,
                "context.final_request.soft_exceeded": preflight.soft_exceeded,
                "context.final_request.hard_exceeded": preflight.hard_exceeded,
                "context.final_request.components.message_text": components.message_text,
                "context.final_request.components.message_framing": components.message_framing,
                "context.final_request.components.tools": components.tools,
                "context.final_request.components.media": components.media,
                "context.final_request.components.reasoning": components.reasoning,
                "context.final_request.components.other_semantic": components.other_semantic,
                "context.final_request.calibration_key": preflight.calibration_key_fingerprint,
                "context.final_request.calibration_samples": preflight.calibration_sample_count,
                "context.final_request.calibration_p95": preflight.calibration_p95 or 0.0,
                "context.final_request.calibration_p99": preflight.calibration_p99 or 0.0,
                "context.final_request.estimator_version": preflight.estimator_version,
                "context.final_request.anchor_input_tokens": preflight.anchor_input_tokens or 0,
                "context.final_request.estimated_delta_tokens": preflight.estimated_delta_tokens or 0,
                "context.final_request.anchor_invalidation_reason": preflight.anchor_invalidation_reason or "",
                "context.final_request.retry_ordinal": preflight.retry_ordinal,
                "context.final_request.recovery_state": recovery_state,
                "context.final_request.count_fallback_reason": preflight.fallback_reason or "",
            }
        )

    @staticmethod
    def _verify_w1_w2_consistency(
        *,
        budget_snapshot: SafeInputBudgetSnapshot,
        capacity_snapshot: Optional[Dict[str, Any]],
    ) -> None:
        """Reject a W2 snapshot whose W1 identity disagrees with the active W1.

        Defense-in-depth per CM-013: a W2 snapshot computed from a different
        model's W1 capacity (model swap mid-flight, stale cache, cross-tenant
        leak) must not be allowed through dispatch even if its own fingerprint
        self-checks.

        When the active W1 capacity_snapshot is not threaded through, the
        check is skipped. This preserves the migration window for legacy
        rows without capacity columns, where W2 already does not produce a
        snapshot.
        """
        if not capacity_snapshot:
            return
        w1_fingerprint = capacity_snapshot.get("capacity_fingerprint")
        provider = capacity_snapshot.get("provider")
        model_name = capacity_snapshot.get("model_name")
        if not w1_fingerprint and not provider and not model_name:
            return
        if w1_fingerprint and w1_fingerprint != budget_snapshot.w1_fingerprint:
            raise SafeInputBudgetCapacityMismatch(
                field="w1_fingerprint",
                expected=w1_fingerprint,
                actual=budget_snapshot.w1_fingerprint,
            )
        if provider and provider != budget_snapshot.provider:
            raise SafeInputBudgetCapacityMismatch(
                field="provider",
                expected=provider,
                actual=budget_snapshot.provider,
            )
        if model_name and model_name != budget_snapshot.model_name:
            raise SafeInputBudgetCapacityMismatch(
                field="model_name",
                expected=model_name,
                actual=budget_snapshot.model_name,
            )

    @staticmethod
    def _coerce_safe_input_budget_snapshot(
        snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]],
    ) -> Optional[SafeInputBudgetSnapshot]:
        if snapshot is None:
            return None
        if isinstance(snapshot, SafeInputBudgetSnapshot):
            resolved = snapshot
        elif isinstance(snapshot, dict):
            resolved = SafeInputBudgetSnapshot.model_validate(snapshot)
        else:
            raise TypeError(
                "safe_input_budget_snapshot must be a SafeInputBudgetSnapshot or dict"
            )
        expected = compute_w2_fingerprint(
            w2_resolver_version=resolved.resolver_version,
            w1_fingerprint=resolved.w1_fingerprint,
            provider=resolved.provider,
            model_name=resolved.model_name,
            requested_output_tokens=resolved.requested_output_tokens,
            output_reserve_source=resolved.output_reserve_source,
            uncertainty_reserve_tokens=resolved.uncertainty_reserve_tokens,
            uncertainty_reserve_basis=resolved.uncertainty_reserve_basis,
            approved_profile_reserve_tokens=resolved.approved_profile_reserve_tokens,
            soft_limit_ratio=resolved.soft_limit_ratio,
            soft_limit_ratio_source=resolved.soft_limit_ratio_source,
            soft_input_budget_tokens=resolved.soft_input_budget_tokens,
            hard_input_budget_tokens=resolved.hard_input_budget_tokens,
            field_sources=resolved.field_sources,
            warnings=resolved.warnings,
        )
        if resolved.fingerprint != expected:
            raise SafeInputBudgetFingerprintMismatch(
                expected=expected,
                actual=resolved.fingerprint,
            )
        return resolved

    @classmethod
    def _safe_input_budget_trace_attributes(
        cls,
        snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]],
    ) -> Dict[str, Any]:
        snapshot = cls._coerce_safe_input_budget_snapshot(snapshot)
        if snapshot is None:
            return {}
        return {
            "w2.budget_fingerprint": snapshot.fingerprint,
            "w2.w1_fingerprint": snapshot.w1_fingerprint,
            "w2.requested_output_tokens": snapshot.requested_output_tokens,
            "w2.output_reserve_source": snapshot.output_reserve_source,
            "w2.provider_input_limit_tokens": snapshot.provider_input_limit_tokens,
            "w2.soft_input_budget_tokens": snapshot.soft_input_budget_tokens,
            "w2.hard_input_budget_tokens": snapshot.hard_input_budget_tokens,
            "w2.uncertainty_reserve_tokens": snapshot.uncertainty_reserve_tokens,
            "w2.uncertainty_reserve_basis": snapshot.uncertainty_reserve_basis,
        }

    async def check_connectivity(self) -> bool:
        """
        Test if the connection to the remote OpenAI large model service is normal

        Returns:
            bool: True if the connection is successful, False if it fails
        """
        try:
            # Construct a simple test message
            test_message = [{"role": "user", "content": "Hello"}]

            # Directly send a short chat request to test the connection
            completion_kwargs = self._prepare_completion_kwargs(
                messages=test_message,
                model=self.model_id,
                max_tokens=5,
            )

            # Offload the blocking SDK call to a thread pool to avoid blocking the event loop
            await asyncio.to_thread(
                self.client.chat.completions.create,
                stream=False,
                **completion_kwargs,
            )

            # If no exception is raised, the connection is successful
            return True
        except Exception as e:
            logging.error(f"Connection test failed: {str(e)}")
            return False
