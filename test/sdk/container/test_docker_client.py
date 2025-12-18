"""
Unit tests for docker_client.py
Tests the DockerContainerClient class with comprehensive coverage
"""

import asyncio
import os
import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
import pytest
from docker.errors import APIError, DockerException, NotFound
from fastmcp import Client

from nexent.container.docker_client import (
    DockerContainerClient,
    ContainerError,
    ContainerConnectionError,
)
from nexent.container.docker_config import DockerContainerConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_docker_config():
    """Create a mock Docker configuration"""
    config = DockerContainerConfig(docker_host="tcp://localhost:2375")
    return config


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client"""
    client = MagicMock()
    client.ping.return_value = True
    return client


@pytest.fixture
def docker_container_client(mock_docker_config, mock_docker_client):
    """Create DockerContainerClient instance with mocked Docker client"""
    with patch("nexent.container.docker_client.docker.DockerClient") as mock_docker_class:
        mock_docker_class.return_value = mock_docker_client
        client = DockerContainerClient(mock_docker_config)
        client.client = mock_docker_client
        return client


@pytest.fixture
def mock_container():
    """Create a mock Docker container"""
    container = MagicMock()
    container.id = "test-container-id"
    container.name = "mcp-test-service-tenant12-user1234"
    container.status = "running"
    container.attrs = {
        "NetworkSettings": {
            "Ports": {
                "5020/tcp": [{"HostPort": "5020"}],
            }
        },
        "Created": "2024-01-01T00:00:00Z",
        "Config": {"Image": "node:22-alpine"},
    }
    return container


# ---------------------------------------------------------------------------
# Test DockerContainerClient.__init__
# ---------------------------------------------------------------------------


class TestDockerContainerClientInit:
    """Test DockerContainerClient initialization"""

    def test_init_success(self, mock_docker_config, mock_docker_client):
        """Test successful initialization"""
        with patch("nexent.container.docker_client.docker.DockerClient") as mock_docker_class:
            mock_docker_class.return_value = mock_docker_client
            client = DockerContainerClient(mock_docker_config)
            assert client.client == mock_docker_client
            mock_docker_class.assert_called_once_with(base_url="tcp://localhost:2375")
            mock_docker_client.ping.assert_called_once()

    def test_init_docker_connection_failure(self, mock_docker_config):
        """Test initialization failure when Docker connection fails"""
        with patch("nexent.container.docker_client.docker.DockerClient") as mock_docker_class:
            mock_docker_client = MagicMock()
            mock_docker_client.ping.side_effect = DockerException("Connection failed")
            mock_docker_class.return_value = mock_docker_client

            with pytest.raises(ContainerError, match="Cannot connect to Docker"):
                DockerContainerClient(mock_docker_config)

    def test_init_docker_ping_failure(self, mock_docker_config):
        """Test initialization failure when Docker ping fails"""
        with patch("nexent.container.docker_client.docker.DockerClient") as mock_docker_class:
            mock_docker_client = MagicMock()
            mock_docker_client.ping.side_effect = Exception("Ping failed")
            mock_docker_class.return_value = mock_docker_client

            with pytest.raises(ContainerError):
                DockerContainerClient(mock_docker_config)


# ---------------------------------------------------------------------------
# Test _is_running_in_docker
# ---------------------------------------------------------------------------


class TestIsRunningInDocker:
    """Test _is_running_in_docker static method"""

    def test_is_running_in_docker_with_dockerenv(self):
        """Test detection when /.dockerenv exists"""
        def mock_exists(self):
            if str(self) == str(Path("/.dockerenv")):
                return True
            return False
        
        with patch.object(Path, "exists", mock_exists), \
             patch.dict(os.environ, {}, clear=True):
            result = DockerContainerClient._is_running_in_docker()
            assert result is True

    def test_is_running_in_docker_with_cgroup_docker(self):
        """Test detection when /proc/self/cgroup contains docker"""
        def mock_exists(self):
            if str(self) == str(Path("/.dockerenv")):
                return False
            if str(self) == str(Path("/proc/self/cgroup")):
                return True
            return False
        
        def mock_read_text(self):
            if str(self) == str(Path("/proc/self/cgroup")):
                return "1:name=systemd:/docker/12345"
            return ""
        
        with patch.object(Path, "exists", mock_exists), \
             patch.object(Path, "read_text", mock_read_text), \
             patch.dict(os.environ, {}, clear=True):
            result = DockerContainerClient._is_running_in_docker()
            assert result is True

    def test_is_running_in_docker_with_cgroup_containerd(self):
        """Test detection when /proc/self/cgroup contains containerd"""
        def mock_exists(self):
            if str(self) == str(Path("/.dockerenv")):
                return False
            if str(self) == str(Path("/proc/self/cgroup")):
                return True
            return False
        
        def mock_read_text(self):
            if str(self) == str(Path("/proc/self/cgroup")):
                return "1:name=systemd:/containerd/12345"
            return ""
        
        with patch.object(Path, "exists", mock_exists), \
             patch.object(Path, "read_text", mock_read_text), \
             patch.dict(os.environ, {}, clear=True):
            result = DockerContainerClient._is_running_in_docker()
            assert result is True

    def test_is_running_in_docker_ignores_env_var(self):
        """Test detection ignores container environment variable (SDK must not read env)"""
        def mock_exists(self):
            return False
        
        with patch.object(Path, "exists", mock_exists), \
             patch.dict(os.environ, {"container": "docker"}):
            result = DockerContainerClient._is_running_in_docker()
            assert result is False

    def test_is_running_in_docker_not_in_docker(self):
        """Test detection when not in Docker"""
        def mock_exists(self):
            return False
        
        with patch.object(Path, "exists", mock_exists), \
             patch.dict(os.environ, {}, clear=True):
            result = DockerContainerClient._is_running_in_docker()
            assert result is False

    def test_is_running_in_docker_cgroup_read_exception(self):
        """Test detection when cgroup read raises exception"""
        def mock_exists(self):
            if str(self) == str(Path("/.dockerenv")):
                return False
            if str(self) == str(Path("/proc/self/cgroup")):
                return True
            return False
        
        def mock_read_text(self):
            raise IOError("Permission denied")
        
        with patch.object(Path, "exists", mock_exists), \
             patch.object(Path, "read_text", mock_read_text), \
             patch.dict(os.environ, {}, clear=True):
            result = DockerContainerClient._is_running_in_docker()
            assert result is False

    def test_is_running_in_docker_cgroup_no_docker(self):
        """Test detection when cgroup exists but doesn't contain docker"""
        def mock_exists(self):
            if str(self) == str(Path("/.dockerenv")):
                return False
            if str(self) == str(Path("/proc/self/cgroup")):
                return True
            return False
        
        def mock_read_text(self):
            if str(self) == str(Path("/proc/self/cgroup")):
                return "1:name=systemd:/user/12345"
            return ""
        
        with patch.object(Path, "exists", mock_exists), \
             patch.object(Path, "read_text", mock_read_text), \
             patch.dict(os.environ, {}, clear=True):
            result = DockerContainerClient._is_running_in_docker()
            assert result is False


