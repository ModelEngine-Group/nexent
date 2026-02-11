import logging
from abc import ABC, abstractmethod
from typing import Dict, List

import aiohttp

logger = logging.getLogger("model_provider")


# =============================================================================
# Provider Error Handling Utilities
# =============================================================================


def _create_error_response(error_code: str, message: str, http_code: int = None) -> List[Dict]:
    """
    Create a standardized error response for provider API failures.

    Args:
        error_code: Machine-readable error code (e.g., 'authentication_failed')
        message: Human-readable error message
        http_code: HTTP status code if available

    Returns:
        List containing a single error dict with standardized format
    """
    error_dict = {"_error": error_code, "_message": message}
    if http_code:
        error_dict["_http_code"] = http_code
    return [error_dict]


def _classify_provider_error(
        provider_name: str,
        status_code: int = None,
        error_message: str = None,
        exception: Exception = None
) -> List[Dict]:
    """
    Classify provider errors and return standardized error response.

    This function centralizes error classification logic for all model providers,
    ensuring consistent error codes and messages across different providers.

    Args:
        provider_name: Name of the provider (for logging and messages)
        status_code: HTTP status code if available
        error_message: Error message from API if available
        exception: Exception object if available

    Returns:
        List containing a single error dict with standardized format
    """
    # Classify by HTTP status code
    if status_code:
        if status_code == 401:
            logger.error(
                f"{provider_name} API authentication failed: Invalid API key")
            return _create_error_response(
                "authentication_failed",
                "Invalid API key or authentication failed",
                status_code
            )
        elif status_code == 403:
            logger.error(
                f"{provider_name} API access forbidden: Insufficient permissions")
            return _create_error_response(
                "access_forbidden",
                "Access forbidden. Please check your permissions",
                status_code
            )
        elif status_code == 404:
            logger.error(
                f"{provider_name} API endpoint not found: URL may be incorrect")
            return _create_error_response(
                "endpoint_not_found",
                "API endpoint not found. Please verify the URL",
                status_code
            )
        elif status_code >= 500:
            logger.error(f"{provider_name} server error: HTTP {status_code}")
            return _create_error_response(
                "server_error",
                f"Server error (HTTP {status_code})",
                status_code
            )
        elif status_code >= 400:
            logger.error(
                f"{provider_name} API error (HTTP {status_code}): {error_message}")
            return _create_error_response(
                "api_error",
                f"API error (HTTP {status_code})",
                status_code
            )

    # Classify by exception type
    if exception:
        # aiohttp exceptions
        if isinstance(exception, aiohttp.ClientConnectorError):
            error_str = str(exception).lower()
            if "certificate" in error_str or "ssl" in error_str:
                logger.error(
                    f"{provider_name} SSL certificate error: {exception}")
                return _create_error_response(
                    "ssl_error",
                    "SSL certificate error. Please check the URL and SSL configuration"
                )
            else:
                logger.error(f"{provider_name} connection failed: {exception}")
                return _create_error_response(
                    "connection_failed",
                    f"Failed to connect to {provider_name}. Please check the URL and network connection"
                )
        elif isinstance(exception, aiohttp.ServerTimeoutError):
            logger.error(f"{provider_name} server timeout: {exception}")
            return _create_error_response(
                "timeout",
                "Connection timed out. Please check the URL and network connection"
            )
        elif isinstance(exception, aiohttp.ServerDisconnectedError):
            logger.error(f"{provider_name} server disconnected: {exception}")
            return _create_error_response(
                "connection_failed",
                f"Connection to {provider_name} was interrupted. Please try again"
            )
        elif isinstance(exception, aiohttp.ContentTypeError):
            logger.error(
                f"{provider_name} invalid response format: {exception}")
            return _create_error_response(
                "invalid_response",
                "Invalid response from provider API"
            )

    # Generic connection error fallback
    error_msg = error_message or str(
        exception) if exception else "Unknown error"
    logger.error(f"{provider_name} error: {error_msg}")
    return _create_error_response(
        "connection_failed",
        f"Failed to connect to {provider_name}. Please check the URL and network connection"
    )


class AbstractModelProvider(ABC):
    """Common interface that all model provider integrations must implement."""

    @abstractmethod
    async def get_models(self, provider_config: Dict) -> List[Dict]:
        """Return a list of models provided by the concrete provider."""
        raise NotImplementedError
