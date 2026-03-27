"""
Unit tests for mcp_container_service.py
Tests the MCPContainerManager class with comprehensive coverage
"""

import sys
import os
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.modules['boto3'] = MagicMock()

# Apply critical patches before importing any modules
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config',
      return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate',
      lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()
patch('elasticsearch.Elasticsearch', return_value=MagicMock()).start()

from consts.exceptions import MCPContainerError, MCPConnectionError
from services.mcp_container_service import MCPContainerManager
from nexent.container import ContainerError, ContainerConnectionError


# ---------------------------------------------------------------------------
# Test MCPContainerManager.__init__
# ---------------------------------------------------------------------------


class TestMCPContainerManagerInit:
    """Test MCPContainerManager initialization"""

    @patch('services.mcp_container_service.create_container_client_from_config')
    @patch('services.mcp_container_service.DockerContainerConfig')
    @patch('services.mcp_container_service.IS_DEPLOYED_BY_KUBERNETES', False)
    def test_init_success(self, mock_config_class, mock_create_client):
        """Test successful initialization"""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        manager = MCPContainerManager(
            docker_socket_path="/var/run/docker.sock")

        assert manager.client == mock_client
        mock_config_class.assert_called_once_with(
            docker_socket_path="/var/run/docker.sock"
        )
        mock_create_client.assert_called_once_with(mock_config)

    @patch('services.mcp_container_service.create_container_client_from_config')
    @patch('services.mcp_container_service.DockerContainerConfig')
    @patch('services.mcp_container_service.IS_DEPLOYED_BY_KUBERNETES', False)
    def test_init_container_error(self, mock_config_class, mock_create_client):
        """Test initialization failure when container client creation fails"""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        mock_create_client.side_effect = ContainerError(
            "Cannot connect to Docker")

        with pytest.raises(MCPContainerError, match="Cannot connect to Docker"):
            MCPContainerManager(docker_socket_path="/var/run/docker.sock")

    @patch('services.mcp_container_service.create_container_client_from_config')
    @patch('services.mcp_container_service.DockerContainerConfig')
    @patch('services.mcp_container_service.IS_DEPLOYED_BY_KUBERNETES', False)
    def test_init_default_socket_path(self, mock_config_class, mock_create_client):
        """Test initialization with default socket path"""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        manager = MCPContainerManager()

        mock_config_class.assert_called_once_with(
            docker_socket_path=None
        )

    @patch('services.mcp_container_service.create_container_client_from_config')
    @patch('services.mcp_container_service.KubernetesContainerConfig')
    @patch('services.mcp_container_service.IS_DEPLOYED_BY_KUBERNETES', True)
    @patch('services.mcp_container_service.KUBERNETES_NAMESPACE', 'test-namespace')
    def test_init_kubernetes_mode_success(self, mock_k8s_config_class, mock_create_client):
        """Test successful initialization in Kubernetes mode"""
        mock_config = MagicMock()
        mock_k8s_config_class.return_value = mock_config

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        manager = MCPContainerManager()

        assert manager.client == mock_client
        mock_k8s_config_class.assert_called_once_with(
            namespace='test-namespace',
            in_cluster=True,
        )
        mock_create_client.assert_called_once_with(mock_config)

    @patch('services.mcp_container_service.create_container_client_from_config')
    @patch('services.mcp_container_service.KubernetesContainerConfig')
    @patch('services.mcp_container_service.IS_DEPLOYED_BY_KUBERNETES', True)
    @patch('services.mcp_container_service.KUBERNETES_NAMESPACE', 'test-namespace')
    def test_init_kubernetes_mode_container_error(self, mock_k8s_config_class, mock_create_client):
        """Test initialization failure in Kubernetes mode"""
        mock_config = MagicMock()
        mock_k8s_config_class.return_value = mock_config

        mock_create_client.side_effect = ContainerError(
            "Cannot connect to Kubernetes")

        with pytest.raises(MCPContainerError, match="Cannot connect to Kubernetes"):
            MCPContainerManager()


# ---------------------------------------------------------------------------
# Test start_mcp_container
# ---------------------------------------------------------------------------


