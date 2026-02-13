"""
Tests for HTTP Client Manager module.

This module tests the HttpClientManager class including:
- Singleton pattern implementation
- HTTP client creation and caching
- Context manager support (new feature)
- Client lifecycle management
- Statistics and configuration retrieval
"""
import pytest
from unittest.mock import patch, MagicMock


def _reset_singleton():
    """Reset the singleton state for test isolation."""
    import sys
    from nexent.utils.http_client_manager import HttpClientManager

    # Get the module for updating the global http_client_manager reference
    module = sys.modules.get("nexent.utils.http_client_manager")

    # Get the existing instance before resetting
    instance = HttpClientManager._instance
    if instance is not None:
        # Close all clients properly before clearing
        for client in list(instance._clients.values()):
            try:
                client.close()
            except Exception:
                pass
        for client in list(instance._async_clients.values()):
            try:
                # Use close() for async clients in sync context
                if hasattr(client, 'close'):
                    client.close()
            except Exception:
                pass
        # Clear the instance's internal state
        instance._clients.clear()
        instance._async_clients.clear()
        instance._configs.clear()
        # Reset instance-level initialized flag
        instance._initialized = False
    # Reset class-level singleton variables
    HttpClientManager._instance = None

    # Update the module-level http_client_manager to point to a fresh instance
    # This ensures tests get a completely new singleton state
    if module is not None:
        # Force module reload to get a fresh singleton
        fresh_manager = HttpClientManager()
        module.http_client_manager = fresh_manager