# ---------------------------------------------------------------------------
# Test _get_service_host
# ---------------------------------------------------------------------------


class TestGetServiceHost:
    """Test _get_service_host static method"""

    def test_get_service_host_in_docker(self):
        """Test host selection when running in Docker"""
        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True):
            result = DockerContainerClient._get_service_host("test-service")
            assert result == "test-service"

    def test_get_service_host_local(self):
        """Test host selection when running locally"""
        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=False):
            result = DockerContainerClient._get_service_host("test-service")
            assert result == "localhost"


# ---------------------------------------------------------------------------
# Test find_free_port
# ---------------------------------------------------------------------------


class TestFindFreePort:
    """Test find_free_port method"""

    def test_find_free_port_success(self, docker_container_client):
        """Test finding a free port successfully"""
        # Mock socket to simulate port being free (connect_ex returns non-zero)
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            mock_socket.connect_ex.return_value = 1  # Port is free
            mock_socket_class.return_value = mock_socket

            port = docker_container_client.find_free_port(start_port=5020, max_attempts=10)
            assert port == 5020

    def test_find_free_port_second_attempt(self, docker_container_client):
        """Test finding free port on second attempt"""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            # First port is in use (0), second is free (1)
            mock_socket.connect_ex.side_effect = [0, 1]
            mock_socket_class.return_value = mock_socket

            port = docker_container_client.find_free_port(start_port=5020, max_attempts=10)
            assert port == 5021

    def test_find_free_port_no_available_port(self, docker_container_client):
        """Test failure when no port is available"""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            mock_socket.connect_ex.return_value = 0  # All ports in use
            mock_socket_class.return_value = mock_socket

            with pytest.raises(ContainerError, match="No available port found"):
                docker_container_client.find_free_port(start_port=5020, max_attempts=5)

    def test_find_free_port_custom_start_port(self, docker_container_client):
        """Test finding free port with custom start port"""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            mock_socket.connect_ex.return_value = 1
            mock_socket_class.return_value = mock_socket

            port = docker_container_client.find_free_port(start_port=9000, max_attempts=10)
            assert port == 9000


# ---------------------------------------------------------------------------
# Test _generate_container_name
# ---------------------------------------------------------------------------


class TestGenerateContainerName:
    """Test _generate_container_name method"""

    def test_generate_container_name_basic(self, docker_container_client):
        """Test basic container name generation"""
        name = docker_container_client._generate_container_name("test-service", "tenant123", "user12345")
        assert name == "mcp-test-service-tenant12-user1234"

    def test_generate_container_name_with_special_chars(self, docker_container_client):
        """Test container name generation with special characters"""
        name = docker_container_client._generate_container_name("test@service#123", "tenant123", "user12345")
        assert name == "mcp-test-service-123-tenant12-user1234"
        assert "@" not in name
        assert "#" not in name

    def test_generate_container_name_long_user_id(self, docker_container_client):
        """Test container name generation with long user ID"""
        long_user_id = "a" * 20
        name = docker_container_client._generate_container_name("test-service", "tenant123", long_user_id)
        # Should only use first 8 characters of tenant_id and user_id
        assert name == f"mcp-test-service-tenant12-{long_user_id[:8]}"

    def test_generate_container_name_short_user_id(self, docker_container_client):
        """Test container name generation with short user ID"""
        name = docker_container_client._generate_container_name("test-service", "tenant123", "user")
        assert name == "mcp-test-service-tenant12-user"


# ---------------------------------------------------------------------------
# Test start_container
# ---------------------------------------------------------------------------


