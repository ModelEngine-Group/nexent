import threading

import pytest
from nexent.core.models.model_concurrency import (
    ModelConcurrencyExceeded,
    ModelConcurrencyLimiter,
)
from nexent.core.models.retry import get_retry_after_seconds


def test_ut_sdk_tlm_028_same_model_key_has_hard_concurrency_limit():
    limiter = ModelConcurrencyLimiter()
    stop_event = threading.Event()
    key = ("tenant-1", "openai", "model-1")
    first = limiter.acquire(key, 1, 1, stop_event)

    with pytest.raises(ModelConcurrencyExceeded):
        limiter.acquire(key, 1, 0.02, stop_event)

    first.release()
    second = limiter.acquire(key, 1, 1, stop_event)
    second.release()


def test_ut_sdk_tlm_028_cancelled_wait_does_not_acquire_permit():
    limiter = ModelConcurrencyLimiter()
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(RuntimeError, match="cancelled"):
        limiter.acquire(("tenant-1", "openai", "model-1"), 1, 1, stop_event)


def test_ut_sdk_tlm_028_retry_after_header_is_parsed():
    response = type("Response", (), {"headers": {"Retry-After": "2.5"}})()
    error = type("RateLimitError", (Exception,), {"response": response})()

    assert get_retry_after_seconds(error) == 2.5
