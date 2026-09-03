import logging
import random
import time
from typing import Callable, List, Optional

from consts.const import MESSAGE_ROLE, THINK_END_PATTERN, THINK_START_PATTERN
from consts.error_code import ErrorCode
from consts.exceptions import AppException
from database.model_management_db import get_model_by_model_id
from services.model_gateway_service import get_llm_adapter_from_config
from nexent.monitor import set_monitoring_context, set_monitoring_operation

logger = logging.getLogger("llm_utils")

# Retry configuration for transient LLM errors (rate limits, 5xx, network).
# Decision: global constants only for the initial rollout (not per-model / DB-driven).
_LLM_RETRY_MAX_ATTEMPTS = 6
_LLM_RETRY_BACKOFF_BASE = 2.0
_LLM_RETRY_MAX_BACKOFF = 30.0


def _is_transient_llm_error(exc: Exception) -> bool:
    """Return True for transient errors worth retrying.
    Retries rate-limiting (429), server errors (5xx), and network/timeout
    failures. Authentication, not-found, invalid-payload and context-length
    errors are treated as non-retryable so we fail fast.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or 500 <= status < 600
    msg = str(exc).lower()
    non_retryable = (
        "401", "unauthorized", "403", "forbidden", "404", "not found",
        "400", "bad request", "422", "unprocessable", "invalid",
        "api key", "authentication", "context_length", "context length",
        "token limit",
    )
    if any(m in msg for m in non_retryable):
        return False
    retryable = (
        "429", "rate limit", "rate_limit", "500", "502", "503", "504",
        "connection", "connecterror", "connect error", "timeout",
        "timed out", "time out", "readtimeout", "read timeout", "refused",
        "reset by peer", "broken pipe", "remote protocol", "aiohttp",
        "client error", "server error", "service unavailable",
        "temporarily unavailable", "try again", "gateway timeout",
        "bad gateway", "connection reset", "econnrefused", "etimedout",
    )
    return any(m in msg for m in retryable)


def _process_thinking_tokens(
    new_token: str,
    is_thinking: bool,
    token_join: List[str],
    callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Process tokens to filter out thinking content between <think> and </think> tags.
    Handles cases where providers only send a closing tag or mix reasoning_content.
    """
    # Check for end tag first, as it might appear in the same token as start tag
    if THINK_END_PATTERN in new_token:
        # If we were never in think mode, treat everything accumulated so far as reasoning and clear it
        if not is_thinking:
            token_join.clear()
            if callback:
                callback("")  # clear any previously streamed reasoning content

        # Exit thinking mode and only keep content after </think>
        _, _, after_end = new_token.partition(THINK_END_PATTERN)
        is_thinking = False
        new_token = after_end
        # Continue processing the remaining content in this token

    # Check for start tag (after processing end tag, in case both are in the same token)
    if THINK_START_PATTERN in new_token:
        # Drop any content before <think> and switch to thinking mode
        _, _, after_start = new_token.partition(THINK_START_PATTERN)
        new_token = after_start
        is_thinking = True

    if is_thinking:
        # Still inside thinking content; ignore until we exit
        return True

    if new_token:
        token_join.append(new_token)
        if callback:
            callback("".join(token_join))

    return False