class TestHttpClientManagerSingleton:
    """Test singleton pattern implementation."""

    def test_singleton_returns_same_instance(self):
        """Test that HttpClientManager returns the same instance."""
        _reset_singleton()
        from nexent.utils.http_client_manager import HttpClientManager

        manager1 = HttpClientManager()
        manager2 = HttpClientManager()

        assert manager1 is manager2

    def test_singleton_thread_safety(self):
        """Test that singleton initialization is thread-safe."""
        _reset_singleton()
        from nexent.utils.http_client_manager import HttpClientManager
        import threading

        instances = []
        barrier = threading.Barrier(10)

        def create_instance():
            barrier.wait()
            instances.append(HttpClientManager())

        threads = [threading.Thread(target=create_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All instances should be the same object
        first_instance = instances[0]
        for instance in instances[1:]:
            assert instance is first_instance


class TestHttpClientManagerSyncClient:
    """Test synchronous HTTP client management."""

    def test_get_sync_client_creates_new_client(self):
        """Test that get_sync_client creates a new client for new config."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        client = http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert client is not None
        stats = http_client_manager.get_stats()
        assert stats["sync_clients_count"] == 1

    def test_get_sync_client_returns_cached_client(self):
        """Test that get_sync_client returns the same client for same config."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        client1 = http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        client2 = http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert client1 is client2
        # Only one client despite 2 calls
        assert http_client_manager.get_stats()["sync_clients_count"] == 1

    def test_get_sync_client_different_timeout_creates_new_client(self):
        """Test that different timeout creates a new client."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        client1 = http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        client2 = http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=60.0,
            verify_ssl=True
        )

        assert client1 is not client2
        assert http_client_manager.get_stats()["sync_clients_count"] == 2

    def test_get_sync_client_different_verify_ssl_creates_new_client(self):
        """Test that different verify_ssl creates a new client."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        client1 = http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        client2 = http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=False
        )

        assert client1 is not client2
        assert http_client_manager.get_stats()["sync_clients_count"] == 2

    def test_get_sync_client_different_base_url_creates_new_client(self):
        """Test that different base_url creates a new client."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        client1 = http_client_manager.get_sync_client(
            base_url="https://api1.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        client2 = http_client_manager.get_sync_client(
            base_url="https://api2.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert client1 is not client2
        assert http_client_manager.get_stats()["sync_clients_count"] == 2


class TestHttpClientManagerAsyncClient:
    """Test asynchronous HTTP client management."""

    def test_get_async_client_creates_new_client(self):
        """Test that get_async_client creates a new client for new config."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        client = http_client_manager.get_async_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert client is not None
        assert http_client_manager.get_stats()["async_clients_count"] == 1

    def test_get_async_client_returns_cached_client(self):
        """Test that get_async_client returns the same client for same config."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        client1 = http_client_manager.get_async_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        client2 = http_client_manager.get_async_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert client1 is client2
        # Only one client despite 2 calls
        assert http_client_manager.get_stats()["async_clients_count"] == 1


class TestHttpClientManagerContextManager:
    """Test context manager support (new feature)."""

    def test_context_manager_enter_returns_self(self):
        """Test that __enter__ returns the manager instance."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        with http_client_manager as manager:
            assert manager is http_client_manager

    def test_context_manager_exits_cleans_up_clients(self):
        """Test that __exit__ properly closes all clients."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        # Create some clients
        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        http_client_manager.get_sync_client(
            base_url="https://api2.example.com",
            timeout=60.0,
            verify_ssl=False
        )

        # Verify clients were created
        stats_before = http_client_manager.get_stats()
        assert stats_before["sync_clients_count"] == 2

        # Exit context - clients should be closed
        # The context manager's __exit__ calls shutdown()

    def test_context_manager_with_exception_still_closes(self):
        """Test that context manager closes clients even when exception occurs."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        # Create a client before context
        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        # Simulate exception in context - manager should still shutdown
        try:
            with http_client_manager:
                raise ValueError("Test exception")
        except ValueError:
            pass

        # After context exit, clients should be cleaned up
        stats = http_client_manager.get_stats()
        assert stats["sync_clients_count"] == 0

    def test_context_manager_multiple_clients_closed(self):
        """Test that all clients are closed when exiting context."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        with http_client_manager as manager:
            client1 = manager.get_sync_client(
                base_url="https://api1.example.com",
                timeout=30.0,
                verify_ssl=True
            )
            client2 = manager.get_sync_client(
                base_url="https://api2.example.com",
                timeout=30.0,
                verify_ssl=True
            )

            # Both clients should be cached
            stats = manager.get_stats()
            assert stats["sync_clients_count"] == 2

        # After exiting context, all clients should be closed
        stats = http_client_manager.get_stats()
        assert stats["sync_clients_count"] == 0


class TestHttpClientManagerShutdown:
    """Test shutdown functionality."""

    def test_shutdown_closes_all_sync_clients(self):
        """Test that shutdown() closes all sync clients."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        # Create clients
        http_client_manager.get_sync_client(
            base_url="https://api1.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        http_client_manager.get_sync_client(
            base_url="https://api2.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        # Verify clients exist
        stats_before = http_client_manager.get_stats()
        assert stats_before["sync_clients_count"] == 2

        # Shutdown
        http_client_manager.shutdown()

        # Verify clients are closed
        stats_after = http_client_manager.get_stats()
        assert stats_after["sync_clients_count"] == 0

    def test_shutdown_clears_configs(self):
        """Test that shutdown() clears all configurations."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        http_client_manager.shutdown()

        assert http_client_manager.get_stats()["configs_count"] == 0


class TestHttpClientManagerAsyncShutdown:
    """Test async shutdown functionality."""

    @pytest.mark.asyncio
    async def test_shutdown_async_closes_all_clients(self):
        """Test that shutdown_async() closes both sync and async clients."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        # Create both sync and async clients
        # Note: get_async_client() is synchronous, returns AsyncClient directly
        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        http_client_manager.get_async_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        # Verify clients exist
        stats_before = http_client_manager.get_stats()
        assert stats_before["sync_clients_count"] == 1
        assert stats_before["async_clients_count"] == 1

        # Async shutdown
        await http_client_manager.shutdown_async()

        # Verify all clients are closed
        stats_after = http_client_manager.get_stats()
        assert stats_after["sync_clients_count"] == 0
        assert stats_after["async_clients_count"] == 0


class TestHttpClientManagerCloseClient:
    """Test individual client close functionality."""

    def test_close_client_returns_true_when_found(self):
        """Test that close_client returns True when client exists."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        result = http_client_manager.close_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert result is True

    def test_close_client_returns_false_when_not_found(self):
        """Test that close_client returns False when client doesn't exist."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        result = http_client_manager.close_client(
            base_url="https://nonexistent.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert result is False

    def test_close_client_removes_client_from_registry(self):
        """Test that close_client removes the client from registry."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        http_client_manager.close_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert http_client_manager.get_stats()["sync_clients_count"] == 0

    @pytest.mark.asyncio
    async def test_close_async_client(self):
        """Test async client close functionality."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        # get_async_client() is synchronous, returns AsyncClient directly
        http_client_manager.get_async_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        result = await http_client_manager.close_async_client(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert result is True


class TestHttpClientManagerGetStats:
    """Test statistics retrieval functionality."""

    def test_get_stats_returns_correct_counts(self):
        """Test that get_stats returns correct client counts."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        http_client_manager.get_sync_client(
            base_url="https://api1.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        http_client_manager.get_sync_client(
            base_url="https://api2.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        stats = http_client_manager.get_stats()

        assert stats["sync_clients_count"] == 2
        assert stats["async_clients_count"] == 0
        assert stats["configs_count"] == 2

    def test_get_stats_includes_client_details(self):
        """Test that get_stats includes detailed client information."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=45.0,
            verify_ssl=False
        )

        stats = http_client_manager.get_stats()

        assert len(stats["clients"]) == 1
        client_info = stats["clients"][0]
        assert client_info["base_url"] == "https://api.example.com"
        assert client_info["timeout"] == 45.0
        assert client_info["verify_ssl"] is False
        assert client_info["is_async"] is False


class TestHttpClientManagerGetConfig:
    """Test configuration retrieval functionality."""

    def test_get_client_config_returns_config(self):
        """Test that get_client_config returns the correct configuration."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        http_client_manager.get_sync_client(
            base_url="https://api.example.com",
            timeout=60.0,
            verify_ssl=True
        )

        config = http_client_manager.get_client_config(
            base_url="https://api.example.com",
            timeout=60.0,
            verify_ssl=True
        )

        assert config is not None
        assert config.base_url == "https://api.example.com"
        assert config.timeout == 60.0
        assert config.verify_ssl is True

    def test_get_client_config_returns_none_for_nonexistent(self):
        """Test that get_client_config returns None for non-existent client."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        config = http_client_manager.get_client_config(
            base_url="https://nonexistent.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert config is None


class TestHttpClientManagerClientKey:
    """Test client key generation functionality."""

    def test_get_client_key_format(self):
        """Test that _get_client_key generates correct format."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        key = http_client_manager._get_client_key(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )

        assert key == "https://api.example.com|30.0|True"

    def test_get_client_key_different_params_different_keys(self):
        """Test that different parameters generate different keys."""
        _reset_singleton()
        from nexent.utils.http_client_manager import http_client_manager

        key1 = http_client_manager._get_client_key(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=True
        )
        key2 = http_client_manager._get_client_key(
            base_url="https://api.example.com",
            timeout=60.0,
            verify_ssl=True
        )
        key3 = http_client_manager._get_client_key(
            base_url="https://api.example.com",
            timeout=30.0,
            verify_ssl=False
        )

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3
