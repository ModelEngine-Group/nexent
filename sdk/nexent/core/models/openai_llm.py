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
from typing import List, Optional, Dict, Any

from openai.types.chat.chat_completion_message import ChatCompletionMessage
from smolagents import Tool
from smolagents.models import OpenAIServerModel, ChatMessage, MessageRole

from .capacity_budget import (
    CallerMaxTokensOverrideForbidden,
    SafeInputBudgetCapacityMismatch,
    SafeInputBudgetFingerprintMismatch,
    SafeInputBudgetSnapshot,
    compute_w2_fingerprint,
)
from ..utils.observer import MessageObserver, ProcessType
from .prompt_cache import (
    apply_cache_directives,
    cache_directive_advice,
    extract_prompt_cache_usage,
    resolve_prompt_cache_profile,
)

logger = logging.getLogger("openai_llm")


class OpenAIModel(OpenAIServerModel):
    # Public SDK constructor: keep common kwargs explicit and read extension
    # kwargs below to preserve backward-compatible keyword call sites.
    def __init__(self, observer: MessageObserver = MessageObserver, temperature=0.2, top_p=0.95,
ssl_verify=True, model_factory: Optional[str] = None,
                 display_name: Optional[str] = None,
                 extra_body: Optional[Dict[str, Any]] = None,
                 max_output_tokens: Optional[int] = None,
                 max_tokens: Optional[int] = None,
                 safe_input_budget_snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]] = None,
                 timeout_seconds: Optional[float] = None,
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
        self.stop_event = threading.Event()
        self._monitoring = get_monitoring_manager()
        self.model_factory = (model_factory or "").lower()
        self.display_name = display_name
        self.extra_body = extra_body or None
        self.prompt_cache = prompt_cache or None
        self.last_provider_cache_advice = None
        self.last_prompt_cache_usage = None
        self.last_cached_input_token_count = 0
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
                 **kwargs, ) -> ChatMessage:
        _monitoring_operation.set("chat_completion")

        if _token_tracker is None:
            trusted_budget_snapshot = (
                safe_input_budget_snapshot or self.safe_input_budget_snapshot
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
                    **kwargs,
                )

        token_tracker = _token_tracker or self._monitoring.create_token_tracker(
            self.model_id)

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

        completion_kwargs = self._prepare_completion_kwargs(
            messages=normalized_messages, stop_sequences=stop_sequences,
            response_format=response_format, tools_to_call_from=tools_to_call_from, model=self.model_id,
            custom_role_conversions=self.custom_role_conversions, convert_images_to_image_urls=True,
            temperature=self.temperature, top_p=self.top_p,
            flatten_messages_as_text=self.model_factory == "modelengine", **kwargs,
        )

        completion_kwargs["stream_options"] = {"include_usage": True}

        # Provider-specific extras (e.g. Qwen3 chat_template_kwargs) - only
        # set when the caller actually supplied something so default OpenAI
        # behaviour is unchanged for everyone else.
        if self.extra_body:
            completion_kwargs["extra_body"] = self.extra_body

        trusted_budget_snapshot = (
            safe_input_budget_snapshot or self.safe_input_budget_snapshot
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

        current_request = self._dispatch_chat_completion(
            safe_input_budget_snapshot=trusted_budget_snapshot,
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

        chunk_list = []
        token_join = []
        role = None

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
                    continue

                if not chunk.choices:
                    chunk_list.append(chunk)
                    continue

                new_token = chunk.choices[0].delta.content
                reasoning_content = getattr(
                    chunk.choices[0].delta, 'reasoning_content', None)

                # Handle reasoning_content if it exists and is not null
                if reasoning_content is not None:
                    self.observer.add_model_reasoning_content(
                        reasoning_content)
                    if token_tracker and not first_token_received:
                        token_tracker.record_first_token()
                        first_token_received = True

                if new_token is not None:
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
                    raise RuntimeError(
                        "Model is interrupted by stop event")

            # Send end marker
            self.observer.flush_remaining_tokens()
            model_output = "".join(token_join)

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

            if token_tracker:
                total_duration = time.time() - stream_start_time
                self._monitoring.set_openinference_output(model_output)
                self._monitoring.add_span_event("completion_finished", {
                    "total_duration": total_duration,
                    "output_length": len(model_output),
                    "chunk_count": len(chunk_list)
                })

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

            if "context_length_exceeded" in str(e):
                raise ValueError(f"Token limit exceeded: {str(e)}")
            raise e

    def _dispatch_chat_completion(
        self,
        *,
        safe_input_budget_snapshot: Optional[SafeInputBudgetSnapshot | Dict[str, Any]] = None,
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
        snapshot = self._coerce_safe_input_budget_snapshot(safe_input_budget_snapshot)
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
        return self.client.chat.completions.create(**completion_kwargs)

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