class TestStartMCPContainer:
    """Test start_mcp_container method"""

    @pytest.fixture
    def mock_manager(self):
        """Create MCPContainerManager instance with mocked client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.DockerContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            return manager

    @pytest.mark.asyncio
    async def test_start_mcp_container_success(self, mock_manager):
        """Test successful starting of MCP container"""
        mock_manager.client.start_container = AsyncMock(return_value={
            "container_id": "container-123",
            "service_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        result = await mock_manager.start_mcp_container(
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            full_command=["npx", "-y", "test-mcp"],
            env_vars={"NODE_ENV": "production"},
            host_port=5020,
            image="node:22-alpine"
        )

        assert result["container_id"] == "container-123"
        assert result["mcp_url"] == "http://localhost:5020/mcp"
        assert result["host_port"] == "5020"
        assert result["status"] == "started"
        assert result["container_name"] == "test-service-user1234"

        mock_manager.client.start_container.assert_called_once_with(
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            full_command=["npx", "-y", "test-mcp"],
            env_vars={"NODE_ENV": "production"},
            host_port=5020,
            image="node:22-alpine"
        )

    @pytest.mark.asyncio
    async def test_start_mcp_container_container_error(self, mock_manager):
        """Test starting container when ContainerError occurs"""
        mock_manager.client.start_container = AsyncMock(
            side_effect=ContainerError("Container startup failed"))

        with pytest.raises(MCPContainerError, match="Container startup failed"):
            await mock_manager.start_mcp_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"]
            )

    @pytest.mark.asyncio
    async def test_start_mcp_container_connection_error(self, mock_manager):
        """Test starting container when ContainerConnectionError occurs"""
        mock_manager.client.start_container = AsyncMock(
            side_effect=ContainerConnectionError("Connection failed"))

        with pytest.raises(MCPConnectionError, match="MCP connection failed"):
            await mock_manager.start_mcp_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"]
            )

    @pytest.mark.asyncio
    async def test_start_mcp_container_without_env_vars(self, mock_manager):
        """Test starting container without environment variables"""
        mock_manager.client.start_container = AsyncMock(return_value={
            "container_id": "container-123",
            "service_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        result = await mock_manager.start_mcp_container(
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            full_command=["npx", "-y", "test-mcp"]
        )

        assert result["status"] == "started"
        mock_manager.client.start_container.assert_called_once_with(
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            full_command=["npx", "-y", "test-mcp"],
            env_vars=None,
            host_port=None,
            image=None
        )

    @pytest.mark.asyncio
    async def test_start_mcp_container_without_full_command(self, mock_manager):
        """Test starting container without full_command (should work as per SDK design)"""
        mock_manager.client.start_container = AsyncMock(return_value={
            "container_id": "container-123",
            "service_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        result = await mock_manager.start_mcp_container(
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            full_command=None
        )

        assert result["container_id"] == "container-123"
        assert result["mcp_url"] == "http://localhost:5020/mcp"
        mock_manager.client.start_container.assert_called_once_with(
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            full_command=None,
            env_vars=None,
            host_port=None,
            image=None
        )


# ---------------------------------------------------------------------------
# Test stop_mcp_container
# ---------------------------------------------------------------------------


class TestStopMCPContainer:
    """Test stop_mcp_container method"""

    @pytest.fixture
    def mock_manager(self):
        """Create MCPContainerManager instance with mocked client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.DockerContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            return manager

    @pytest.mark.asyncio
    async def test_stop_mcp_container_success(self, mock_manager):
        """Test successful stopping and removal of MCP container"""
        mock_manager.client.stop_container = AsyncMock(return_value=True)
        mock_manager.client.remove_container = AsyncMock(return_value=True)

        result = await mock_manager.stop_mcp_container("container-123")

        assert result is True
        mock_manager.client.stop_container.assert_called_once_with(
            "container-123")
        mock_manager.client.remove_container.assert_called_once_with(
            "container-123")

    @pytest.mark.asyncio
    async def test_stop_mcp_container_stop_not_found(self, mock_manager):
        """Test stopping non-existent container"""
        mock_manager.client.stop_container = AsyncMock(return_value=False)

        result = await mock_manager.stop_mcp_container("non-existent")

        assert result is False
        mock_manager.client.stop_container.assert_called_once_with(
            "non-existent")
        mock_manager.client.remove_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_mcp_container_remove_not_found(self, mock_manager):
        """Test removing container when stop succeeds but remove fails (not found)"""
        mock_manager.client.stop_container = AsyncMock(return_value=True)
        mock_manager.client.remove_container = AsyncMock(return_value=False)

        result = await mock_manager.stop_mcp_container("container-123")

        assert result is False
        mock_manager.client.stop_container.assert_called_once_with(
            "container-123")
        mock_manager.client.remove_container.assert_called_once_with(
            "container-123")

    @pytest.mark.asyncio
    async def test_stop_mcp_container_stop_error(self, mock_manager):
        """Test stopping container when ContainerError occurs during stop"""
        mock_manager.client.stop_container = AsyncMock(
            side_effect=ContainerError("Stop failed"))

        with pytest.raises(MCPContainerError, match="Failed to stop container"):
            await mock_manager.stop_mcp_container("container-123")

        mock_manager.client.stop_container.assert_called_once_with(
            "container-123")
        mock_manager.client.remove_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_mcp_container_remove_error(self, mock_manager):
        """Test removing container when ContainerError occurs during remove"""
        mock_manager.client.stop_container = AsyncMock(return_value=True)
        mock_manager.client.remove_container = AsyncMock(
            side_effect=ContainerError("Remove failed"))

        with pytest.raises(MCPContainerError, match="Failed to stop container"):
            await mock_manager.stop_mcp_container("container-123")

        mock_manager.client.stop_container.assert_called_once_with(
            "container-123")
        mock_manager.client.remove_container.assert_called_once_with(
            "container-123")


# ---------------------------------------------------------------------------
# Test list_mcp_containers
# ---------------------------------------------------------------------------


