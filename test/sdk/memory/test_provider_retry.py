"""Tests for provider retry logic."""

import pytest
import asyncio

from nexent.memory.providers.retry import (
    RetryConfig,
    RetryableProviderError,
    DegradableProviderError,
    NonRetryableProviderError,
    classify_error,
    execute_with_retry,
)
from nexent.memory.models import (
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
)


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_values(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.backoff_base_seconds == 1.0
        assert config.max_backoff_seconds == 30.0
        assert config.jitter is True

    def test_custom_values(self):
        config = RetryConfig(
            max_attempts=5,
            backoff_base_seconds=2.0,
            max_backoff_seconds=60.0,
            jitter=False,
        )
        assert config.max_attempts == 5
        assert config.backoff_base_seconds == 2.0

    def test_calculate_backoff(self):
        config = RetryConfig(backoff_base_seconds=1.0, max_backoff_seconds=30.0, jitter=False)
        # Attempt 1: 1 * 2^0 = 1
        assert config.calculate_backoff(1) == 1.0
        # Attempt 2: 1 * 2^1 = 2
        assert config.calculate_backoff(2) == 2.0
        # Attempt 3: 1 * 2^2 = 4
        assert config.calculate_backoff(3) == 4.0

    def test_calculate_backoff_with_max(self):
        config = RetryConfig(backoff_base_seconds=10.0, max_backoff_seconds=15.0, jitter=False)
        # Attempt 4: 10 * 2^3 = 80, but capped at 15
        assert config.calculate_backoff(4) == 15.0


class TestClassifyError:
    """Tests for classify_error function."""

    def test_timeout_is_retryable(self):
        error = ProviderError(
            code=ProviderErrorCode.TIMEOUT,
            message="timeout",
            severity=ProviderErrorSeverity.RETRYABLE,
        )
        assert classify_error(error) == ProviderErrorSeverity.RETRYABLE

    def test_rate_limited_is_retryable(self):
        error = ProviderError(
            code=ProviderErrorCode.RATE_LIMITED,
            message="rate limited",
            severity=ProviderErrorSeverity.RETRYABLE,
        )
        assert classify_error(error) == ProviderErrorSeverity.RETRYABLE

    def test_provider_error_is_retryable(self):
        error = ProviderError(
            code=ProviderErrorCode.PROVIDER_ERROR,
            message="server error",
            severity=ProviderErrorSeverity.RETRYABLE,
        )
        assert classify_error(error) == ProviderErrorSeverity.RETRYABLE

    def test_unsupported_unit_type_is_degradable(self):
        error = ProviderError(
            code=ProviderErrorCode.UNSUPPORTED_UNIT_TYPE,
            message="unsupported",
            severity=ProviderErrorSeverity.DEGRADABLE,
        )
        assert classify_error(error) == ProviderErrorSeverity.DEGRADABLE

    def test_unauthorized_is_non_retryable(self):
        error = ProviderError(
            code=ProviderErrorCode.UNAUTHORIZED,
            message="unauthorized",
            severity=ProviderErrorSeverity.NON_RETRYABLE,
        )
        assert classify_error(error) == ProviderErrorSeverity.NON_RETRYABLE

    def test_forbidden_is_non_retryable(self):
        error = ProviderError(
            code=ProviderErrorCode.FORBIDDEN,
            message="forbidden",
            severity=ProviderErrorSeverity.NON_RETRYABLE,
        )
        assert classify_error(error) == ProviderErrorSeverity.NON_RETRYABLE


class TestExecuteWithRetry:
    """Tests for execute_with_retry function."""

    @pytest.mark.asyncio
    async def test_successful_operation(self):
        config = RetryConfig(max_attempts=3)
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await execute_with_retry(operation, config, "test")
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        config = RetryConfig(max_attempts=3)
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            error = ProviderError(
                code=ProviderErrorCode.UNAUTHORIZED,
                message="unauthorized",
                severity=ProviderErrorSeverity.NON_RETRYABLE,
            )
            raise NonRetryableProviderError("failed", error)

        with pytest.raises(NonRetryableProviderError):
            await execute_with_retry(operation, config, "test")
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_degradable_error_propagates(self):
        config = RetryConfig(max_attempts=3)
        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            error = ProviderError(
                code=ProviderErrorCode.UNSUPPORTED_UNIT_TYPE,
                message="unsupported",
                severity=ProviderErrorSeverity.DEGRADABLE,
            )
            raise DegradableProviderError("degraded", error)

        with pytest.raises(DegradableProviderError):
            await execute_with_retry(operation, config, "test")
        assert call_count == 1
