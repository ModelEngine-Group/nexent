"""
Unit tests for mcp_container_service.py
Tests the MCPContainerManager class with comprehensive coverage
"""

import sys
import os
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
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
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
    def test_init_success(self, mock_config_class, mock_create_client):
        """Test successful initialization"""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        manager = MCPContainerManager(docker_socket_path="/var/run/docker.sock")

        assert manager.client == mock_client
        mock_config_class.assert_called_once_with(
            docker_socket_path="/var/run/docker.sock"
        )
        mock_create_client.assert_called_once_with(mock_config)

    @patch('services.mcp_container_service.create_container_client_from_config')
    @patch('services.mcp_container_service.DockerContainerConfig')
    def test_init_container_error(self, mock_config_class, mock_create_client):
        """Test initialization failure when container client creation fails"""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        
        mock_create_client.side_effect = ContainerError("Cannot connect to Docker")

        with pytest.raises(MCPContainerError, match="Cannot connect to Docker"):
            MCPContainerManager(docker_socket_path="/var/run/docker.sock")

    @patch('services.mcp_container_service.create_container_client_from_config')
    @patch('services.mcp_container_service.DockerContainerConfig')
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
    async def test_start_mcp_container_missing_full_command(self, mock_manager):
        """Test starting container without full_command"""
        with pytest.raises(MCPContainerError, match="full_command is required"):
            await mock_manager.start_mcp_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=None
            )

    @pytest.mark.asyncio
    async def test_start_mcp_container_container_error(self, mock_manager):
        """Test starting container when ContainerError occurs"""
        mock_manager.client.start_container = AsyncMock(side_effect=ContainerError("Container startup failed"))

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
        mock_manager.client.start_container = AsyncMock(side_effect=ContainerConnectionError("Connection failed"))

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
        mock_manager.client.stop_container.assert_called_once_with("container-123")
        mock_manager.client.remove_container.assert_called_once_with("container-123")

    @pytest.mark.asyncio
    async def test_stop_mcp_container_stop_not_found(self, mock_manager):
        """Test stopping non-existent container"""
        mock_manager.client.stop_container = AsyncMock(return_value=False)

        result = await mock_manager.stop_mcp_container("non-existent")

        assert result is False
        mock_manager.client.stop_container.assert_called_once_with("non-existent")
        mock_manager.client.remove_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_mcp_container_remove_not_found(self, mock_manager):
        """Test removing container when stop succeeds but remove fails (not found)"""
        mock_manager.client.stop_container = AsyncMock(return_value=True)
        mock_manager.client.remove_container = AsyncMock(return_value=False)

        result = await mock_manager.stop_mcp_container("container-123")

        assert result is False
        mock_manager.client.stop_container.assert_called_once_with("container-123")
        mock_manager.client.remove_container.assert_called_once_with("container-123")

    @pytest.mark.asyncio
    async def test_stop_mcp_container_stop_error(self, mock_manager):
        """Test stopping container when ContainerError occurs during stop"""
        mock_manager.client.stop_container = AsyncMock(side_effect=ContainerError("Stop failed"))

        with pytest.raises(MCPContainerError, match="Failed to stop container"):
            await mock_manager.stop_mcp_container("container-123")

        mock_manager.client.stop_container.assert_called_once_with("container-123")
        mock_manager.client.remove_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_mcp_container_remove_error(self, mock_manager):
        """Test removing container when ContainerError occurs during remove"""
        mock_manager.client.stop_container = AsyncMock(return_value=True)
        mock_manager.client.remove_container = AsyncMock(side_effect=ContainerError("Remove failed"))

        with pytest.raises(MCPContainerError, match="Failed to stop container"):
            await mock_manager.stop_mcp_container("container-123")

        mock_manager.client.stop_container.assert_called_once_with("container-123")
        mock_manager.client.remove_container.assert_called_once_with("container-123")


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
        mock_manager.client.list_containers.assert_called_once_with(tenant_id="tenant123")

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
        mock_manager.client.list_containers.assert_called_once_with(tenant_id=None)

    def test_list_mcp_containers_empty(self, mock_manager):
        """Test listing containers when none exist"""
        mock_manager.client.list_containers.return_value = []

        result = mock_manager.list_mcp_containers(tenant_id="tenant123")

        assert len(result) == 0

    def test_list_mcp_containers_exception(self, mock_manager):
        """Test listing containers when exception occurs"""
        mock_manager.client.list_containers.side_effect = Exception("Connection error")

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
        mock_manager.client.get_container_logs.assert_called_once_with("container-123", tail=100)

    def test_get_container_logs_custom_tail(self, mock_manager):
        """Test getting container logs with custom tail"""
        mock_manager.client.get_container_logs.return_value = "Log line 1"

        logs = mock_manager.get_container_logs("container-123", tail=50)

        mock_manager.client.get_container_logs.assert_called_once_with("container-123", tail=50)

    def test_get_container_logs_default_tail(self, mock_manager):
        """Test getting container logs with default tail"""
        mock_manager.client.get_container_logs.return_value = "Log line 1"

        logs = mock_manager.get_container_logs("container-123")

        mock_manager.client.get_container_logs.assert_called_once_with("container-123", tail=100)

    def test_get_container_logs_exception(self, mock_manager):
        """Test getting container logs when exception occurs"""
        mock_manager.client.get_container_logs.side_effect = Exception("Connection error")

        logs = mock_manager.get_container_logs("container-123")

        assert "Error retrieving logs" in logs


if __name__ == "__main__":
    pytest.main([__file__])