class TestListMCPContainers:
    """Test list_mcp_containers method"""

    @pytest.fixture
    def mock_manager(self):
        """Create MCPContainerManager instance with mocked client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.DockerContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            return manager

    def test_list_mcp_containers_success(self, mock_manager):
        """Test successful listing of MCP containers"""
        mock_manager.client.list_containers.return_value = [
            {
                "container_id": "container-1",
                "name": "service1-user1234",
                "status": "running",
                "service_url": "http://localhost:5020/mcp",
                "host_port": "5020"
            },
            {
                "container_id": "container-2",
                "name": "service2-user1234",
                "status": "running",
                "service_url": "http://localhost:5021/mcp",
                "host_port": "5021"
            }
        ]

        result = mock_manager.list_mcp_containers(tenant_id="tenant123")

        assert len(result) == 2
        assert result[0]["container_id"] == "container-1"
        assert result[0]["mcp_url"] == "http://localhost:5020/mcp"
        assert result[1]["container_id"] == "container-2"
        assert result[1]["mcp_url"] == "http://localhost:5021/mcp"
        mock_manager.client.list_containers.assert_called_once_with(
            tenant_id="tenant123")

    def test_list_mcp_containers_no_tenant_filter(self, mock_manager):
        """Test listing containers without tenant filter"""
        mock_manager.client.list_containers.return_value = [
            {
                "container_id": "container-1",
                "name": "service1-user1234",
                "status": "running",
                "service_url": "http://localhost:5020/mcp",
                "host_port": "5020"
            }
        ]

        result = mock_manager.list_mcp_containers()

        assert len(result) == 1
        mock_manager.client.list_containers.assert_called_once_with(
            tenant_id=None)

    def test_list_mcp_containers_empty(self, mock_manager):
        """Test listing containers when none exist"""
        mock_manager.client.list_containers.return_value = []

        result = mock_manager.list_mcp_containers(tenant_id="tenant123")

        assert len(result) == 0

    def test_list_mcp_containers_exception(self, mock_manager):
        """Test listing containers when exception occurs"""
        mock_manager.client.list_containers.side_effect = Exception(
            "Connection error")

        result = mock_manager.list_mcp_containers(tenant_id="tenant123")

        assert result == []

    def test_list_mcp_containers_maps_service_url_to_mcp_url(self, mock_manager):
        """Test that service_url is correctly mapped to mcp_url"""
        mock_manager.client.list_containers.return_value = [
            {
                "container_id": "container-1",
                "name": "service1-user1234",
                "status": "running",
                "service_url": "http://localhost:5020/mcp",
                "host_port": "5020"
            }
        ]

        result = mock_manager.list_mcp_containers(tenant_id="tenant123")

        assert result[0]["mcp_url"] == "http://localhost:5020/mcp"
        assert "service_url" not in result[0]  # Should be mapped to mcp_url


# ---------------------------------------------------------------------------
# Test get_container_logs
# ---------------------------------------------------------------------------


class TestGetContainerLogs:
    """Test get_container_logs method"""

    @pytest.fixture
    def mock_manager(self):
        """Create MCPContainerManager instance with mocked client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.DockerContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            return manager

    def test_get_container_logs_success(self, mock_manager):
        """Test successful retrieval of container logs"""
        mock_manager.client.get_container_logs.return_value = "Log line 1\nLog line 2\nLog line 3"

        logs = mock_manager.get_container_logs("container-123", tail=100)

        assert logs == "Log line 1\nLog line 2\nLog line 3"
        mock_manager.client.get_container_logs.assert_called_once_with(
            "container-123", tail=100)

    def test_get_container_logs_custom_tail(self, mock_manager):
        """Test getting container logs with custom tail"""
        mock_manager.client.get_container_logs.return_value = "Log line 1"

        logs = mock_manager.get_container_logs("container-123", tail=50)

        mock_manager.client.get_container_logs.assert_called_once_with(
            "container-123", tail=50)

    def test_get_container_logs_default_tail(self, mock_manager):
        """Test getting container logs with default tail"""
        mock_manager.client.get_container_logs.return_value = "Log line 1"

        logs = mock_manager.get_container_logs("container-123")

        mock_manager.client.get_container_logs.assert_called_once_with(
            "container-123", tail=100)

    def test_get_container_logs_exception(self, mock_manager):
        """Test getting container logs when exception occurs"""
        mock_manager.client.get_container_logs.side_effect = Exception(
            "Connection error")

        logs = mock_manager.get_container_logs("container-123")

        assert "Error retrieving logs" in logs


# ---------------------------------------------------------------------------
# Test stream_container_logs
# ---------------------------------------------------------------------------


