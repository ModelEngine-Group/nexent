from ...monitor import get_monitoring_manager
from ...monitor.monitoring import (
    _MonitoredClient,
    _monitoring_operation,
    _monitoring_display_name,
    _detect_model_type,
    OPENINFERENCE_INPUT_VALUE,
)
from ..utils.token_estimation import estimate_tokens_text
from ..concurrency import RunCancellationScope, run_blocking
import logging
import threading
import asyncio
import time
import json
import httpx
from typing import List, Optional, Dict, Any

from openai.types.chat.chat_completion_message import ChatCompletionMessage
from smolagents import Tool
from smolagents.models import OpenAIServerModel, ChatMessage, MessageRole

from .capacity_budget import (
    CallerMaxTokensOverrideForbidden,
    ContextBudgetCapacityMismatch,
    ContextBudgetSnapshot,
    parse_context_budget_snapshot,
)
from ..utils.observer import MessageObserver, ProcessType
from .prompt_cache import (
    apply_cache_directives,
    cache_directive_advice,
    extract_prompt_cache_usage,
    resolve_prompt_cache_profile,
)
from .message_utils import content_has_multimodal_blocks, prepare_messages_for_smolagents_text_flattening
from .context_overflow import (
    ProviderContextOverflowRetryExhausted,
    ProviderContextOverflowRetryUnsafe,
    is_provider_context_overflow,
)
from .model_concurrency import ModelConcurrencyExceeded, model_concurrency_limiter
from .retry import (
    DEFAULT_MODEL_RETRY,
    ModelRetryConfig,
    classify_model_error,
    get_retry_after_seconds,
)

logger = logging.getLogger("openai_llm")


def _bad_request_error_type() -> Optional[type]:
    """Resolve openai.BadRequestError lazily; None when unavailable.

    Test doubles may stub the openai package with a non-module object where
    the import fails; in that case sampling-fallback judgement is disabled
    and the original exception propagates unchanged.
    """
    try:
        from openai import BadRequestError

        return BadRequestError
    except ImportError:
        return None

# Raised (with this message) when a model invocation is aborted because the
# caller's stop event was set. Reused at every stop_event check site so the
# message stays consistent and is easy to assert against in tests.
STOP_EVENT_INTERRUPTED_MESSAGE = "Model is interrupted by stop event"


class EmptyModelResponseError(RuntimeError):
    """Raised when a completed provider stream contains no user-visible content."""