class TestStartContainer:
    """Test start_container method"""

    @pytest.mark.asyncio
    async def test_start_container_existing_running(self, docker_container_client, mock_container):
        """Test starting container when existing container is already running"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "existing"
            assert result["container_id"] == "test-container-id"
            assert "localhost" in result["service_url"]
            docker_container_client.client.containers.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_container_existing_stopped(self, docker_container_client, mock_container):
        """Test starting container when existing container is stopped"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "stopped"
        mock_container.remove.return_value = None

        # Mock new container creation
        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            mock_container.remove.assert_called_once_with(force=True)
            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_not_found(self, docker_container_client):
        """Test starting container when no existing container exists"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_existing_check_error(self, docker_container_client):
        """Test starting container when checking existing container raises error"""
        docker_container_client.client.containers.get.side_effect = Exception("Connection error")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_find_port_failure(self, docker_container_client):
        """Test starting container when finding free port fails"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        with patch.object(DockerContainerClient, "find_free_port", side_effect=ContainerError("No ports available")):
            with pytest.raises(ContainerError, match="No ports available"):
                await docker_container_client.start_container(
                    service_name="test-service",
                    tenant_id="tenant123",
                    user_id="user12345",
                    full_command=["npx", "-y", "test-mcp"],
                )

    @pytest.mark.asyncio
    async def test_start_container_with_env_vars(self, docker_container_client):
        """Test starting container with environment variables"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            env_vars = {"CUSTOM_VAR": "value", "ANOTHER_VAR": "another_value"}
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
                env_vars=env_vars,
            )

            # Check that containers.run was called with env vars
            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            assert "environment" in call_args.kwargs
            assert call_args.kwargs["environment"]["CUSTOM_VAR"] == "value"
            assert call_args.kwargs["environment"]["ANOTHER_VAR"] == "another_value"
            assert call_args.kwargs["environment"]["PORT"] == "5020"

    @pytest.mark.asyncio
    async def test_start_container_npx_command(self, docker_container_client):
        """Test starting container with npx full_command"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            assert call_args.kwargs["image"] == "node:22-alpine"
            assert call_args.kwargs["command"] == ["npx", "-y", "test-mcp"]

    @pytest.mark.asyncio
    async def test_start_container_node_command(self, docker_container_client):
        """Test starting container with node full_command"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["node", "script.js"],
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            assert call_args.kwargs["image"] == "node:22-alpine"

    @pytest.mark.asyncio
    async def test_start_container_python_command(self, docker_container_client):
        """Test starting container with python full_command"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["python", "script.py"],
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            # Non-node commands default to alpine:latest unless overridden
            assert call_args.kwargs["image"] == "alpine:latest"

    @pytest.mark.asyncio
    async def test_start_container_generic_command(self, docker_container_client):
        """Test starting container with generic full_command"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["custom-command", "arg1", "arg2"],
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            assert call_args.kwargs["image"] == "alpine:latest"

    @pytest.mark.asyncio
    async def test_start_container_api_error(self, docker_container_client):
        """Test starting container when Docker API error occurs"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")
        docker_container_client.client.containers.run.side_effect = APIError("API error")

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020):
            with pytest.raises(ContainerError, match="Container startup failed"):
                await docker_container_client.start_container(
                    service_name="test-service",
                    tenant_id="tenant123",
                    user_id="user12345",
                    full_command=["npx", "-y", "test-mcp"],
                )

    @pytest.mark.asyncio
    async def test_start_container_generic_exception(self, docker_container_client):
        """Test starting container when generic exception occurs"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")
        docker_container_client.client.containers.run.side_effect = Exception("Unexpected error")

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020):
            with pytest.raises(ContainerError, match="Container startup failed"):
                await docker_container_client.start_container(
                    service_name="test-service",
                    tenant_id="tenant123",
                    user_id="user12345",
                    full_command=["npx", "-y", "test-mcp"],
                )

    @pytest.mark.asyncio
    async def test_start_container_health_check_failure_container_stopped(self, docker_container_client):
        """Test starting container when health check fails and container stopped"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "stopped"
        new_container.reload.return_value = None
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", 
                         side_effect=ContainerConnectionError("Service not ready")), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerError, match="stopped unexpectedly"):
                await docker_container_client.start_container(
                    service_name="test-service",
                    tenant_id="tenant123",
                    user_id="user12345",
                    full_command=["npx", "-y", "test-mcp"],
                )

    @pytest.mark.asyncio
    async def test_start_container_health_check_failure_container_not_found(self, docker_container_client):
        """Test starting container when health check fails and container not found"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        new_container.reload.side_effect = NotFound("Container not found")
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", 
                         side_effect=ContainerConnectionError("Service not ready")), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerError, match="not found after start"):
                await docker_container_client.start_container(
                    service_name="test-service",
                    tenant_id="tenant123",
                    user_id="user12345",
                    full_command=["npx", "-y", "test-mcp"],
                )

    @pytest.mark.asyncio
    async def test_start_container_health_check_failure_but_running(self, docker_container_client):
        """Test starting container when health check fails but container is running"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        new_container.reload.return_value = None
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", 
                         side_effect=ContainerConnectionError("Service not ready")), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            # Should not raise error, just log warning
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_existing_no_port_mapping(self, docker_container_client, mock_container):
        """Test starting container when existing container has no port mapping"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {}
            }
        }

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            # Should create new container since existing one has no port
            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_npm_command(self, docker_container_client):
        """Test starting container with npm full_command"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npm", "run", "start"],
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            assert call_args.kwargs["image"] == "node:22-alpine"

    @pytest.mark.asyncio
    async def test_start_container_python3_command(self, docker_container_client):
        """Test starting container with python3 full_command"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["python3", "script.py"],
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            # Non-node commands default to alpine:latest unless overridden
            assert call_args.kwargs["image"] == "alpine:latest"

    @pytest.mark.asyncio
    async def test_start_container_bash_command(self, docker_container_client):
        """Test starting container with bash full_command"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["bash", "script.sh"],
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            # Non-node commands default to alpine:latest unless overridden
            assert call_args.kwargs["image"] == "alpine:latest"

    @pytest.mark.asyncio
    async def test_start_container_existing_empty_host_mappings(self, docker_container_client, mock_container):
        """Test starting container when existing container has empty host mappings"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": []
                }
            }
        }

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            # Should create new container since existing one has no valid port mapping
            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_existing_no_hostport(self, docker_container_client, mock_container):
        """Test starting container when existing container has port mapping but no HostPort"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{}]  # Empty dict, no HostPort
                }
            }
        }

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            # Should create new container since existing one has no HostPort
            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_existing_multiple_ports(self, docker_container_client, mock_container):
        """Test starting container when existing container has multiple port mappings"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{"HostPort": "5020"}],
                    "5021/tcp": [{"HostPort": "5021"}],
                }
            }
        }

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            # Should use existing container with first available port
            assert result["status"] == "existing"
            assert result["host_port"] == "5020"

    @pytest.mark.asyncio
    async def test_start_container_existing_no_port_mapping_with_host_port(self, docker_container_client, mock_container):
        """Test starting container when existing container has no port mapping but host_port is provided (line 228-229)"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {}  # No port mappings
            }
        }

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=False), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
                host_port=5025,  # Provide host_port parameter
            )

            # Should use existing container with provided host_port
            assert result["status"] == "existing"
            assert result["host_port"] == "5025"

    @pytest.mark.asyncio
    async def test_start_container_empty_full_command(self, docker_container_client):
        """Test starting container with empty full_command raises error (line 272-273)"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        with pytest.raises(ContainerError, match="full_command is required to start container"):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=[],  # Empty command
            )

    @pytest.mark.asyncio
    async def test_start_container_with_custom_image(self, docker_container_client):
        """Test starting container with custom image parameter (line 276-277)"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        new_container.reload.return_value = None
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port", return_value=5020), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["python", "script.py"],
                image="python:3.11-alpine",  # Custom image
            )

            call_args = docker_container_client.client.containers.run.call_args
            assert call_args is not None
            assert call_args.kwargs["image"] == "python:3.11-alpine"

    @pytest.mark.asyncio
    async def test_start_container_with_host_port_provided(self, docker_container_client):
        """Test starting container when host_port is provided (line 252 - skip find_free_port)"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        new_container.reload.return_value = None
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "find_free_port") as mock_find_port, \
             patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch.object(DockerContainerClient, "_is_running_in_docker", return_value=False):
            await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
                host_port=8080,  # Provide host_port, should skip find_free_port
            )

            # find_free_port should not be called when host_port is provided
            mock_find_port.assert_not_called()
            call_args = docker_container_client.client.containers.run.call_args
            assert call_args.kwargs["environment"]["PORT"] == "8080"


# ---------------------------------------------------------------------------
# Test _wait_for_service_ready
# ---------------------------------------------------------------------------


class TestWaitForServiceReady:
    """Test _wait_for_service_ready method"""

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_success(self, docker_container_client):
        """Test waiting for service ready successfully"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.docker_client.Client", return_value=mock_client):
            await docker_container_client._wait_for_service_ready("http://localhost:5020/mcp", max_retries=5)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_retries(self, docker_container_client):
        """Test waiting for service ready with retries"""
        mock_client = MagicMock()
        # First two attempts fail, third succeeds
        call_count = 0
        def is_connected():
            nonlocal call_count
            call_count += 1
            return call_count >= 3
        mock_client.is_connected.side_effect = is_connected
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.docker_client.Client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await docker_container_client._wait_for_service_ready("http://localhost:5020/mcp", max_retries=5, retry_delay=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_max_retries_exceeded(self, docker_container_client):
        """Test waiting for service ready when max retries exceeded"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = False
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.docker_client.Client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerConnectionError, match="Service not ready after"):
                await docker_container_client._wait_for_service_ready("http://localhost:5020/mcp", max_retries=3, retry_delay=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_exception(self, docker_container_client):
        """Test waiting for service ready when exception occurs"""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.docker_client.Client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerConnectionError):
                await docker_container_client._wait_for_service_ready("http://localhost:5020/mcp", max_retries=3, retry_delay=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_loop_iterations(self, docker_container_client):
        """Test waiting for service ready with multiple loop iterations (line 356)"""
        mock_client = MagicMock()
        # Simulate multiple failures before success to test loop
        call_count = 0
        def is_connected():
            nonlocal call_count
            call_count += 1
            return call_count >= 5  # Success on 5th attempt
        mock_client.is_connected.side_effect = is_connected
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.docker_client.Client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await docker_container_client._wait_for_service_ready("http://localhost:5020/mcp", max_retries=10, retry_delay=0.01)
            
            # Should have slept 4 times (before 5th attempt succeeds)
            assert mock_sleep.call_count == 4


# ---------------------------------------------------------------------------
# Test stop_container
# ---------------------------------------------------------------------------


class TestStopContainer:
    """Test stop_container method"""

    @pytest.mark.asyncio
    async def test_stop_container_success(self, docker_container_client, mock_container):
        """Test stopping container successfully"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.stop.return_value = None
        mock_container.remove.return_value = None

        result = await docker_container_client.stop_container("test-container-id")

        assert result is True
        mock_container.stop.assert_called_once_with(timeout=10)
        mock_container.remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_container_not_found(self, docker_container_client):
        """Test stopping container that doesn't exist"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        result = await docker_container_client.stop_container("non-existent-container")

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_container_api_error(self, docker_container_client, mock_container):
        """Test stopping container when API error occurs"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.stop.side_effect = APIError("API error")

        with pytest.raises(ContainerError, match="Failed to stop container"):
            await docker_container_client.stop_container("test-container-id")

    @pytest.mark.asyncio
    async def test_stop_container_generic_exception(self, docker_container_client, mock_container):
        """Test stopping container when generic exception occurs"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.stop.side_effect = Exception("Unexpected error")

        with pytest.raises(ContainerError, match="Failed to stop container"):
            await docker_container_client.stop_container("test-container-id")


# ---------------------------------------------------------------------------
# Test list_containers
# ---------------------------------------------------------------------------


class TestListContainers:
    """Test list_containers method"""

    def test_list_containers_no_filters(self, docker_container_client, mock_container):
        """Test listing containers without filters"""
        docker_container_client.client.containers.list.return_value = [mock_container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.list_containers()

            assert len(result) == 1
            assert result[0]["container_id"] == "test-container-id"
            assert result[0]["name"] == "mcp-test-service-tenant12-user1234"
            assert result[0]["status"] == "running"
            assert result[0]["host_port"] == "5020"

    def test_list_containers_with_tenant_filter(self, docker_container_client, mock_container):
        """Test listing containers with tenant filter"""
        docker_container_client.client.containers.list.return_value = [mock_container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            # tenant_id should match first 8 chars of user_id in container name
            result = docker_container_client.list_containers(tenant_id="user1234")

            assert len(result) == 1

    def test_list_containers_with_tenant_filter_no_match(self, docker_container_client, mock_container):
        """Test listing containers with tenant filter that doesn't match"""
        docker_container_client.client.containers.list.return_value = [mock_container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.list_containers(tenant_id="different")

            assert len(result) == 0

    def test_list_containers_with_service_filter(self, docker_container_client, mock_container):
        """Test listing containers with service filter"""
        docker_container_client.client.containers.list.return_value = [mock_container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.list_containers(service_name="test-service")

            assert len(result) == 1

    def test_list_containers_with_service_filter_no_match(self, docker_container_client, mock_container):
        """Test listing containers with service filter that doesn't match"""
        docker_container_client.client.containers.list.return_value = [mock_container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.list_containers(service_name="other-service")

            assert len(result) == 0

    def test_list_containers_with_both_filters(self, docker_container_client, mock_container):
        """Test listing containers with both tenant and service filters"""
        docker_container_client.client.containers.list.return_value = [mock_container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.list_containers(
                tenant_id="user1234",
                service_name="test-service"
            )

            assert len(result) == 1

    def test_list_containers_no_port_mapping(self, docker_container_client):
        """Test listing containers without port mapping"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "NetworkSettings": {
                "Ports": {}
            }
        }
        docker_container_client.client.containers.list.return_value = [container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.list_containers()

            assert len(result) == 1
            assert result[0]["host_port"] is None
            assert result[0]["service_url"] is None

    def test_list_containers_empty_port_mapping(self, docker_container_client):
        """Test listing containers with empty port mapping"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": []
                }
            }
        }
        docker_container_client.client.containers.list.return_value = [container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.list_containers()

            assert len(result) == 1
            assert result[0]["host_port"] is None

    def test_list_containers_host_port_none_or_empty(self, docker_container_client):
        """Test listing containers when host_port is None or empty string (line 448)"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{"HostPort": None}],  # None value
                    "5021/tcp": [{"HostPort": ""}],   # Empty string
                }
            }
        }
        docker_container_client.client.containers.list.return_value = [container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_is_running_in_docker", return_value=False):
            result = docker_container_client.list_containers()

            assert len(result) == 1
            # Should not break on None or empty HostPort
            # When HostPort is empty string, it will be returned as empty string (not None)
            # Since the last HostPort value is empty string, host_port will be empty string
            assert result[0]["host_port"] == ""

    def test_list_containers_exception(self, docker_container_client):
        """Test listing containers when exception occurs"""
        docker_container_client.client.containers.list.side_effect = Exception("Connection error")

        result = docker_container_client.list_containers()

        assert result == []

    def test_list_containers_service_filter_special_chars(self, docker_container_client, mock_container):
        """Test listing containers with service filter containing special characters"""
        docker_container_client.client.containers.list.return_value = [mock_container]

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            # Service name with special chars should be sanitized
            result = docker_container_client.list_containers(service_name="test@service#123")

            # Should match because sanitized name is "test-service-123"
            assert len(result) == 0  # Actually will not match because container name is "mcp-test-service-tenant12-user1234"


# ---------------------------------------------------------------------------
# Test get_container_logs
# ---------------------------------------------------------------------------


class TestGetContainerLogs:
    """Test get_container_logs method"""

    def test_get_container_logs_success(self, docker_container_client, mock_container):
        """Test getting container logs successfully"""
        mock_container.logs.return_value = b"Log line 1\nLog line 2\nLog line 3"
        docker_container_client.client.containers.get.return_value = mock_container

        logs = docker_container_client.get_container_logs("test-container-id", tail=100)

        assert logs == "Log line 1\nLog line 2\nLog line 3"
        mock_container.logs.assert_called_once_with(tail=100, stdout=True, stderr=True)

    def test_get_container_logs_custom_tail(self, docker_container_client, mock_container):
        """Test getting container logs with custom tail"""
        mock_container.logs.return_value = b"Log line 1\nLog line 2"
        docker_container_client.client.containers.get.return_value = mock_container

        logs = docker_container_client.get_container_logs("test-container-id", tail=50)

        mock_container.logs.assert_called_once_with(tail=50, stdout=True, stderr=True)

    def test_get_container_logs_not_found(self, docker_container_client):
        """Test getting logs for non-existent container"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        logs = docker_container_client.get_container_logs("non-existent-container")

        assert logs == ""

    def test_get_container_logs_decode_error(self, docker_container_client, mock_container):
        """Test getting container logs with decode error"""
        # Simulate binary data that can't be decoded as UTF-8
        mock_container.logs.return_value = b"\xff\xfe\x00\x01"
        docker_container_client.client.containers.get.return_value = mock_container

        logs = docker_container_client.get_container_logs("test-container-id")

        # Should handle decode error gracefully
        assert isinstance(logs, str)

    def test_get_container_logs_exception(self, docker_container_client):
        """Test getting container logs when exception occurs"""
        docker_container_client.client.containers.get.side_effect = Exception("Connection error")

        logs = docker_container_client.get_container_logs("test-container-id")

        assert "Error retrieving logs" in logs


# ---------------------------------------------------------------------------
# Test get_container_status
# ---------------------------------------------------------------------------


class TestGetContainerStatus:
    """Test get_container_status method"""

    def test_get_container_status_success(self, docker_container_client, mock_container):
        """Test getting container status successfully"""
        docker_container_client.client.containers.get.return_value = mock_container
        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.get_container_status("test-container-id")

            assert result is not None
            assert result["container_id"] == "test-container-id"
            assert result["name"] == "mcp-test-service-tenant12-user1234"
            assert result["status"] == "running"
            assert result["host_port"] == "5020"
            assert result["created"] == "2024-01-01T00:00:00Z"
            assert result["image"] == "node:22-alpine"

    def test_get_container_status_not_found(self, docker_container_client):
        """Test getting status for non-existent container"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        result = docker_container_client.get_container_status("non-existent-container")

        assert result is None

    def test_get_container_status_no_port_mapping(self, docker_container_client):
        """Test getting container status without port mapping"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "NetworkSettings": {
                "Ports": {}
            },
            "Created": "2024-01-01T00:00:00Z",
            "Config": {"Image": "node:22-alpine"},
        }
        docker_container_client.client.containers.get.return_value = container

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.get_container_status("test-container-id")

            assert result is not None
            assert result["host_port"] is None
            assert result["service_url"] is None

    def test_get_container_status_exception(self, docker_container_client):
        """Test getting container status when exception occurs"""
        docker_container_client.client.containers.get.side_effect = Exception("Connection error")

        result = docker_container_client.get_container_status("test-container-id")

        assert result is None

    def test_get_container_status_empty_port_mapping(self, docker_container_client):
        """Test getting container status with empty port mapping"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": []
                }
            },
            "Created": "2024-01-01T00:00:00Z",
            "Config": {"Image": "node:22-alpine"},
        }
        docker_container_client.client.containers.get.return_value = container

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"):
            result = docker_container_client.get_container_status("test-container-id")

            assert result is not None
            assert result["host_port"] is None

    def test_get_container_status_host_port_none_or_empty(self, docker_container_client):
        """Test getting container status when host_port is None or empty string (line 513)"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{"HostPort": None}],  # None value
                    "5021/tcp": [{"HostPort": ""}],   # Empty string
                }
            },
            "Created": "2024-01-01T00:00:00Z",
            "Config": {"Image": "node:22-alpine"},
        }
        docker_container_client.client.containers.get.return_value = container

        with patch.object(DockerContainerClient, "_get_service_host", return_value="localhost"), \
             patch.object(DockerContainerClient, "_is_running_in_docker", return_value=False):
            result = docker_container_client.get_container_status("test-container-id")

            assert result is not None
            # Should not break on None or empty HostPort
            # When HostPort is empty string, it will be returned as empty string (not None)
            # Since the last HostPort value is empty string, host_port will be empty string
            assert result["host_port"] == ""