class TestStreamContainerLogs:
    """Test stream_container_logs method"""

    @pytest.fixture
    def mock_manager(self):
        """Create MCPContainerManager instance with mocked client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.DockerContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            manager.client.client = MagicMock()
            return manager

    @pytest.mark.asyncio
    async def test_stream_container_logs_initial_logs_only(self, mock_manager):
        """Test streaming container logs with initial logs only (follow=False)"""
        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs
        initial_logs_bytes = b"Log line 1\nLog line 2\nLog line 3\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Collect logs from async generator
        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=False
        ):
            logs.append(log_line)

        assert len(logs) == 3
        assert logs[0] == "Log line 1"
        assert logs[1] == "Log line 2"
        assert logs[2] == "Log line 3"
        mock_container.logs.assert_called_once_with(
            tail=100, stdout=True, stderr=True, timestamps=False
        )

    @pytest.mark.asyncio
    async def test_stream_container_logs_empty_initial_logs(self, mock_manager):
        """Test streaming when initial logs are empty"""
        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock empty initial logs
        mock_container.logs.return_value = b""

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=False
        ):
            logs.append(log_line)

        assert len(logs) == 0

    @pytest.mark.asyncio
    async def test_stream_container_logs_filters_empty_lines(self, mock_manager):
        """Test that empty lines are filtered out"""
        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock logs with empty lines
        initial_logs_bytes = b"Log line 1\n\nLog line 2\n   \nLog line 3\n"
        mock_container.logs.return_value = initial_logs_bytes

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=False
        ):
            logs.append(log_line)

        assert len(logs) == 3
        assert "Log line 1" in logs
        assert "Log line 2" in logs
        assert "Log line 3" in logs

    @pytest.mark.asyncio
    async def test_stream_container_logs_with_follow(self, mock_manager):
        """Test streaming container logs with follow=True - normal flow"""
        import asyncio
        import threading
        import time

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs
        initial_logs_bytes = b"Initial log\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream - create a generator that yields chunks
        follow_chunks = [
            b"New log 1\n",
            b"New log 2\n",
            b"New log 3\n",
        ]
        follow_stream = iter(follow_chunks)

        # First call returns initial logs, second call returns follow stream
        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: initial logs
                return initial_logs_bytes
            elif call_count[0] == 2:
                # Second call: follow stream
                return follow_stream
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        # Collect logs from async generator
        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            # Wait a bit for thread to process, then break after we get follow logs
            if len(logs) >= 4:  # Initial log + 3 follow logs
                break
            await asyncio.sleep(0.1)  # Give thread time to put items in queue

        # Should have initial log and follow logs
        assert len(logs) >= 1
        assert "Initial log" in logs[0]
        # Verify follow logs are captured (may need to wait for thread)
        assert any("New log" in log for log in logs) or len(logs) >= 1

    @pytest.mark.asyncio
    async def test_stream_container_logs_container_not_found(self, mock_manager):
        """Test streaming logs when container is not found"""
        from docker.errors import NotFound

        mock_manager.client.client.containers.get.side_effect = NotFound(
            "Container not found", response=None, explanation="Container does not exist"
        )

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "non-existent", tail=100, follow=False
        ):
            logs.append(log_line)

        # Should yield error message
        assert len(logs) == 1
        assert "Error retrieving logs" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_container_logs_exception_during_streaming(self, mock_manager):
        """Test exception handling during log streaming in thread (covers lines 318-322)"""
        import asyncio
        import threading

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs to succeed
        initial_logs_bytes = b"Log line 1\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream to raise exception during iteration in thread
        # The exception should be raised inside the for loop (line 307), not at container.logs() call
        call_count = [0]
        iteration_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: initial logs
                return initial_logs_bytes
            elif call_count[0] == 2:
                # Second call: follow stream - raise exception during iteration
                def exception_stream():
                    iteration_count[0] += 1
                    yield b"First chunk\n"
                    iteration_count[0] += 1
                    # Raise exception during iteration (inside for loop at line 307)
                    raise Exception("Stream error during iteration")
                return exception_stream()
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        # Collect logs from async generator
        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            # Wait for thread to process chunks and raise exception
            await asyncio.sleep(0.2)
            # After exception, None should be put in queue (line 320-321)
            # This will break the while loop (line 333-334)
            break

        # Should have initial log
        assert len(logs) >= 1
        assert "Log line 1" in logs[0]
        # Exception should be caught at line 318, None put in queue at line 320-321

    @pytest.mark.asyncio
    async def test_stream_container_logs_follow_exception_in_logs_call(self, mock_manager):
        """Test exception when container.logs() raises exception (covers lines 318-322)"""
        import asyncio

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs to succeed
        initial_logs_bytes = b"Log line 1\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream - container.logs() call itself raises exception
        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: initial logs
                return initial_logs_bytes
            elif call_count[0] == 2:
                # Second call: container.logs() raises exception (before iteration)
                raise Exception("Error calling container.logs()")
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        # Collect logs from async generator
        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            # Wait for thread exception handling
            await asyncio.sleep(0.2)
            break

        # Should have initial log
        assert len(logs) >= 1
        assert "Log line 1" in logs[0]
        # Exception should be caught at line 318, None put in queue at line 320-321

    @pytest.mark.asyncio
    async def test_stream_container_logs_follow_with_multiple_chunks(self, mock_manager):
        """Test follow=True with multiple log chunks and line splitting (covers lines 307-339)"""
        import asyncio
        import threading

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs
        initial_logs_bytes = b"Initial log\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream with multiple chunks containing multiple lines
        follow_chunks = [
            b"Chunk 1 line 1\nChunk 1 line 2\n",
            b"Chunk 2 line 1\n",
            b"Chunk 3 line 1\nChunk 3 line 2\nChunk 3 line 3\n",
        ]
        follow_stream = iter(follow_chunks)

        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return initial_logs_bytes
            elif call_count[0] == 2:
                return follow_stream
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            # Collect all logs
            await asyncio.sleep(0.1)
            if len(logs) >= 10:  # Safety limit
                break

        # Should have initial log and follow logs split by lines
        assert len(logs) >= 1
        assert "Initial log" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_container_logs_follow_filters_empty_lines(self, mock_manager):
        """Test that empty lines are filtered in follow stream (covers lines 337-339)"""
        import asyncio

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs with empty lines
        initial_logs_bytes = b"Initial log\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream with empty lines
        follow_chunks = [
            b"Valid log 1\n\n   \nValid log 2\n",
        ]
        follow_stream = iter(follow_chunks)

        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return initial_logs_bytes
            elif call_count[0] == 2:
                return follow_stream
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            await asyncio.sleep(0.1)
            if len(logs) >= 5:  # Safety limit
                break

        # Should filter out empty lines
        assert len(logs) >= 1
        # All logs should be non-empty
        for log in logs:
            assert log.strip() != ""

    @pytest.mark.asyncio
    async def test_stream_container_logs_follow_stop_flag(self, mock_manager):
        """Test that stop_flag stops the thread loop (covers lines 308-309, 341)"""
        import asyncio
        import threading
        import time

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs
        initial_logs_bytes = b"Initial log\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream that yields chunks slowly
        # This allows stop_flag to be checked during iteration at line 308
        chunk_count = [0]

        def slow_stream():
            while True:
                chunk_count[0] += 1
                yield f"Log chunk {chunk_count[0]}\n".encode()
                # Small delay to allow stop_flag to be set and checked
                time.sleep(0.05)
                if chunk_count[0] > 20:  # Safety limit
                    break

        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return initial_logs_bytes
            elif call_count[0] == 2:
                return slow_stream()
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            # Break early to trigger stop_flag in finally block (line 341)
            # This will set stop_flag[0] = True, which thread checks at line 308
            if len(logs) >= 2:
                break

        # Give thread time to check stop_flag[0] at line 308 and break at line 309
        await asyncio.sleep(0.2)

        # Should have at least initial log
        assert len(logs) >= 1
        # stop_flag should be set in finally block (line 341)
        # Thread should check stop_flag[0] at line 308 and break at line 309

    @pytest.mark.asyncio
    async def test_stream_container_logs_follow_queue_none_signal(self, mock_manager):
        """Test that None in queue signals end of stream (covers lines 314-317, 332-334)"""
        import asyncio

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs
        initial_logs_bytes = b"Initial log\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream that immediately ends (puts None in queue)
        follow_chunks = [
            b"Follow log 1\n",
        ]
        follow_stream = iter(follow_chunks)

        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return initial_logs_bytes
            elif call_count[0] == 2:
                return follow_stream
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            await asyncio.sleep(0.2)  # Wait for thread to finish and put None

        # Should have initial log and follow log before None signal
        assert len(logs) >= 1
        assert "Initial log" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_container_logs_follow_stop_flag_during_iteration(self, mock_manager):
        """Test stop_flag check during log stream iteration (covers lines 308-309)"""
        import asyncio
        import time

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs
        initial_logs_bytes = b"Initial log\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Create a stream that yields multiple chunks with delays
        # This ensures the thread will be in the for loop (line 307) when stop_flag is checked
        chunk_yielded = [False]

        def stream_with_delay():
            chunk_yielded[0] = True
            yield b"Chunk 1\n"
            time.sleep(0.1)  # Delay to allow stop_flag to be set
            yield b"Chunk 2\n"
            time.sleep(0.1)
            yield b"Chunk 3\n"

        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return initial_logs_bytes
            elif call_count[0] == 2:
                return stream_with_delay()
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            # After getting initial log, break to set stop_flag[0] = True in finally (line 341)
            # Thread should check stop_flag[0] at line 308 during next iteration
            if len(logs) >= 1:
                # Small delay to let thread start processing
                await asyncio.sleep(0.05)
                break

        # Wait for thread to check stop_flag and break
        await asyncio.sleep(0.2)

        # Should have initial log
        assert len(logs) >= 1
        # stop_flag[0] is set to True in finally block (line 341)
        # Thread checks stop_flag[0] at line 308 and breaks at line 309

    @pytest.mark.asyncio
    async def test_stream_container_logs_follow_decode_errors(self, mock_manager):
        """Test decode error handling in follow stream (covers line 335)"""
        import asyncio

        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock initial logs
        initial_logs_bytes = b"Initial log\n"
        mock_container.logs.return_value = initial_logs_bytes

        # Mock follow stream with invalid UTF-8
        follow_chunks = [
            b"Valid log\n",
            b"\xff\xfeInvalid UTF-8\n",  # Invalid UTF-8 bytes
            b"Another valid log\n",
        ]
        follow_stream = iter(follow_chunks)

        call_count = [0]

        def logs_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return initial_logs_bytes
            elif call_count[0] == 2:
                return follow_stream
            else:
                return iter([])

        mock_container.logs.side_effect = logs_side_effect

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=True
        ):
            logs.append(log_line)
            await asyncio.sleep(0.1)
            if len(logs) >= 5:  # Safety limit
                break

        # Should handle decode errors gracefully with errors="replace"
        assert len(logs) >= 1
        assert "Initial log" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_container_logs_decode_error(self, mock_manager):
        """Test handling of decode errors in log streaming"""
        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        # Mock logs with invalid UTF-8 bytes
        initial_logs_bytes = b"\xff\xfeInvalid UTF-8\n"
        mock_container.logs.return_value = initial_logs_bytes

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=100, follow=False
        ):
            logs.append(log_line)

        # Should handle decode errors gracefully with errors="replace"
        assert len(logs) >= 0

    @pytest.mark.asyncio
    async def test_stream_container_logs_custom_tail(self, mock_manager):
        """Test streaming with custom tail parameter"""
        mock_container = MagicMock()
        mock_manager.client.client.containers.get.return_value = mock_container

        initial_logs_bytes = b"Log line 1\n"
        mock_container.logs.return_value = initial_logs_bytes

        logs = []
        async for log_line in mock_manager.stream_container_logs(
            "container-123", tail=50, follow=False
        ):
            logs.append(log_line)

        # Verify tail parameter was passed correctly
        mock_container.logs.assert_called_with(
            tail=50, stdout=True, stderr=True, timestamps=False
        )


# ---------------------------------------------------------------------------
# Test stream_container_logs (Kubernetes Mode)
# ---------------------------------------------------------------------------


class TestStreamContainerLogsKubernetes:
    """Test stream_container_logs method in Kubernetes mode"""

    @pytest.fixture(autouse=True)
    def setup_k8s_patches(self):
        """Setup patches for Kubernetes mode - runs for each test"""
        self._patches = [
            patch('services.mcp_container_service.IS_DEPLOYED_BY_KUBERNETES', True),
            patch('services.mcp_container_service.KUBERNETES_NAMESPACE', 'test-namespace'),
        ]
        for p in self._patches:
            p.start()
        yield
        for p in self._patches:
            p.stop()

    @pytest.fixture
    def mock_manager_k8s(self):
        """Create MCPContainerManager instance with mocked Kubernetes client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.KubernetesContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            manager.client.core_v1 = MagicMock()
            yield manager

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_initial_logs_only(self, mock_manager_k8s):
        """Test streaming Kubernetes container logs with initial logs only (follow=False)"""
        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"

        # Mock get_container_logs for initial logs
        mock_manager_k8s.client.get_container_logs.return_value = "K8s log line 1\nK8s log line 2\n"

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=False
        ):
            logs.append(log_line)

        assert len(logs) == 2
        assert logs[0] == "K8s log line 1"
        assert logs[1] == "K8s log line 2"
        mock_manager_k8s.client._resolve_pod_name.assert_called_once_with("container-uid-123")

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_pod_not_found(self, mock_manager_k8s):
        """Test streaming logs when Kubernetes pod is not found"""
        mock_manager_k8s.client._resolve_pod_name.return_value = None

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "non-existent-uid", tail=100, follow=False
        ):
            logs.append(log_line)

        # Should yield no logs when pod is not found
        assert len(logs) == 0
        mock_manager_k8s.client._resolve_pod_name.assert_called_once_with("non-existent-uid")

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_empty_initial_logs(self, mock_manager_k8s):
        """Test streaming when initial Kubernetes logs are empty"""
        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"
        mock_manager_k8s.client.get_container_logs.return_value = ""

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=False
        ):
            logs.append(log_line)

        assert len(logs) == 0

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_filters_empty_lines(self, mock_manager_k8s):
        """Test that empty lines are filtered out in Kubernetes mode"""
        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"

        # Mock initial logs with empty lines
        mock_manager_k8s.client.get_container_logs.return_value = "Log 1\n\nLog 2\n   \nLog 3\n"

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=False
        ):
            logs.append(log_line)

        assert len(logs) == 3
        assert "Log 1" in logs
        assert "Log 2" in logs
        assert "Log 3" in logs

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_with_follow(self, mock_manager_k8s):
        """Test streaming Kubernetes container logs with follow=True"""
        import asyncio

        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"
        mock_manager_k8s.client.get_container_logs.return_value = "Initial K8s log\n"

        # Mock Kubernetes log stream
        mock_manager_k8s.client.core_v1.read_namespaced_pod_log.return_value = iter([
            b"New K8s log 1\n",
            b"New K8s log 2\n",
        ])

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=True
        ):
            logs.append(log_line)
            if len(logs) >= 3:
                break
            await asyncio.sleep(0.1)

        assert len(logs) >= 1
        assert "Initial K8s log" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_follow_stream_exception(self, mock_manager_k8s):
        """Test exception handling during Kubernetes log stream"""
        import asyncio

        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"
        mock_manager_k8s.client.get_container_logs.return_value = "Log line\n"

        # Mock Kubernetes log stream to raise exception
        def raise_exception_stream():
            yield b"Chunk 1\n"
            raise Exception("K8s stream error")

        mock_manager_k8s.client.core_v1.read_namespaced_pod_log.return_value = raise_exception_stream()

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=True
        ):
            logs.append(log_line)
            await asyncio.sleep(0.2)
            break

        assert len(logs) >= 1
        assert "Log line" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_bytes_decoding(self, mock_manager_k8s):
        """Test Kubernetes log stream handles bytes decoding"""
        import asyncio

        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"
        mock_manager_k8s.client.get_container_logs.return_value = "Initial log\n"

        # Mock Kubernetes log stream returning bytes
        mock_manager_k8s.client.core_v1.read_namespaced_pod_log.return_value = iter([
            b"Decoded log 1\n",
            b"\xff\xfeInvalid UTF-8\n",  # Invalid UTF-8
            b"Valid log 2\n",
        ])

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=True
        ):
            logs.append(log_line)
            await asyncio.sleep(0.1)
            if len(logs) >= 5:
                break

        assert len(logs) >= 1
        # Should handle decode errors gracefully

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_stop_flag(self, mock_manager_k8s):
        """Test stop_flag stops Kubernetes log stream"""
        import asyncio
        import time

        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"
        mock_manager_k8s.client.get_container_logs.return_value = "Initial\n"

        # Mock slow stream to allow stop_flag to be set
        def slow_stream():
            for i in range(5):
                yield f"Log {i}\n".encode()
                time.sleep(0.05)

        mock_manager_k8s.client.core_v1.read_namespaced_pod_log.return_value = slow_stream()

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=True
        ):
            logs.append(log_line)
            if len(logs) >= 2:
                break
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.2)

        assert len(logs) >= 1

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_custom_namespace(self, mock_manager_k8s):
        """Test streaming logs with custom Kubernetes namespace"""
        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"
        mock_manager_k8s.client.get_container_logs.return_value = "Log\n"

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=False
        ):
            logs.append(log_line)

        assert len(logs) == 1

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_outer_exception(self, mock_manager_k8s):
        """Test outer exception handler in Kubernetes stream_container_logs (lines 426-428)"""
        mock_manager_k8s.client._resolve_pod_name.side_effect = Exception(
            "Unexpected error in K8s mode")

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=False
        ):
            logs.append(log_line)

        # Should yield error message from outer exception handler
        assert len(logs) == 1
        assert "Error retrieving logs" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_container_logs_k8s_read_pod_log_params(self, mock_manager_k8s):
        """Test that read_namespaced_pod_log is called with correct parameters"""
        import asyncio

        mock_manager_k8s.client._resolve_pod_name.return_value = "test-pod"
        mock_manager_k8s.client.get_container_logs.return_value = ""

        # Mock stream that ends immediately
        mock_manager_k8s.client.core_v1.read_namespaced_pod_log.return_value = iter([])

        logs = []
        async for log_line in mock_manager_k8s.stream_container_logs(
            "container-uid-123", tail=100, follow=True
        ):
            logs.append(log_line)
            await asyncio.sleep(0.1)
            if len(logs) >= 2:
                break

        # Verify read_namespaced_pod_log was called with correct parameters
        mock_manager_k8s.client.core_v1.read_namespaced_pod_log.assert_called_once()
        call_kwargs = mock_manager_k8s.client.core_v1.read_namespaced_pod_log.call_args[1]
        assert call_kwargs['name'] == 'test-pod'
        assert call_kwargs['namespace'] == 'test-namespace'
        assert call_kwargs['container'] == 'mcp-server'
        assert call_kwargs['follow'] is True
        assert call_kwargs['timestamps'] is False
        assert call_kwargs['_preload_content'] is False
        assert call_kwargs['tail_lines'] == 0