def _is_timeout_error(exc: BaseException) -> bool:
    """Return whether an exception chain represents a network or caller timeout."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TimeoutException)):
            return True
        if "timeout" in type(current).__name__.lower():
            return True
        current = current.__cause__ or current.__context__
    return False


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
                 context_budget_snapshot: Optional[ContextBudgetSnapshot | Dict[str, Any]] = None,
                 timeout_seconds: Optional[float] = None,
                 retry_config: Optional["ModelRetryConfig"] = None,
                 cancellation_scope: Optional[RunCancellationScope] = None,
                 concurrency_limit: Optional[int] = None,
                 concurrency_key: Optional[tuple[str, str, str]] = None,
                 concurrency_wait_timeout_seconds: float = 30.0,
                 connect_timeout_seconds: float = 10.0,
                 read_timeout_seconds: Optional[float] = None,
                 write_timeout_seconds: float = 30.0,
                 pool_timeout_seconds: float = 10.0,
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

        self.observer = observer
        self.temperature = temperature
        self.top_p = top_p
        self.stop_event = (
            cancellation_scope.stop_event if cancellation_scope else threading.Event()
        )
        self.cancellation_scope = cancellation_scope or RunCancellationScope(self.stop_event)
        self.concurrency_limit = concurrency_limit
        self.concurrency_key = concurrency_key
        self.concurrency_wait_timeout_seconds = concurrency_wait_timeout_seconds
        self._monitoring = get_monitoring_manager()
        self.model_factory = (model_factory or "").lower()
        self.flatten_messages_as_text = flatten_messages_as_text
        self.display_name = display_name
        self.extra_body = extra_body or None
        self.prompt_cache = prompt_cache or None
        self.last_provider_cache_advice = None
        self.last_prompt_cache_usage = None
        self.last_cached_input_token_count = 0
        self.last_response_diagnostics = None
        self.context_budget_snapshot = context_budget_snapshot
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
        self.read_timeout_seconds = read_timeout_seconds or timeout_seconds or 60.0

        # Keep every streaming HTTP phase finite. Callers can still inject a
        # custom client through client_kwargs when they own its lifecycle.
        client_kwargs = kwargs.get("client_kwargs", {})
        if "http_client" not in client_kwargs:
            from openai import DefaultHttpxClient
            from openai._base_client import httpx2

            http_client = DefaultHttpxClient(
                verify=ssl_verify,
                timeout=httpx2.Timeout(
                    connect=connect_timeout_seconds,
                    read=self.read_timeout_seconds,
                    write=write_timeout_seconds,
                    pool=pool_timeout_seconds,
                ),
            )
            client_kwargs["http_client"] = http_client
            kwargs["client_kwargs"] = client_kwargs

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

    @property
    def context_budget_snapshot(self) -> Optional[ContextBudgetSnapshot]:
        return self._context_budget_snapshot

    @context_budget_snapshot.setter
    def context_budget_snapshot(
        self,
        value: Optional[ContextBudgetSnapshot | Dict[str, Any]],
    ) -> None:
        """Validate the complete V2 contract at every runtime assignment."""
        self._context_budget_snapshot = (
            parse_context_budget_snapshot(value) if value is not None else None
        )

    def __call__(self, messages: List[Dict[str, Any]], stop_sequences: Optional[List[str]] = None,
                 response_format: dict[str, str] | None = None, tools_to_call_from: Optional[List[Tool]] = None,
                 _token_tracker=None, context_budget_snapshot: Optional[ContextBudgetSnapshot] = None,
                 context_rebuild=None, _overflow_recovery_ordinal: int = 0,
                 **kwargs, ) -> ChatMessage:
        _monitoring_operation.set("chat_completion")

        if _token_tracker is None:
            trusted_budget_snapshot = (
                context_budget_snapshot or self.context_budget_snapshot
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
                self._context_budget_trace_attributes(trusted_budget_snapshot)
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
                    context_budget_snapshot=context_budget_snapshot,
                    context_rebuild=context_rebuild,
                    _overflow_recovery_ordinal=_overflow_recovery_ordinal,
                    **kwargs,
                )

        token_tracker = _token_tracker or self._monitoring.create_token_tracker(
            self.model_id)
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
            content_has_multimodal_blocks(getattr(m, "content", None))
            for m in normalized_messages
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

        # Provider-specific extras (e.g. Qwen3 chat_template_kwargs) - only
        # set when the caller actually supplied something so default OpenAI
        # behaviour is unchanged for everyone else.
        if self.extra_body:
            completion_kwargs["extra_body"] = self._translate_thinking_flag(
                self.extra_body
            )

        trusted_budget_snapshot = (
            context_budget_snapshot or self.context_budget_snapshot
        )

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

        selected_cache_profile = resolve_prompt_cache_profile(
            self.model_factory or "unknown", self.prompt_cache
        )
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
        self._monitoring.set_span_attributes(
            **{
                "llm.prompt_cache.mode": cache_advice.mode,
                "llm.prompt_cache.supported": cache_advice.supported,
                "llm.prompt_cache.directive_reason": cache_advice.reason,
            }
        )
        context_evidence = getattr(self, "last_context_evidence", None)
        if context_evidence is not None:
            self._monitoring.set_span_attributes(
                **{
                    "llm.prompt_cache.stable_prefix_fingerprint": getattr(
                        context_evidence, "stable_prefix_fingerprint", None
                    ),
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

        for attempt in range(1, self.retry_config.max_attempts + 1):
            first_token_received = False
            if self.stop_event.is_set():
                if token_tracker:
                    self._monitoring.add_span_event("model_stopped", {
                        "reason": "stop_event_set"})
                raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)
            current_request = None
            stream_token = None
            close_stream_once = None
            concurrency_permit = None
            received_chunk_count = 0
            try:
                if self.concurrency_limit is not None:
                    concurrency_permit = model_concurrency_limiter.acquire(
                        self.concurrency_key
                        or ("default", self.model_factory or "unknown", str(self.model_id)),
                        self.concurrency_limit,
                        self.concurrency_wait_timeout_seconds,
                        self.stop_event,
                    )
                current_request = self._dispatch_chat_completion(
                    context_budget_snapshot=trusted_budget_snapshot,
                    capacity_snapshot=self.capacity_snapshot,
                    stream=True,
                    **dispatch_kwargs,
                )

                # Validate response type: ensure we got a proper iterator, not error strings or dicts
                # Some APIs return error strings like "error: rate limit" or JSON dicts on failure
                if isinstance(current_request, str):
                    raise ValueError(f"LLM API returned error string: {current_request}")
                if isinstance(current_request, dict):
                    error_msg = current_request.get("error") or current_request.get("message") or str(current_request)
                    raise ValueError(f"LLM API returned error: {error_msg}")

                close_stream = getattr(current_request, "close", None)
                if callable(close_stream):
                    close_lock = threading.Lock()
                    stream_closed = False

                    def _close_stream_once():
                        nonlocal stream_closed
                        with close_lock:
                            if stream_closed:
                                return
                            stream_closed = True
                        close_stream()

                    close_stream_once = _close_stream_once
                    stream_token = self.cancellation_scope.register_closer(close_stream_once)

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

                # Reset output mode
                self.observer.current_mode = ProcessType.MODEL_OUTPUT_THINKING

                # Track streaming metrics
                stream_start_time = time.time()

                try:
                    for chunk in current_request:
                        received_chunk_count += 1
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

                        new_token = getattr(chunk.choices[0].delta, "content", None)
                        reasoning_content = getattr(chunk.choices[0].delta, "reasoning", None)
                        if reasoning_content is None:
                            reasoning_content = getattr(chunk.choices[0].delta, "reasoning_content", None)

                        # Handle reasoning_content if it exists and is not null
                        if reasoning_content is not None:
                            reasoning_chunk_count += 1
                            reasoning_char_count += len(str(reasoning_content))
                            self.observer.add_model_reasoning_content(
                                reasoning_content)
                            if token_tracker and not first_token_received:
                                token_tracker.record_first_token()
                                first_token_received = True

                        if new_token is not None:
                            content_chunk_count += 1
                            # Record first token timing
                            if token_tracker and not first_token_received:
                                token_tracker.record_first_token()
                                first_token_received = True

                            # Track each token
                            if token_tracker:
                                token_tracker.record_token(new_token)

                            self.observer.add_model_new_token(new_token)
                            token_join.append(new_token)
                            role = chunk.choices[0].delta.role

                        chunk_list.append(chunk)
                        if self.stop_event.is_set():
                            if token_tracker:
                                self._monitoring.add_span_event("model_stopped", {
                                    "reason": "stop_event_set"})
                            raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)

                    # Send end marker
                    self.observer.flush_remaining_tokens()
                    model_output = "".join(token_join)
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

                    if not model_output.strip():
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

                    message = ChatMessage.from_dict(
                        ChatCompletionMessage(role=role if role else "assistant",  # If there is no explicit role, default to "assistant"
                                              content=model_output).model_dump(include={"role", "content", "tool_calls"}))

                    from smolagents.monitoring import TokenUsage

                    if input_tokens > 0 or output_tokens > 0:
                        message.token_usage = TokenUsage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens
                        )
                    message.raw = current_request
                    message.role = MessageRole.ASSISTANT
                    return message

                except Exception as e:
                    if token_tracker:
                        self._monitoring.add_span_event("error_occurred", {"error_type": type(
                            e).__name__, "error_message": str(e)})

                    raise e
            except EmptyModelResponseError:
                # Some reasoning-capable OpenAI-compatible providers
                # occasionally finish with ``stop`` after emitting only
                # reasoning chunks. Retry once inside the model adapter so an
                # otherwise transient malformed stream does not consume a
                # visible agent step. A ``length`` finish is deterministic
                # truncation and must still surface immediately.
                empty_retry_limit = min(self.retry_config.max_attempts, 2)
                if self.last_finish_reason not in (None, "stop") or attempt >= empty_retry_limit:
                    raise
                backoff = self.retry_config.calculate_backoff(attempt)
                logger.warning(
                    "event=retry_empty_model_response attempt=%d/%d finish_reason=%s "
                    "retrying_after_seconds=%.2f",
                    attempt,
                    empty_retry_limit,
                    self.last_finish_reason,
                    backoff,
                )
                self.last_retry_count = attempt
                if self.stop_event.is_set():
                    raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)
                self.stop_event.wait(backoff)
                continue
            except Exception as e:
                if self.stop_event.is_set() or self.cancellation_scope.cancelled:
                    raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE) from e
                if isinstance(e, ModelConcurrencyExceeded):
                    raise
                if token_tracker:
                    self._monitoring.add_span_event("error_occurred", {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    })
                if is_provider_context_overflow(e):
                    if first_token_received or context_rebuild is None:
                        raise ProviderContextOverflowRetryUnsafe(
                            "Provider context overflow cannot be safely rebuilt: "
                            f"{e}"
                        ) from e
                    if _overflow_recovery_ordinal >= 2:
                        raise ProviderContextOverflowRetryExhausted(
                            "Provider context overflow persisted after two recovery dispatches"
                        ) from e
                    rebuilt = context_rebuild()
                    rebuilt_messages = getattr(rebuilt, "messages", rebuilt)
                    if not isinstance(rebuilt_messages, list):
                        raise TypeError(
                            "context_rebuild must return FinalContext or a message list"
                        )
                    rebuilt_evidence = getattr(rebuilt, "evidence", None)
                    if rebuilt_evidence is not None:
                        self.last_context_evidence = rebuilt_evidence
                    self._monitoring.add_span_event("provider_context_overflow", {
                        "recovery_dispatch": _overflow_recovery_ordinal + 1,
                        "compaction_attempts": getattr(
                            rebuilt_evidence, "compaction_attempts", None
                        ),
                    })
                    if concurrency_permit is not None:
                        concurrency_permit.release()
                        concurrency_permit = None
                    return self.__call__(
                        messages=rebuilt_messages,
                        stop_sequences=stop_sequences,
                        response_format=response_format,
                        tools_to_call_from=tools_to_call_from,
                        _token_tracker=token_tracker,
                        context_budget_snapshot=trusted_budget_snapshot,
                        context_rebuild=context_rebuild,
                        _overflow_recovery_ordinal=_overflow_recovery_ordinal + 1,
                        **kwargs,
                    )
                is_timeout = _is_timeout_error(e)
                if is_timeout:
                    logger.warning(
                        "event=model_stream_timeout model_id=%s provider=%s "
                        "attempt=%d max_attempts=%d timeout_seconds=%.3f "
                        "phase=%s chunk_count=%d error_type=%s",
                        self.model_id,
                        self.model_factory or "unknown",
                        attempt,
                        self.retry_config.max_attempts,
                        self.read_timeout_seconds,
                        "initial_chunk" if received_chunk_count == 0 else "next_chunk",
                        received_chunk_count,
                        type(e).__name__,
                    )
                if classify_model_error(e) != "retryable":
                    raise
                if attempt >= self.retry_config.max_attempts:
                    if not is_timeout:
                        logging.exception(
                            "Model call failed after %d attempts: %s",
                            attempt, str(e),
                        )
                    raise
                backoff = self.retry_config.calculate_backoff(attempt)
                retry_after = get_retry_after_seconds(e)
                if retry_after is not None:
                    backoff = max(backoff, retry_after)
                if is_timeout:
                    logger.warning(
                        "event=model_stream_timeout_retry model_id=%s provider=%s "
                        "attempt=%d max_attempts=%d retrying_after_seconds=%.2f "
                        "error_type=%s",
                        self.model_id,
                        self.model_factory or "unknown",
                        attempt,
                        self.retry_config.max_attempts,
                        backoff,
                        type(e).__name__,
                    )
                else:
                    logger.warning(
                        "Model call attempt %d/%d failed with retryable error (%s); "
                        "retrying after %.2fs",
                        attempt, self.retry_config.max_attempts, str(e), backoff,
                    )
                self.last_retry_count = attempt
                if self.stop_event.is_set():
                    raise RuntimeError(STOP_EVENT_INTERRUPTED_MESSAGE)
                self.stop_event.wait(backoff)
                continue
            finally:
                if stream_token is not None:
                    self.cancellation_scope.unregister_closer(stream_token)
                if close_stream_once is not None:
                    try:
                        close_stream_once()
                    except Exception:
                        if not self.stop_event.is_set():
                            logger.warning(
                                "event=model_stream_close_failed model_id=%s",
                                self.model_id,
                                exc_info=True,
                            )
                if concurrency_permit is not None:
                    concurrency_permit.release()

    def _dispatch_chat_completion(
        self,
        *,
        context_budget_snapshot: Optional[ContextBudgetSnapshot | Dict[str, Any]] = None,
        capacity_snapshot: Optional[Dict[str, Any]] = None,
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
        snapshot = self._coerce_context_budget_snapshot(context_budget_snapshot)
        if snapshot is not None:
            self._verify_w1_w2_consistency(
                budget_snapshot=snapshot,
                capacity_snapshot=capacity_snapshot,
            )
            trusted_max_tokens = snapshot.requested_output_tokens
            caller_max_tokens = completion_kwargs.get("max_tokens")
            if caller_max_tokens is not None and caller_max_tokens != trusted_max_tokens:
                raise CallerMaxTokensOverrideForbidden(
                    snapshot_value=trusted_max_tokens,
                    caller_value=caller_max_tokens,
                )
            completion_kwargs["max_tokens"] = trusted_max_tokens
        logger.info(
            "event=chat_completion_create model_id=%s kwargs=%s",
            self.model_id,
            json.dumps(
                {k: v for k, v in completion_kwargs.items() if k != "messages"},
                ensure_ascii=False,
                default=str,
            ),
        )
        try:
            return self.client.chat.completions.create(**completion_kwargs)
        except Exception as exc:
            # Reasoning-only models (kimi-k3, o1-mini, ...) reject any
            # sampling value other than their enforced default, which makes
            # the instance-level default temperature/top_p (possibly just a
            # generic 0.2 the operator never configured) fail the whole
            # request. On a 400 that names temperature/top_p, strip the
            # sampling params once and retry so the provider default applies.
            # User-supplied __custom__ params (extra_body) are NOT touched, so
            # a genuinely invalid custom param still surfaces as an error.
            retry_kwargs = self._sampling_fallback_kwargs(exc, completion_kwargs)
            if retry_kwargs is None:
                raise
            logger.warning(
                "event=chat_completion_sampling_fallback model_id=%s error=%s",
                self.model_id,
                exc,
            )
            return self.client.chat.completions.create(**retry_kwargs)

    def _translate_thinking_flag(
        self, extra_body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Translate the enable_thinking flag to the provider's wire format.

        Qwen-family models (vLLM/SGLang deployments and DashScope alike) only
        read it from ``chat_template_kwargs.enable_thinking``; a top-level
        flag is silently ignored there. Other providers (DashScope
        non-Qwen, DeepSeek, SiliconFlow DeepSeek-V3.x) read the top-level
        ``enable_thinking``. An explicit False must therefore be wrapped for
        Qwen and kept top-level for everyone else; an absent flag is passed
        through untouched (model default applies).
        """
        if "enable_thinking" not in extra_body:
            return extra_body
        translated = dict(extra_body)
        thinking = translated.pop("enable_thinking")
        if "qwen" in (self.model_id or "").lower():
            chat_kwargs = translated.get("chat_template_kwargs")
            if isinstance(chat_kwargs, dict):
                translated["chat_template_kwargs"] = {
                    **chat_kwargs, "enable_thinking": thinking,
                }
            else:
                translated["chat_template_kwargs"] = {"enable_thinking": thinking}
        else:
            translated["enable_thinking"] = thinking
        return translated

    def _sampling_fallback_kwargs(
        self, exc: Exception, completion_kwargs: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Sampling-param retry plan for a provider 400, or None to re-raise.

        The retry plan is only built when the error is a 400-class rejection
        that names temperature/top_p AND the request actually carried those
        params. Anything else (auth, quota, custom-param validation, ...) is
        returned to the caller untouched.
        """
        error_type = _bad_request_error_type()
        if error_type is None or not isinstance(exc, error_type):
            return None
        message = str(exc).lower()
        if "temperature" not in message and "top_p" not in message:
            return None
        if "temperature" not in completion_kwargs and "top_p" not in completion_kwargs:
            return None
        return {
            k: v
            for k, v in completion_kwargs.items()
            if k not in ("temperature", "top_p")
        }

    @staticmethod
    def _verify_w1_w2_consistency(
        *,
        budget_snapshot: ContextBudgetSnapshot,
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
            raise ContextBudgetCapacityMismatch(
                field="w1_fingerprint",
                expected=w1_fingerprint,
                actual=budget_snapshot.w1_fingerprint,
            )
        if provider and provider != budget_snapshot.provider:
            raise ContextBudgetCapacityMismatch(
                field="provider",
                expected=provider,
                actual=budget_snapshot.provider,
            )
        if model_name and model_name != budget_snapshot.model_name:
            raise ContextBudgetCapacityMismatch(
                field="model_name",
                expected=model_name,
                actual=budget_snapshot.model_name,
            )

    @staticmethod
    def _coerce_context_budget_snapshot(
        snapshot: Optional[ContextBudgetSnapshot | Dict[str, Any]],
    ) -> Optional[ContextBudgetSnapshot]:
        if snapshot is None:
            return None
        if not isinstance(snapshot, (ContextBudgetSnapshot, dict)):
            raise TypeError(
                "context_budget_snapshot must be a ContextBudgetSnapshot or dict"
            )
        return parse_context_budget_snapshot(snapshot)

    @classmethod
    def _context_budget_trace_attributes(
        cls,
        snapshot: Optional[ContextBudgetSnapshot | Dict[str, Any]],
    ) -> Dict[str, Any]:
        snapshot = cls._coerce_context_budget_snapshot(snapshot)
        if snapshot is None:
            return {}
        return {
            "w2.budget_fingerprint": snapshot.fingerprint,
            "w2.w1_fingerprint": snapshot.w1_fingerprint,
            "w2.requested_output_tokens": snapshot.requested_output_tokens,
            "w2.output_reserve_source": snapshot.output_reserve_source,
            "context.effective_input_limit_tokens": snapshot.effective_input_limit_tokens,
            "context.compaction_trigger_threshold_tokens": (
                snapshot.compaction_trigger_threshold_tokens
            ),
            "context.compaction_target_tokens": snapshot.compaction_target_tokens,
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

            # Directly send a short chat request to test the connection.
            # Sampling params (temperature / top_p) are intentionally NOT
            # sent: reasoning-only models (kimi-k3, DeepSeek-R1 family)
            # reject any value other than their fixed default, and the model
            # instance may carry a generic default (0.2) the operator never
            # configured. The probe validates connectivity and custom params
            # (extra_body incl. __custom__) still surface as a 400 here.
            completion_kwargs = self._prepare_completion_kwargs(
                messages=test_message,
                model=self.model_id,
                max_tokens=5,
            )
            if self.extra_body:
                completion_kwargs["extra_body"] = self.extra_body

            # Offload the blocking SDK call to a thread pool to avoid blocking the event loop
            await run_blocking(
                "openai-llm-connectivity",
                self.client.chat.completions.create,
                stream=False,
                **completion_kwargs,
            )

            # If no exception is raised, the connection is successful
            return True
        except Exception as e:
            logging.error(f"Connection test failed: {str(e)}")
            return False
