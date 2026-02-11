"""
Shared HTTP Client Manager for connection pooling and lifecycle management.

This module provides a singleton HTTP client manager that enables efficient
connection pooling across multiple services (DataMate, Dify, etc.) to avoid
socket exhaustion and port conflicts on Windows systems.

    Usage:
    from nexent.utils.http_client_manager import http_client_manager

    # Get the shared sync client (configurable per base_url)
    client = http_client_manager.get_sync_client(
        base_url="https://api.example.com",
        timeout=30.0,
        verify_ssl=True
    )

    # Different configs for same base_url create separate clients
    client2 = http_client_manager.get_sync_client(
        base_url="https://api.example.com",
        timeout=60.0,  # Different timeout = separate client
        verify_ssl=False  # Different SSL setting = separate client
    )

    # Make requests using the shared client
    response = client.get("/api/endpoint")

    # Use as context manager for automatic cleanup (recommended)
    with http_client_manager as manager:
        client = manager.get_sync_client(base_url="https://api.example.com")
        response = client.get("/api/endpoint")
    # All HTTP clients are automatically closed when exiting the context

    # Manual shutdown when not using context manager
    # http_client_manager.shutdown()
"""
import logging
import threading
from contextlib import contextmanager
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

import httpx
from httpx import Limits

logger = logging.getLogger("http_client_manager")


@dataclass
class ClientConfig:
    """Configuration for an HTTP client."""
    base_url: str
    timeout: float = 30.0
    verify_ssl: bool = True
    limits: Limits = field(default_factory=lambda: Limits(
        max_connections=100,
        max_keepalive_connections=20
    ))