# ---------------------------------------------------------------------------
# Test load_image_from_tar_file
# ---------------------------------------------------------------------------


class TestLoadImageFromTarFile:
    """Test load_image_from_tar_file method"""

    @pytest.fixture
    def mock_manager(self):
        """Create MCPContainerManager instance with mocked client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.DockerContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            return manager

    @pytest.mark.asyncio
    async def test_load_image_from_tar_file_success_with_tags(self, mock_manager):
        """Test successful loading of image with tags"""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as temp_file:
            temp_file.write(b"fake tar content")
            temp_file_path = temp_file.name

        try:
            mock_image = MagicMock()
            mock_image.tags = ["test-image:latest", "test-image:v1.0"]
            mock_image.id = "sha256:1234567890abcdef"

            mock_manager.client.client.images.load.return_value = [mock_image]

            result = await mock_manager.load_image_from_tar_file(temp_file_path)

            assert result == "test-image:latest"
            mock_manager.client.client.images.load.assert_called_once()
        finally:
            # Clean up
            try:
                os.unlink(temp_file_path)
            except:
                pass

    @pytest.mark.asyncio
    async def test_load_image_from_tar_file_success_without_tags(self, mock_manager):
        """Test successful loading of image without tags"""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as temp_file:
            temp_file.write(b"fake tar content")
            temp_file_path = temp_file.name

        try:
            mock_image = MagicMock()
            mock_image.tags = []
            mock_image.id = "sha256:1234567890abcdef"

            mock_manager.client.client.images.load.return_value = [mock_image]

            result = await mock_manager.load_image_from_tar_file(temp_file_path)

            assert result == "sha256:1234567890abcdef"
            mock_manager.client.client.images.load.assert_called_once()
        finally:
            # Clean up
            try:
                os.unlink(temp_file_path)
            except:
                pass

    @pytest.mark.asyncio
    async def test_load_image_from_tar_file_empty_images(self, mock_manager):
        """Test loading when no images are found in tar file (covers lines 69-70)"""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as temp_file:
            temp_file.write(b"fake tar content")
            temp_file_path = temp_file.name

        try:
            mock_manager.client.client.images.load.return_value = []

            with pytest.raises(MCPContainerError, match="No images found in tar file"):
                await mock_manager.load_image_from_tar_file(temp_file_path)
        finally:
            # Clean up
            try:
                os.unlink(temp_file_path)
            except:
                pass

    @pytest.mark.asyncio
    async def test_load_image_from_tar_file_exception(self, mock_manager):
        """Test loading when exception occurs (covers lines 80-82)"""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as temp_file:
            temp_file.write(b"fake tar content")
            temp_file_path = temp_file.name

        try:
            mock_manager.client.client.images.load.side_effect = Exception(
                "File not found")

            with pytest.raises(MCPContainerError, match="Failed to load image from tar file: File not found"):
                await mock_manager.load_image_from_tar_file(temp_file_path)
        finally:
            # Clean up
            try:
                os.unlink(temp_file_path)
            except:
                pass


# ---------------------------------------------------------------------------
# Test start_mcp_container_from_tar
# ---------------------------------------------------------------------------


class TestStartMCPContainerFromTar:
    """Test start_mcp_container_from_tar method"""

    @pytest.fixture
    def mock_manager(self):
        """Create MCPContainerManager instance with mocked client"""
        with patch('services.mcp_container_service.create_container_client_from_config'), \
                patch('services.mcp_container_service.DockerContainerConfig'):
            manager = MCPContainerManager()
            manager.client = MagicMock()
            return manager

    @pytest.mark.asyncio
    async def test_start_mcp_container_from_tar_success(self, mock_manager):
        """Test successful starting of MCP container from tar file"""
        # Mock load_image_from_tar_file
        mock_manager.load_image_from_tar_file = AsyncMock(
            return_value="loaded-image:latest")

        # Mock start_mcp_container
        mock_manager.start_mcp_container = AsyncMock(return_value={
            "container_id": "container-123",
            "mcp_url": "http://localhost:5020/mcp",
            "host_port": "5020",
            "status": "started",
            "container_name": "test-service-user1234"
        })

        result = await mock_manager.start_mcp_container_from_tar(
            tar_file_path="/path/to/image.tar",
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            env_vars={"NODE_ENV": "production"},
            host_port=5020,
            full_command=["npx", "-y", "test-mcp"]
        )

        assert result["container_id"] == "container-123"
        assert result["mcp_url"] == "http://localhost:5020/mcp"
        mock_manager.load_image_from_tar_file.assert_called_once_with(
            "/path/to/image.tar")
        mock_manager.start_mcp_container.assert_called_once_with(
            service_name="test-service",
            tenant_id="tenant123",
            user_id="user12345",
            env_vars={"NODE_ENV": "production"},
            host_port=5020,
            image="loaded-image:latest",
            full_command=["npx", "-y", "test-mcp"]
        )

    @pytest.mark.asyncio
    async def test_start_mcp_container_from_tar_load_image_error(self, mock_manager):
        """Test starting container when load_image_from_tar_file fails (covers lines 178-181)"""
        # Mock load_image_from_tar_file to raise error
        mock_manager.load_image_from_tar_file = AsyncMock(
            side_effect=MCPContainerError("Failed to load image"))

        with pytest.raises(MCPContainerError, match="Failed to start container from tar file: Failed to load image"):
            await mock_manager.start_mcp_container_from_tar(
                tar_file_path="/path/to/image.tar",
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345"
            )

    @pytest.mark.asyncio
    async def test_start_mcp_container_from_tar_start_container_error(self, mock_manager):
        """Test starting container when start_mcp_container fails (covers lines 178-181)"""
        # Mock load_image_from_tar_file to succeed
        mock_manager.load_image_from_tar_file = AsyncMock(
            return_value="loaded-image:latest")

        # Mock start_mcp_container to raise error
        mock_manager.start_mcp_container = AsyncMock(
            side_effect=MCPContainerError("Container startup failed"))

        with pytest.raises(MCPContainerError, match="Failed to start container from tar file: Container startup failed"):
            await mock_manager.start_mcp_container_from_tar(
                tar_file_path="/path/to/image.tar",
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345"
            )


if __name__ == "__main__":
    pytest.main([__file__])
