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
    container.name = "mcp-test-service-user12345"
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
        name = docker_container_client._generate_container_name("test-service", "user12345")
        assert name == "test-service-user1234"

    def test_generate_container_name_with_special_chars(self, docker_container_client):
        """Test container name generation with special characters"""
        name = docker_container_client._generate_container_name("test@service#123", "user12345")
        assert name == "test-service-123-user1234"
        assert "@" not in name
        assert "#" not in name

    def test_generate_container_name_long_user_id(self, docker_container_client):
        """Test container name generation with long user ID"""
        long_user_id = "a" * 20
        name = docker_container_client._generate_container_name("test-service", long_user_id)
        # Should only use first 8 characters of user_id
        assert name == f"test-service-{long_user_id[:8]}"

    def test_generate_container_name_short_user_id(self, docker_container_client):
        """Test container name generation with short user ID"""
        name = docker_container_client._generate_container_name("test-service", "user")
        assert name == "test-service-user"


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
            assert result[0]["name"] == "mcp-test-service-user12345"
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
        container.name = "mcp-test-service-user12345"
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
        container.name = "mcp-test-service-user12345"
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
            assert len(result) == 0  # Actually won't match because container name is "mcp-test-service-user12345"


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
            assert result["name"] == "mcp-test-service-user12345"
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
        container.name = "mcp-test-service-user12345"
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
        container.name = "mcp-test-service-user12345"
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