def call_llm_for_system_prompt(
    model_id: int,
    user_prompt: str,
    system_prompt: str,
    callback: Optional[Callable[[str], None]] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """
    Call the LLM to generate a system prompt with optional streaming callbacks.
    """
    llm_model_config = get_model_by_model_id(model_id=model_id, tenant_id=tenant_id)

    display_name = llm_model_config.get("display_name", "") if llm_model_config else ""
    if tenant_id:
        set_monitoring_context(tenant_id=tenant_id)
    set_monitoring_operation("system_prompt_generation",
                             display_name=display_name or None)

    timeout_seconds = llm_model_config.get("timeout_seconds") if llm_model_config else None

    llm = get_llm_adapter_from_config(
        llm_model_config,
        tenant_id,
        temperature=0.3,
        top_p=0.95,
        display_name=display_name or None,
        timeout_seconds=timeout_seconds,
    )
    # The gateway adapter lazily wraps the legacy OpenAIModel; the streaming
    # completion below reaches the wrapped model's client, so build it first.
    llm._build_model()
    messages = [
        {"role": MESSAGE_ROLE["SYSTEM"], "content": system_prompt},
        {"role": MESSAGE_ROLE["USER"], "content": user_prompt},
    ]
    for attempt in range(1, _LLM_RETRY_MAX_ATTEMPTS + 1):
        try:
            completion_kwargs = llm._prepare_completion_kwargs(
                messages=messages,
                model=llm.model_id,
                temperature=0.3,
                top_p=0.95,
            )
            # The evaluator consumes the response as a stream. Remove any
            # construction-time stream value before forcing the call-level
            # streaming mode, otherwise Python receives duplicate keywords.
            completion_kwargs.pop("stream", None)
            current_request = llm.client.chat.completions.create(stream=True, **completion_kwargs)
            token_join: List[str] = []
            is_thinking = False
            reasoning_content_seen = False
            content_tokens_seen = 0
            for chunk in current_request:
                choices = getattr(chunk, "choices", None)
                if choices is None:
                   logger.warning("Received non-standard chunk without choices during prompt generation.")
                   continue
                if not choices:
                   logger.debug("Received empty choices chunk during prompt generation; skipping.")
                   continue

                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    logger.debug("Skipping LLM stream chunk without delta")
                    continue
 
                reasoning_content = getattr(delta, "reasoning_content", None)
                new_token = getattr(delta, "content", None)

                # Note: reasoning_content is separate metadata and doesn't affect content filtering
                # We only filter content based on <think> tags in delta.content
                if reasoning_content:
                    reasoning_content_seen = True
                    logger.debug("Received reasoning_content (metadata only, not filtering content)")

                # Process content token if it exists
                if new_token is not None:
                    content_tokens_seen += 1
                    is_thinking = _process_thinking_tokens(
                        new_token,
                        is_thinking,
                        token_join,
                        callback,
                    )

            result = "".join(token_join)
            if not result and content_tokens_seen > 0:
                logger.warning(
                    "Generated prompt is empty but %d content tokens were processed. "
                    "This suggests all content was filtered out.",
                    content_tokens_seen
                )

            return result
        except Exception as exc:
            if _is_transient_llm_error(exc) and attempt < _LLM_RETRY_MAX_ATTEMPTS:
                backoff = min(
                    _LLM_RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
                    _LLM_RETRY_MAX_BACKOFF,
                ) * random.uniform(0.5, 1.5)
                logger.warning(
                    "call_llm_for_system_prompt attempt %d/%d failed with transient "
                    "error (%s); retrying after %.2fs",
                    attempt, _LLM_RETRY_MAX_ATTEMPTS, str(exc), backoff,
                )
                time.sleep(backoff)
                continue
            logger.exception("Failed to generate prompt from LLM: %s", str(exc))
            # Parse error code from exception message and raise appropriate AppException
            # Use specific error codes for different scenarios
            error_msg = str(exc)
            if "401" in error_msg or "api key" in error_msg.lower() or "unauthorized" in error_msg.lower():
                raise AppException(ErrorCode.MODEL_API_KEY_INVALID)
            elif "403" in error_msg or "forbidden" in error_msg.lower():
                raise AppException(ErrorCode.MODEL_API_KEY_NO_PERMISSION)
            elif "404" in error_msg or "not found" in error_msg.lower():
                raise AppException(ErrorCode.MODEL_NOT_FOUND)
            elif "429" in error_msg or "rate limit" in error_msg.lower():
                raise AppException(ErrorCode.MODEL_RATE_LIMIT_EXCEEDED)
            elif "500" in error_msg or "502" in error_msg or "503" in error_msg or "504" in error_msg:
                raise AppException(ErrorCode.MODEL_SERVICE_UNAVAILABLE)
            elif "connection" in error_msg.lower() or "timeout" in error_msg.lower() or "refused" in error_msg.lower():
                raise AppException(ErrorCode.MODEL_CONNECTION_ERROR)
            else:
                raise AppException(ErrorCode.MODEL_PROMPT_GENERATION_FAILED)


__all__ = ["call_llm_for_system_prompt", "_process_thinking_tokens"]
