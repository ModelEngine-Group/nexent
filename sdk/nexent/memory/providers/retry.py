"""Retry and degradation handling for external memory providers.

This module implements the retry strategy defined in the memory design document:
- Retryable errors (timeout, rate_limited, provider_error, unknown): exponential backoff
- Degradable errors (unsupported_unit_type): attempt removal and retry once
- Non-retryable errors (unauthorized, forbidden, invalid_payload, schema_mismatch): fail immediately
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, Optional, TypeVar

from ..models import ProviderError, ProviderErrorCode, ProviderErrorSeverity


logger = logging.getLogger("memory_providers_retry")

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        backoff_base_seconds: float = 1.0,
        max_backoff_seconds: float = 30.0,
        jitter: bool = True,
    ):
        """Initialize retry configuration.

        Args:
            max_attempts: Maximum number of retry attempts.
            backoff_base_seconds: Base value for exponential backoff.
            max_backoff_seconds: Maximum backoff time in seconds.
            jitter: Whether to add random jitter to backoff.
        """
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.jitter = jitter

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time for a given attempt.

        Args:
            attempt: The current attempt number (1-indexed).

        Returns:
            Backoff time in seconds.
        """
        backoff = self.backoff_base_seconds * (2 ** (attempt - 1))
        backoff = min(backoff, self.max_backoff_seconds)
        if self.jitter:
            backoff = backoff * (0.5 + random.random())
        return backoff


class RetryableProviderError(Exception):
    """Error that indicates an operation can be retried."""

    def __init__(self, message: str, error: ProviderError):
        super().__init__(message)
        self.error = error


class DegradableProviderError(Exception):
    """Error that indicates an operation may succeed after degradation."""

    def __init__(self, message: str, error: ProviderError, removable_units: Optional[list] = None):
        super().__init__(message)
        self.error = error
        self.removable_units = removable_units or []


class NonRetryableProviderError(Exception):
    """Error that indicates an operation should not be retried."""

    def __init__(self, message: str, error: ProviderError):
        super().__init__(message)
        self.error = error


def classify_error(error: ProviderError) -> ProviderErrorSeverity:
    """Classify an error by its severity.

    Args:
        error: The provider error to classify.

    Returns:
        The severity level of the error.
    """
    retryable_codes = {
        ProviderErrorCode.TIMEOUT,
        ProviderErrorCode.RATE_LIMITED,
        ProviderErrorCode.PROVIDER_ERROR,
        ProviderErrorCode.UNKNOWN,
    }
    degradable_codes = {
        ProviderErrorCode.UNSUPPORTED_UNIT_TYPE,
        ProviderErrorCode.PARTIAL_ACCEPTANCE,
    }
    non_retryable_codes = {
        ProviderErrorCode.UNAUTHORIZED,
        ProviderErrorCode.FORBIDDEN,
        ProviderErrorCode.INVALID_PAYLOAD,
        ProviderErrorCode.SCHEMA_MISMATCH,
    }

    if error.code in retryable_codes:
        return ProviderErrorSeverity.RETRYABLE
    elif error.code in degradable_codes:
        return ProviderErrorSeverity.DEGRADABLE
    elif error.code in non_retryable_codes:
        return ProviderErrorSeverity.NON_RETRYABLE
    else:
        return ProviderErrorSeverity.UNKNOWN


async def execute_with_retry(
    operation: Callable[[], Any],
    config: RetryConfig,
    operation_name: str = "operation",
) -> Any:
    """Execute an operation with retry logic.

    Args:
        operation: The async operation to execute.
        config: Retry configuration.
        operation_name: Name of the operation for logging.

    Returns:
        Result of the operation.

    Raises:
        NonRetryableProviderError: For non-retryable errors.
        DegradableProviderError: For errors that may succeed after degradation.
        RetryableProviderError: If all retry attempts fail.
    """
    last_error: Optional[ProviderError] = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            return await operation()
        except DegradableProviderError:
            raise
        except NonRetryableProviderError:
            raise
        except Exception as exc:
            error = _extract_provider_error(exc)
            severity = classify_error(error) if error else ProviderErrorSeverity.RETRYABLE

            if severity == ProviderErrorSeverity.NON_RETRYABLE:
                raise NonRetryableProviderError(
                    f"{operation_name} failed with non-retryable error",
                    error or ProviderError(
                        code=ProviderErrorCode.UNKNOWN,
                        message=str(exc),
                        severity=ProviderErrorSeverity.NON_RETRYABLE,
                    ),
                )

            last_error = error
            if attempt < config.max_attempts:
                backoff = config.calculate_backoff(attempt)
                logger.warning(
                    f"{operation_name} failed (attempt {attempt}/{config.max_attempts}), "
                    f"retrying in {backoff:.1f}s: {exc}"
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(
                    f"{operation_name} failed after {config.max_attempts} attempts: {exc}"
                )

    raise RetryableProviderError(
        f"{operation_name} failed after {config.max_attempts} attempts",
        last_error or ProviderError(
            code=ProviderErrorCode.UNKNOWN,
            message="Max retry attempts exceeded",
            severity=ProviderErrorSeverity.RETRYABLE,
        ),
    )


def _extract_provider_error(exc: Exception) -> Optional[ProviderError]:
    """Extract ProviderError from an exception.

    Args:
        exc: The exception to extract from.

    Returns:
        The ProviderError if found, None otherwise.
    """
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, RetryableProviderError):
        return exc.error
    if isinstance(exc, NonRetryableProviderError):
        return exc.error
    if isinstance(exc, DegradableProviderError):
        return exc.error
    return None