# ---------------------------------------------------------------------------
# Test _ensure_network
# ---------------------------------------------------------------------------


class TestEnsureNetwork:
    """Test _ensure_network method"""

    def test_ensure_network_exists(self, docker_container_client):
        """Test ensuring network when it already exists"""
        mock_network = MagicMock()
        docker_container_client.client.networks.get.return_value = mock_network

        docker_container_client._ensure_network("nexent_nexent")

        docker_container_client.client.networks.get.assert_called_once_with("nexent_nexent")
        docker_container_client.client.networks.create.assert_not_called()

    def test_ensure_network_create_new(self, docker_container_client):
        """Test ensuring network when it doesn't exist"""
        docker_container_client.client.networks.get.side_effect = NotFound("Network not found")
        mock_network = MagicMock()
        docker_container_client.client.networks.create.return_value = mock_network

        docker_container_client._ensure_network("nexent_nexent")

        docker_container_client.client.networks.get.assert_called_once_with("nexent_nexent")
        docker_container_client.client.networks.create.assert_called_once_with("nexent_nexent")

    def test_ensure_network_race_condition(self, docker_container_client):
        """Test ensuring network when race condition occurs (another process creates it)"""
        # First call raises NotFound, create raises APIError, second get succeeds
        docker_container_client.client.networks.get.side_effect = [
            NotFound("Network not found"),
            MagicMock()  # Second call succeeds
        ]
        docker_container_client.client.networks.create.side_effect = APIError("Network already exists")

        docker_container_client._ensure_network("nexent_nexent")

        assert docker_container_client.client.networks.get.call_count == 2
        docker_container_client.client.networks.create.assert_called_once()

    def test_ensure_network_create_fails_then_get_fails(self, docker_container_client):
        """Test ensuring network when create fails and subsequent get also fails"""
        docker_container_client.client.networks.get.side_effect = [
            NotFound("Network not found"),
            Exception("Get failed")
        ]
        docker_container_client.client.networks.create.side_effect = APIError("Create failed")

        with pytest.raises(ContainerError, match="Failed to create or get Docker network"):
            docker_container_client._ensure_network("nexent_nexent")

    def test_ensure_network_get_api_error(self, docker_container_client):
        """Test ensuring network when get raises APIError"""
        docker_container_client.client.networks.get.side_effect = APIError("API error")

        with pytest.raises(ContainerError, match="Failed to get Docker network"):
            docker_container_client._ensure_network("nexent_nexent")


