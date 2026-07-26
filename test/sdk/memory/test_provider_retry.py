"""Tests for provider retry logic."""

from unittest.mock import AsyncMock

import pytest

from nexent.memory.models import (
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
)
from nexent.memory.providers.retry import (
    DegradableProviderError,
    NonRetryableProviderError,
    RetryConfig,
    RetryableProviderError,
    _extract_provider_error,
    classify_error,
    execute_with_retry,
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

    def test_calculate_backoff_applies_jitter(self, mocker):
        mocker.patch("nexent.memory.providers.retry.random.random", return_value=0.25)
        config = RetryConfig(backoff_base_seconds=4.0, jitter=True)

        assert config.calculate_backoff(1) == pytest.approx(3.0)

    def test_exception_wrappers_preserve_error_data(self):
        error = ProviderError(
            code=ProviderErrorCode.TIMEOUT,
            message="temporary",
            severity=ProviderErrorSeverity.RETRYABLE,
        )

        retryable = RetryableProviderError("retry", error)
        degradable = DegradableProviderError("degrade", error, removable_units=["unit-1"])
        non_retryable = NonRetryableProviderError("stop", error)

        assert str(retryable) == "retry"
        assert retryable.error is error
        assert degradable.error is error
        assert degradable.removable_units == ["unit-1"]
        assert non_retryable.error is error

    @pytest.mark.parametrize(
        "code",
        [
            ProviderErrorCode.PARTIAL_ACCEPTANCE,
            ProviderErrorCode.INVALID_PAYLOAD,
            ProviderErrorCode.SCHEMA_MISMATCH,
        ],
    )
    def test_classify_error_covers_remaining_known_codes(self, code):
        error = ProviderError(
            code=code,
            message="provider response",
            severity=ProviderErrorSeverity.RETRYABLE,
        )

        expected = (
            ProviderErrorSeverity.DEGRADABLE
            if code == ProviderErrorCode.PARTIAL_ACCEPTANCE
            else ProviderErrorSeverity.NON_RETRYABLE
        )
        assert classify_error(error) == expected

    def test_provider_error_code_unknown_is_retryable(self):
        error = ProviderError(
            code=ProviderErrorCode.UNKNOWN,
            message="unclassified provider failure",
            severity=ProviderErrorSeverity.RETRYABLE,
        )

        assert classify_error(error) == ProviderErrorSeverity.RETRYABLE

    def test_classify_error_defaults_unknown_codes_to_retryable(self):
        class UnknownCode:
            pass

        error = type("UnknownProviderError", (), {"code": UnknownCode()})()

        assert classify_error(error) == ProviderErrorSeverity.RETRYABLE

    def test_extract_provider_error_supports_all_wrapper_types(self):
        error = ProviderError(
            code=ProviderErrorCode.PROVIDER_ERROR,
            message="server error",
            severity=ProviderErrorSeverity.RETRYABLE,
        )

        assert _extract_provider_error(error) is error
        assert _extract_provider_error(RetryableProviderError("retry", error)) is error
        assert _extract_provider_error(NonRetryableProviderError("stop", error)) is error
        assert _extract_provider_error(DegradableProviderError("degrade", error)) is error
        assert _extract_provider_error(RuntimeError("unrelated")) is None

    @pytest.mark.asyncio
    async def test_retries_transient_failure_then_returns_result(self, mocker):
        sleep = mocker.patch("nexent.memory.providers.retry.asyncio.sleep", new_callable=AsyncMock)
        operation = AsyncMock(side_effect=[RuntimeError("temporary"), "success"])
        config = RetryConfig(max_attempts=3, backoff_base_seconds=0.0, jitter=False)

        result = await execute_with_retry(operation, config, "lookup")

        assert result == "success"
        assert operation.await_count == 2
        sleep.assert_awaited_once_with(0.0)

    @pytest.mark.asyncio
    async def test_exhausted_retry_raises_fallback_error(self, mocker):
        sleep = mocker.patch("nexent.memory.providers.retry.asyncio.sleep", new_callable=AsyncMock)
        operation = AsyncMock(side_effect=RuntimeError("temporary"))
        config = RetryConfig(max_attempts=2, backoff_base_seconds=0.0, jitter=False)

        with pytest.raises(RetryableProviderError) as exc_info:
            await execute_with_retry(operation, config, "lookup")

        assert exc_info.value.error.code == ProviderErrorCode.UNKNOWN
        assert exc_info.value.error.message == "Max retry attempts exceeded"
        assert operation.await_count == 2
        sleep.assert_awaited_once_with(0.0)

    @pytest.mark.asyncio
    async def test_exhausted_retry_preserves_extracted_provider_error(self, mocker):
        error = ProviderError(
            code=ProviderErrorCode.TIMEOUT,
            message="timed out",
            severity=ProviderErrorSeverity.RETRYABLE,
        )
        mocker.patch("nexent.memory.providers.retry._extract_provider_error", return_value=error)
        mocker.patch("nexent.memory.providers.retry.asyncio.sleep", new_callable=AsyncMock)
        operation = AsyncMock(side_effect=RuntimeError("temporary"))
        config = RetryConfig(max_attempts=1, jitter=False)

        with pytest.raises(RetryableProviderError) as exc_info:
            await execute_with_retry(operation, config, "lookup")

        assert exc_info.value.error is error

    @pytest.mark.asyncio
    async def test_extracted_non_retryable_error_is_wrapped(self, mocker):
        error = ProviderError(
            code=ProviderErrorCode.FORBIDDEN,
            message="forbidden",
            severity=ProviderErrorSeverity.NON_RETRYABLE,
        )
        mocker.patch("nexent.memory.providers.retry._extract_provider_error", return_value=error)
        operation = AsyncMock(side_effect=RuntimeError("provider rejected request"))
        config = RetryConfig(max_attempts=3)

        with pytest.raises(NonRetryableProviderError) as exc_info:
            await execute_with_retry(operation, config, "lookup")

        assert exc_info.value.error is error
        assert str(exc_info.value) == "lookup failed with non-retryable error"
        assert operation.await_count == 1

    @pytest.mark.asyncio
    async def test_zero_attempt_config_uses_default_retryable_error(self):
        operation = AsyncMock()

        with pytest.raises(RetryableProviderError) as exc_info:
            await execute_with_retry(operation, RetryConfig(max_attempts=0), "lookup")

        operation.assert_not_awaited()
        assert exc_info.value.error.code == ProviderErrorCode.UNKNOWN