class HttpClientManager:
    """
    Singleton HTTP client manager for connection pooling and lifecycle management.

    This manager maintains a registry of HTTP clients for different base URLs,
    reusing connections across requests to avoid socket exhaustion and port conflicts.

    Features:
    - Singleton pattern: single instance across the entire application
    - Connection pooling: reuse connections for the same base URL
    - Thread-safe: uses locks for thread-safe client access
    - Lazy initialization: clients are created on-demand
    - Graceful shutdown: properly close all clients on shutdown
    """

    _instance: Optional['HttpClientManager'] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> 'HttpClientManager':
        """Ensure singleton pattern with thread-safe initialization."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the HTTP client manager if not already initialized."""
        if self._initialized:
            return

        self._clients: Dict[str, httpx.Client] = {}
        self._async_clients: Dict[str, httpx.AsyncClient] = {}
        self._configs: Dict[str, ClientConfig] = {}
        self._lock = threading.Lock()
        self._initialized = True
        logger.info("HttpClientManager initialized (singleton)")

    def __enter__(self) -> 'HttpClientManager':
        """
        Support context manager protocol for automatic resource cleanup.

        Usage:
            with http_client_manager as manager:
                client = manager.get_sync_client(base_url="https://api.example.com")
                response = client.get("/api/endpoint")
            # All HTTP clients are automatically closed when exiting the context

        Returns:
            HttpClientManager: The singleton instance itself
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit context manager and close all HTTP clients.

        This method is automatically called when exiting the with statement,
        ensuring all HTTP connections are properly closed regardless of
        whether an exception occurred.

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)
        """
        self.shutdown()

    def _get_client_key(self, base_url: str, timeout: float, verify_ssl: bool) -> str:
        """
        Generate a unique key for client registry based on URL, timeout, and SSL setting.

        Different configurations (timeout, verify_ssl) for the same base_url
        will create separate client instances to ensure correct behavior.
        """
        return f"{base_url}|{timeout}|{verify_ssl}"

    def get_sync_client(self, base_url: str, timeout: float = 30.0,
                        verify_ssl: bool = True) -> httpx.Client:
        """
        Get or create a synchronous HTTP client for the given configuration.

        Different timeout or verify_ssl settings for the same base_url will
        create separate client instances.

        Args:
            base_url: Base URL for the HTTP client
            timeout: Request timeout in seconds (default: 30.0)
            verify_ssl: Whether to verify SSL certificates (default: True)

        Returns:
            httpx.Client instance configured for the given parameters
        """
        key = self._get_client_key(base_url, timeout, verify_ssl)

        with self._lock:
            if key not in self._clients:
                logger.info(
                    f"Creating sync HTTP client for: {base_url} (timeout={timeout}, verify_ssl={verify_ssl})")
                self._configs[key] = ClientConfig(
                    base_url=base_url,
                    timeout=timeout,
                    verify_ssl=verify_ssl
                )
                self._clients[key] = httpx.Client(
                    timeout=timeout,
                    verify=verify_ssl,
                    limits=Limits(
                        max_connections=100,
                        max_keepalive_connections=20
                    )
                )
                logger.info(f"Sync HTTP client created for {base_url}")

            return self._clients[key]

    def get_async_client(self, base_url: str, timeout: float = 30.0,
                         verify_ssl: bool = True) -> httpx.AsyncClient:
        """
        Get or create an asynchronous HTTP client for the given configuration.

        Different timeout or verify_ssl settings for the same base_url will
        create separate client instances.

        Args:
            base_url: Base URL for the HTTP client
            timeout: Request timeout in seconds (default: 30.0)
            verify_ssl: Whether to verify SSL certificates (default: True)

        Returns:
            httpx.AsyncClient instance configured for the given parameters
        """
        key = self._get_client_key(base_url, timeout, verify_ssl)

        with self._lock:
            if key not in self._async_clients:
                logger.info(
                    f"Creating async HTTP client for: {base_url} (timeout={timeout}, verify_ssl={verify_ssl})")
                self._configs[key] = ClientConfig(
                    base_url=base_url,
                    timeout=timeout,
                    verify_ssl=verify_ssl
                )
                self._async_clients[key] = httpx.AsyncClient(
                    timeout=timeout,
                    verify=verify_ssl,
                    limits=Limits(
                        max_connections=100,
                        max_keepalive_connections=20
                    )
                )
                logger.info(f"Async HTTP client created for {base_url}")

            return self._async_clients[key]

    def get_client_config(self, base_url: str, timeout: float = 30.0,
                          verify_ssl: bool = True) -> Optional[ClientConfig]:
        """Get the configuration for a specific client."""
        key = self._get_client_key(base_url, timeout, verify_ssl)
        return self._configs.get(key)

    def close_client(self, base_url: str, timeout: float = 30.0,
                     verify_ssl: bool = True) -> bool:
        """
        Close and remove a specific HTTP client.

        Args:
            base_url: Base URL of the client to close
            timeout: Timeout setting of the client
            verify_ssl: SSL verification setting of the client

        Returns:
            True if client was found and closed, False otherwise
        """
        key = self._get_client_key(base_url, timeout, verify_ssl)

        with self._lock:
            if key in self._clients:
                try:
                    self._clients[key].close()
                    del self._clients[key]
                    logger.info(f"Closed sync HTTP client: {base_url}")
                    return True
                except Exception as e:
                    logger.error(f"Error closing sync client: {e}")
                    return False
            return False

    async def close_async_client(self, base_url: str, timeout: float = 30.0,
                                 verify_ssl: bool = True) -> bool:
        """
        Close and remove a specific async HTTP client.

        Args:
            base_url: Base URL of the client to close
            timeout: Timeout setting of the client
            verify_ssl: SSL verification setting of the client

        Returns:
            True if client was found and closed, False otherwise
        """
        key = self._get_client_key(base_url, timeout, verify_ssl)

        with self._lock:
            if key in self._async_clients:
                try:
                    await self._async_clients[key].aclose()
                    del self._async_clients[key]
                    logger.info(f"Closed async HTTP client: {base_url}")
                    return True
                except Exception as e:
                    logger.error(f"Error closing async client: {e}")
                    return False
            return False

    def shutdown(self) -> None:
        """
        Gracefully shutdown all HTTP clients.

        This method should be called when the application is shutting down
        to properly release all resources and close all connections.
        """
        logger.info("Shutting down HttpClientManager...")

        with self._lock:
            # Close all sync clients
            for key, client in list(self._clients.items()):
                try:
                    base_url = self._configs.get(
                        key, ClientConfig(base_url=key)).base_url
                    client.close()
                    logger.info(f"Closed sync HTTP client: {base_url}")
                except Exception as e:
                    logger.error(f"Error closing sync client: {e}")
            self._clients.clear()

            # Note: Async clients should be closed using aclose()
            # They remain in the dict for now as we can't await in sync context
            if self._async_clients:
                logger.warning(
                    f"There are {len(self._async_clients)} async clients still open. "
                    "They should be closed using close_all_async_clients()"
                )

            self._configs.clear()
            logger.info("HttpClientManager shutdown complete")

    async def shutdown_async(self) -> None:
        """
        Gracefully shutdown all HTTP clients (async version).

        This method properly closes both sync and async clients.
        """
        logger.info("Shutting down HttpClientManager (async)...")

        with self._lock:
            # Close all sync clients
            for key, client in list(self._clients.items()):
                try:
                    base_url = self._configs.get(
                        key, ClientConfig(base_url=key)).base_url
                    client.close()
                    logger.info(f"Closed sync HTTP client: {base_url}")
                except Exception as e:
                    logger.error(f"Error closing sync client: {e}")
            self._clients.clear()

            # Close all async clients
            for key, client in list(self._async_clients.items()):
                try:
                    base_url = self._configs.get(
                        key, ClientConfig(base_url=key)).base_url
                    await client.aclose()
                    logger.info(f"Closed async HTTP client: {base_url}")
                except Exception as e:
                    logger.error(f"Error closing async client: {e}")
            self._async_clients.clear()
            self._configs.clear()

            logger.info("HttpClientManager shutdown complete (async)")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the HTTP client manager.

        Returns:
            Dictionary containing client statistics
        """
        with self._lock:
            return {
                "sync_clients_count": len(self._clients),
                "async_clients_count": len(self._async_clients),
                "configs_count": len(self._configs),
                "clients": [
                    {
                        "base_url": config.base_url,
                        "verify_ssl": config.verify_ssl,
                        "timeout": config.timeout,
                        "is_async": key in self._async_clients
                    }
                    for key, config in self._configs.items()
                ]
            }


# Global singleton instance
http_client_manager = HttpClientManager()