# ---------------------------------------------------------------------------
# Test _get_container_service_port
# ---------------------------------------------------------------------------


class TestGetContainerServicePort:
    """Test _get_container_service_port static method"""

    def test_get_container_service_port_from_env(self):
        """Test getting port from PORT environment variable"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": ["PORT=5020", "NODE_ENV=production"]
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port == "5020"

    def test_get_container_service_port_from_published_port(self):
        """Test getting port from published port mapping"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{"HostPort": "5020"}]
                }
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port == "5020"

    def test_get_container_service_port_env_takes_precedence(self):
        """Test that PORT env variable takes precedence over published port"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": ["PORT=5021", "NODE_ENV=production"]
            },
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{"HostPort": "5020"}]
                }
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port == "5021"

    def test_get_container_service_port_no_env_no_published(self):
        """Test getting port when neither env nor published port exists"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {}
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port is None

    def test_get_container_service_port_empty_env_list(self):
        """Test getting port when env list is empty"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": None
            },
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{"HostPort": "5020"}]
                }
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port == "5020"

    def test_get_container_service_port_env_exception(self):
        """Test getting port when env access raises exception"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": Exception("Access error")
            },
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{"HostPort": "5020"}]
                }
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port == "5020"

    def test_get_container_service_port_published_port_exception(self):
        """Test getting port when published port access raises exception"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": Exception("Access error")
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port is None

    def test_get_container_service_port_multiple_published_ports(self):
        """Test getting port when multiple published ports exist"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {
                    "5021/tcp": [{"HostPort": "5021"}],
                    "5020/tcp": [{"HostPort": "5020"}]
                }
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        # Should return first available port
        assert port in ["5020", "5021"]

    def test_get_container_service_port_empty_host_mappings(self):
        """Test getting port when host mappings are empty"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": []
                }
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port is None

    def test_get_container_service_port_no_hostport(self):
        """Test getting port when host mapping has no HostPort"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {
                    "5020/tcp": [{}]  # Empty dict, no HostPort
                }
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        assert port is None

    def test_get_container_service_port_non_string_env_item(self):
        """Test getting port when env list contains non-string items (line 131)"""
        container = MagicMock()
        container.attrs = {
            "Config": {
                "Env": [123, "PORT=5020", None, {"key": "value"}]  # Mixed types
            },
            "NetworkSettings": {
                "Ports": {}
            }
        }

        port = DockerContainerClient._get_container_service_port(container)
        # Should still find PORT=5020 despite non-string items
        assert port == "5020"


