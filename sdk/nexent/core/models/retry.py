"""Exponential backoff retry primitives for model invocations.

This module is intentionally dependency-free (it imports neither the OpenAI
SDK nor any ``nexent`` submodule) so it can be reused by both the SDK model
layer (:class:`nexent.core.models.openai_llm.OpenAIModel`) and the backend
direct LLM client path (:func:`utils.llm_utils.call_llm_for_system_prompt`)
without coupling ``core.models`` to ``memory`` or to any specific provider SDK.

Design notes (decision record):
* Retry parameters are **global constants only** for the initial rollout.
  There is no per-model / DB-driven configuration yet.
* Only *transient* errors are retried (rate limiting, server-side 5xx,
  network / connection / timeout failures). Authentication errors, not-found,
  invalid payloads and context-length errors are treated as non-retryable so
  we fail fast instead of burning backoff on hopeless requests.
* Empty responses (stream completed without user-visible content) are handled
  by the caller (the agent step loop / summary truncation), **not** here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class ModelRetryConfig:
    """Configuration for exponential backoff retries on transient model errors.

    Args:
        max_attempts: Maximum number of invocations *including* the first
            attempt. Must be >= 1. The number of *retries* is
            ``max_attempts - 1``.
        backoff_base_seconds: Delay for the first retry. Each subsequent retry
            doubles it (1s, 2s, 4s, ...).
        max_backoff_seconds: Upper bound for a single backoff delay.
        jitter: When True, multiply the computed delay by a random factor in
            ``[0.5, 1.5]`` to avoid synchronised (thundering-herd) retries
            across many concurrent clients.
    """

    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    jitter: bool = True

    def calculate_backoff(self, attempt: int) -> float:
        """Return the sleep duration (seconds) before the ``attempt``-th retry.

        ``attempt`` is 1-based and must be >= 1. The first retry waits
        ``backoff_base_seconds``; each subsequent retry doubles it, capped at
        ``max_backoff_seconds``.
        """
        raw = self.backoff_base_seconds * (2 ** (attempt - 1))
        backoff = min(raw, self.max_backoff_seconds)
        if self.jitter:
            backoff *= random.uniform(0.5, 1.5)
        return backoff


# Process-wide default. Decision: retry parameters are global constants only
# (not configurable per model / via DB) for the initial rollout.
DEFAULT_MODEL_RETRY = ModelRetryConfig()


def classify_model_error(exc: BaseException) -> str:
    """Classify an exception raised by a model invocation.

    Returns ``"retryable"`` for transient errors (rate limiting, server-side
    5xx, network / connection / timeout failures) and ``"non_retryable"`` for
    everything else (auth errors, not-found, invalid payloads, context-length,
    and any unrecognised error -- failing fast is safer than blindly retrying).

    The check prefers an explicit ``status_code`` attribute (the OpenAI SDK
    exposes this on its error types) and falls back to substring matching on
    the error message so it also covers raw httpx / aiohttp network failures
    that surface as generic exceptions.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status == 429 or 500 <= status < 600:
            return "retryable"
        return "non_retryable"

    msg = str(exc).lower()
    non_retryable_markers = (
        "401", "unauthorized", "403", "forbidden",
        "404", "not found", "400", "bad request", "422", "unprocessable",
        "invalid", "api key", "authentication", "context_length",
        "context length", "token limit",
    )
    for marker in non_retryable_markers:
        if marker in msg:
            return "non_retryable"

    retryable_markers = (
        "429", "rate limit", "rate_limit",
        "500", "502", "503", "504",
        "connection", "connecterror", "connect error",
        "timeout", "timed out", "time out", "readtimeout", "read timeout",
        "refused", "reset by peer", "broken pipe", "remote protocol",
        "aiohttp", "client error", "server error", "service unavailable",
        "temporarily unavailable", "try again", "gateway timeout", "bad gateway",
        "connection reset", "econnrefused", "etimedout",
    )
    for marker in retryable_markers:
        if marker in msg:
            return "retryable"

    # Unknown error: prefer failing fast over retrying blindly.
    return "non_retryable"