# ---------------------------------------------------------------------------
# Test start_container in Docker mode
# ---------------------------------------------------------------------------


class TestStartContainerInDocker:
    """Test start_container method when running inside Docker"""

    @pytest.mark.asyncio
    async def test_start_container_in_docker_uses_port_env(self, docker_container_client):
        """Test starting container in Docker mode uses PORT env variable"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        new_container.reload.return_value = None
        new_container.attrs = {
            "Config": {
                "Env": ["PORT=5020"]
            },
            "NetworkSettings": {
                "Ports": {}
            }
        }
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="test-service-user1234"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"
            # Should not publish ports when running in Docker
            call_args = docker_container_client.client.containers.run.call_args
            assert "ports" not in call_args.kwargs or call_args.kwargs.get("ports") is None
            # Should use container name as host
            assert "test-service-user1234" in result["service_url"]

    @pytest.mark.asyncio
    async def test_start_container_in_docker_existing_uses_port_env(self, docker_container_client, mock_container):
        """Test starting container in Docker mode when existing container uses PORT env"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Env": ["PORT=5020", "NODE_ENV=production"]
            },
            "NetworkSettings": {
                "Ports": {}  # No published ports in Docker mode
            }
        }

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="test-service-user1234"):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "existing"
            assert result["host_port"] == "5020"
            assert "test-service-user1234" in result["service_url"]

    @pytest.mark.asyncio
    async def test_start_container_in_docker_no_port_env_fallback(self, docker_container_client, mock_container):
        """Test starting container in Docker mode when no PORT env, falls back to host_port param"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {}
            }
        }

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="test-service-user1234"):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
                host_port=5021,
            )

            assert result["status"] == "existing"
            assert result["host_port"] == "5021"

    @pytest.mark.asyncio
    async def test_start_container_in_docker_default_port(self, docker_container_client):
        """Test starting container in Docker mode uses default port 5020"""
        docker_container_client.client.containers.get.side_effect = NotFound("Container not found")

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        new_container.reload.return_value = None
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="test-service-user1234"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"
            # Should use default port 5020 when running in Docker
            call_args = docker_container_client.client.containers.run.call_args
            assert call_args.kwargs["environment"]["PORT"] == "5020"
            assert "ports" not in call_args.kwargs or call_args.kwargs.get("ports") is None

    @pytest.mark.asyncio
    async def test_start_container_in_docker_existing_no_port(self, docker_container_client, mock_container):
        """Test starting container in Docker mode when existing container has no PORT env and no host_port param"""
        docker_container_client.client.containers.get.return_value = mock_container
        mock_container.status = "running"
        mock_container.attrs = {
            "Config": {
                "Env": []  # No PORT env
            },
            "NetworkSettings": {
                "Ports": {}  # No published ports
            }
        }

        new_container = MagicMock()
        new_container.id = "new-container-id"
        new_container.status = "running"
        new_container.reload.return_value = None
        docker_container_client.client.containers.run.return_value = new_container

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="test-service-user1234"), \
             patch.object(DockerContainerClient, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            # Should create new container since existing one has no port info
            result = await docker_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"
            mock_container.remove.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# Test list_containers in Docker mode
# ---------------------------------------------------------------------------


class TestListContainersInDocker:
    """Test list_containers method when running inside Docker"""

    def test_list_containers_in_docker_uses_port_env(self, docker_container_client):
        """Test listing containers in Docker mode uses PORT env variable"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "Config": {
                "Env": ["PORT=5020"]
            },
            "NetworkSettings": {
                "Ports": {}  # No published ports in Docker mode
            }
        }
        docker_container_client.client.containers.list.return_value = [container]

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="mcp-test-service-tenant12-user1234"):
            result = docker_container_client.list_containers()

            assert len(result) == 1
            assert result[0]["host_port"] == "5020"
            assert result[0]["service_url"] == "http://mcp-test-service-tenant12-user1234:5020/mcp"

    def test_list_containers_in_docker_no_port_env(self, docker_container_client):
        """Test listing containers in Docker mode when no PORT env variable"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {}
            }
        }
        docker_container_client.client.containers.list.return_value = [container]

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="mcp-test-service-tenant12-user1234"):
            result = docker_container_client.list_containers()

            assert len(result) == 1
            assert result[0]["host_port"] is None
            assert result[0]["service_url"] is None


# ---------------------------------------------------------------------------
# Test get_container_status in Docker mode
# ---------------------------------------------------------------------------


class TestGetContainerStatusInDocker:
    """Test get_container_status method when running inside Docker"""

    def test_get_container_status_in_docker_uses_port_env(self, docker_container_client):
        """Test getting container status in Docker mode uses PORT env variable"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "Config": {
                "Env": ["PORT=5020"],
                "Image": "node:22-alpine"
            },
            "NetworkSettings": {
                "Ports": {}
            },
            "Created": "2024-01-01T00:00:00Z",
        }
        docker_container_client.client.containers.get.return_value = container

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="mcp-test-service-tenant12-user1234"):
            result = docker_container_client.get_container_status("test-container-id")

            assert result is not None
            assert result["host_port"] == "5020"
            assert result["service_url"] == "http://mcp-test-service-tenant12-user1234:5020/mcp"

    def test_get_container_status_in_docker_no_port_env(self, docker_container_client):
        """Test getting container status in Docker mode when no PORT env variable"""
        container = MagicMock()
        container.id = "test-container-id"
        container.name = "mcp-test-service-tenant12-user1234"
        container.status = "running"
        container.attrs = {
            "Config": {
                "Env": []
            },
            "NetworkSettings": {
                "Ports": {}
            },
            "Created": "2024-01-01T00:00:00Z",
            "Config": {"Image": "node:22-alpine"},
        }
        docker_container_client.client.containers.get.return_value = container

        with patch.object(DockerContainerClient, "_is_running_in_docker", return_value=True), \
             patch.object(DockerContainerClient, "_get_service_host", return_value="mcp-test-service-tenant12-user1234"):
            result = docker_container_client.get_container_status("test-container-id")

            assert result is not None
            assert result["host_port"] is None
            assert result["service_url"] is None

