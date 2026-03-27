"""
Unit tests for k8s_client.py
Tests the KubernetesContainerClient class with comprehensive coverage
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch
import pytest
from kubernetes.client.exceptions import ApiException

from nexent.container.k8s_client import (
    KubernetesContainerClient,
    ContainerError,
    ContainerConnectionError,
)
from nexent.container.k8s_config import KubernetesContainerConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_k8s_config():
    """Create a mock Kubernetes configuration"""
    config = KubernetesContainerConfig(
        namespace="test-namespace",
        kubeconfig_path=None,
        in_cluster=False,
        service_port=5020,
    )
    return config


@pytest.fixture
def mock_core_v1_api():
    """Create a mock CoreV1Api"""
    api = MagicMock()
    api.list_namespaced_pod.return_value = MagicMock(items=[])
    return api


@pytest.fixture
def mock_apps_v1_api():
    """Create a mock AppsV1Api"""
    api = MagicMock()
    return api


@pytest.fixture
def k8s_container_client(mock_k8s_config, mock_core_v1_api, mock_apps_v1_api):
    """Create KubernetesContainerClient instance with mocked API"""
    with patch("nexent.container.k8s_client.client.CoreV1Api", return_value=mock_core_v1_api), \
         patch("nexent.container.k8s_client.client.AppsV1Api", return_value=mock_apps_v1_api), \
         patch("nexent.container.k8s_client.kubernetes.config.load_kube_config"):
        client = KubernetesContainerClient(mock_k8s_config)
        client.core_v1 = mock_core_v1_api
        client.apps_v1 = mock_apps_v1_api
        return client


@pytest.fixture
def mock_pod():
    """Create a mock Kubernetes Pod"""
    pod = MagicMock()
    pod.metadata = MagicMock()
    pod.metadata.uid = "test-pod-uid-12345"
    pod.metadata.name = "mcp-test-service-tenant12-user1234"
    pod.metadata.labels = {
        "app": "nexent-mcp",
        "component": "test-service",
        "tenant": "tenant12",
        "user": "user1234",
    }
    pod.metadata.creation_timestamp = MagicMock()
    pod.metadata.creation_timestamp.isoformat.return_value = "2024-01-01T00:00:00Z"
    pod.status = MagicMock()
    pod.status.phase = "Running"
    pod.status.container_statuses = [
        MagicMock(ready=True),
    ]
    pod.spec = MagicMock()
    container = MagicMock()
    container.ports = [MagicMock(container_port=5020)]
    container.image = "node:22-alpine"
    container.env = [
        MagicMock(name="PORT", value="5020"),
    ]
    pod.spec.containers = [container]
    return pod


# ---------------------------------------------------------------------------
# Test KubernetesContainerClient.__init__
# ---------------------------------------------------------------------------


class TestKubernetesContainerClientInit:
    """Test KubernetesContainerClient initialization"""

    def test_init_with_in_cluster(self):
        """Test initialization with in_cluster config"""
        config = KubernetesContainerConfig(
            namespace="test-namespace",
            in_cluster=True,
            service_port=5020,
        )
        mock_core_v1 = MagicMock()
        mock_apps_v1 = MagicMock()

        with patch("nexent.container.k8s_client.client.CoreV1Api", return_value=mock_core_v1), \
             patch("nexent.container.k8s_client.client.AppsV1Api", return_value=mock_apps_v1), \
             patch("nexent.container.k8s_client.kubernetes.config.load_incluster_config"):
            client = KubernetesContainerClient(config)
            assert client.core_v1 == mock_core_v1
            assert client.apps_v1 == mock_apps_v1
            mock_core_v1.list_namespaced_pod.assert_called_once_with(namespace="test-namespace", limit=1)

    def test_init_with_kubeconfig_path(self):
        """Test initialization with kubeconfig_path"""
        config = KubernetesContainerConfig(
            namespace="test-namespace",
            kubeconfig_path={"clusters": [], "contexts": [], "users": []},
            service_port=5020,
        )
        mock_core_v1 = MagicMock()
        mock_apps_v1 = MagicMock()

        with patch("nexent.container.k8s_client.client.CoreV1Api", return_value=mock_core_v1), \
             patch("nexent.container.k8s_client.client.AppsV1Api", return_value=mock_apps_v1), \
             patch("nexent.container.k8s_client.kubernetes.config.load_kube_config_from_dict"):
            client = KubernetesContainerClient(config)
            assert client.core_v1 == mock_core_v1
            assert client.apps_v1 == mock_apps_v1

    def test_init_with_default_config(self):
        """Test initialization with default config"""
        config = KubernetesContainerConfig(
            namespace="test-namespace",
            service_port=5020,
        )
        mock_core_v1 = MagicMock()
        mock_apps_v1 = MagicMock()

        with patch("nexent.container.k8s_client.client.CoreV1Api", return_value=mock_core_v1), \
             patch("nexent.container.k8s_client.client.AppsV1Api", return_value=mock_apps_v1), \
             patch("nexent.container.k8s_client.kubernetes.config.load_kube_config"):
            client = KubernetesContainerClient(config)
            assert client.core_v1 == mock_core_v1
            assert client.apps_v1 == mock_apps_v1

    def test_init_connection_failure(self):
        """Test initialization failure when Kubernetes connection fails"""
        config = KubernetesContainerConfig(
            namespace="test-namespace",
            service_port=5020,
        )
        # Create mock API instance with failing method
        mock_core_v1 = MagicMock()
        mock_core_v1.list_namespaced_pod.side_effect = Exception("Connection failed")

        with patch("nexent.container.k8s_client.client.CoreV1Api", return_value=mock_core_v1), \
             patch("nexent.container.k8s_client.client.AppsV1Api"), \
             patch("nexent.container.k8s_client.kubernetes.config.load_kube_config"):
            with pytest.raises(ContainerError, match="Cannot connect to Kubernetes"):
                KubernetesContainerClient(config)


# ---------------------------------------------------------------------------
# Test _generate_pod_name
# ---------------------------------------------------------------------------


class TestGeneratePodName:
    """Test _generate_pod_name method"""

    def test_generate_pod_name_basic(self, k8s_container_client):
        """Test basic pod name generation"""
        name = k8s_container_client._generate_pod_name(
            "test-service", "tenant123", "user12345")
        assert name == "mcp-test-service-tenant12-user1234"  # user_id truncated to 8 chars

    def test_generate_pod_name_with_special_chars(self, k8s_container_client):
        """Test pod name generation with special characters"""
        name = k8s_container_client._generate_pod_name(
            "test@service#123", "tenant123", "user12345")
        assert name == "mcp-test-service-123-tenant12-user1234"  # user_id truncated to 8 chars
        assert "@" not in name
        assert "#" not in name

    def test_generate_pod_name_long_user_id(self, k8s_container_client):
        """Test pod name generation with long user ID"""
        long_user_id = "a" * 20
        name = k8s_container_client._generate_pod_name(
            "test-service", "tenant123", long_user_id)
        # Should only use first 8 characters of tenant_id and user_id
        assert name == f"mcp-test-service-tenant12-{long_user_id[:8]}"

    def test_generate_pod_name_short_user_id(self, k8s_container_client):
        """Test pod name generation with short user ID"""
        name = k8s_container_client._generate_pod_name(
            "test-service", "tenant123", "user")
        assert name == "mcp-test-service-tenant12-user"

    def test_generate_pod_name_empty_tenant(self, k8s_container_client):
        """Test pod name generation with empty tenant_id"""
        name = k8s_container_client._generate_pod_name(
            "test-service", "", "user12345")
        assert name == "mcp-test-service--user1234"  # user_id truncated to 8 chars

    def test_generate_pod_name_empty_user(self, k8s_container_client):
        """Test pod name generation with empty user_id"""
        name = k8s_container_client._generate_pod_name(
            "test-service", "tenant123", "")
        assert name == "mcp-test-service-tenant12-"

    def test_generate_pod_name_none_tenant(self, k8s_container_client):
        """Test pod name generation with None tenant_id"""
        name = k8s_container_client._generate_pod_name(
            "test-service", None, "user12345")
        assert name == "mcp-test-service--user1234"  # user_id truncated to 8 chars

    def test_generate_pod_name_none_user(self, k8s_container_client):
        """Test pod name generation with None user_id"""
        name = k8s_container_client._generate_pod_name(
            "test-service", "tenant123", None)
        assert name == "mcp-test-service-tenant12-"


# ---------------------------------------------------------------------------
# Test _get_labels
# ---------------------------------------------------------------------------


class TestGetLabels:
    """Test _get_labels method"""

    def test_get_labels_basic(self, k8s_container_client):
        """Test basic label generation"""
        labels = k8s_container_client._get_labels("test-service", "tenant123", "user12345")
        assert labels["app"] == "nexent-mcp"
        assert labels["component"] == "test-service"
        assert labels["tenant"] == "tenant12"  # First 8 chars
        assert labels["user"] == "user1234"  # First 8 chars

    def test_get_labels_empty_ids(self, k8s_container_client):
        """Test label generation with empty IDs"""
        labels = k8s_container_client._get_labels("test-service", "", "")
        assert labels["app"] == "nexent-mcp"
        assert labels["component"] == "test-service"
        assert labels["tenant"] == ""
        assert labels["user"] == ""

    def test_get_labels_long_ids(self, k8s_container_client):
        """Test label generation with long IDs (truncation)"""
        labels = k8s_container_client._get_labels(
            "test-service", "a" * 20, "b" * 20)
        assert labels["tenant"] == "a" * 8
        assert labels["user"] == "b" * 8


# ---------------------------------------------------------------------------
# Test _find_free_port
# ---------------------------------------------------------------------------


class TestFindFreePort:
    """Test _find_free_port method"""

    def test_find_free_port_success(self, k8s_container_client):
        """Test finding a free port successfully"""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            mock_socket.connect_ex.return_value = 1  # Port is free (non-zero)
            mock_socket_class.return_value = mock_socket

            port = k8s_container_client._find_free_port(start_port=5020, max_attempts=10)
            assert port == 5020

    def test_find_free_port_second_attempt(self, k8s_container_client):
        """Test finding free port on second attempt"""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            # First port is in use (0), second is free (1)
            mock_socket.connect_ex.side_effect = [0, 1]
            mock_socket_class.return_value = mock_socket

            port = k8s_container_client._find_free_port(start_port=5020, max_attempts=10)
            assert port == 5021

    def test_find_free_port_no_available_port(self, k8s_container_client):
        """Test failure when no port is available"""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            mock_socket.connect_ex.return_value = 0  # All ports in use
            mock_socket_class.return_value = mock_socket

            with pytest.raises(ContainerError, match="No available port found"):
                k8s_container_client._find_free_port(start_port=5020, max_attempts=5)

    def test_find_free_port_custom_start_port(self, k8s_container_client):
        """Test finding free port with custom start port"""
        with patch("socket.socket") as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket.__enter__ = Mock(return_value=mock_socket)
            mock_socket.__exit__ = Mock(return_value=False)
            mock_socket.connect_ex.return_value = 1
            mock_socket_class.return_value = mock_socket

            port = k8s_container_client._find_free_port(start_port=9000, max_attempts=10)
            assert port == 9000


# ---------------------------------------------------------------------------
# Test _get_pod_port_from_env
# ---------------------------------------------------------------------------


class TestGetPodPortFromEnv:
    """Test _get_pod_port_from_env method"""

    def test_get_pod_port_from_env_found(self, k8s_container_client, mock_pod):
        """Test getting port from environment when found"""
        # Ensure container.env is properly configured with spec
        container = MagicMock()
        port_env_var = MagicMock(spec=['name', 'value'])
        port_env_var.name = "PORT"
        port_env_var.value = "5020"
        container.env = [port_env_var]
        mock_pod.spec.containers = [container]

        port = k8s_container_client._get_pod_port_from_env(mock_pod)
        assert port == "5020"

    def test_get_pod_port_from_env_not_found(self, k8s_container_client):
        """Test getting port when PORT env is not set"""
        pod = MagicMock()
        pod.spec = MagicMock()
        container = MagicMock()
        container.env = [
            MagicMock(name="OTHER_VAR", value="value"),
        ]
        pod.spec.containers = [container]
        port = k8s_container_client._get_pod_port_from_env(pod)
        assert port is None

    def test_get_pod_port_from_env_no_containers(self, k8s_container_client):
        """Test getting port when pod has no containers"""
        pod = MagicMock()
        pod.spec = None
        port = k8s_container_client._get_pod_port_from_env(pod)
        assert port is None

    def test_get_pod_port_from_env_empty_containers(self, k8s_container_client):
        """Test getting port when containers list is empty"""
        pod = MagicMock()
        pod.spec = MagicMock()
        pod.spec.containers = []
        port = k8s_container_client._get_pod_port_from_env(pod)
        assert port is None

    def test_get_pod_port_from_env_container_no_env(self, k8s_container_client):
        """Test getting port when container has no env vars"""
        pod = MagicMock()
        pod.spec = MagicMock()
        container = MagicMock()
        container.env = []
        pod.spec.containers = [container]
        port = k8s_container_client._get_pod_port_from_env(pod)
        assert port is None

    def test_get_pod_port_from_env_exception(self, k8s_container_client):
        """Test getting port when exception occurs"""
        pod = MagicMock()
        pod.spec = MagicMock(side_effect=Exception("Access error"))
        port = k8s_container_client._get_pod_port_from_env(pod)
        assert port is None


# ---------------------------------------------------------------------------
# Test _get_service_url
# ---------------------------------------------------------------------------


class TestGetServiceUrl:
    """Test _get_service_url method"""

    def test_get_service_url_with_host_port(self, k8s_container_client):
        """Test getting service URL with host port"""
        url = k8s_container_client._get_service_url("test-pod", host_port=8080)
        assert url == "http://test-pod:8080/mcp"

    def test_get_service_url_without_host_port(self, k8s_container_client):
        """Test getting service URL without host port (uses config default)"""
        url = k8s_container_client._get_service_url("test-pod")
        assert url == "http://test-pod:5020/mcp"


# ---------------------------------------------------------------------------
# Test _create_pod_service
# ---------------------------------------------------------------------------


class TestCreatePodService:
    """Test _create_pod_service method"""

    def test_create_pod_service(self, k8s_container_client):
        """Test creating a pod service"""
        mock_labels = {"app": "nexent-mcp", "component": "test"}
        mock_service = MagicMock()
        k8s_container_client.core_v1.create_namespaced_service.return_value = mock_service

        result = k8s_container_client._create_pod_service(
            "test-pod", "test-namespace", 5020, mock_labels)

        k8s_container_client.core_v1.create_namespaced_service.assert_called_once()
        call_args = k8s_container_client.core_v1.create_namespaced_service.call_args
        assert call_args.kwargs["namespace"] == "test-namespace"
        assert call_args.kwargs["body"].metadata.name == "test-pod"
        assert call_args.kwargs["body"].spec.ports[0].port == 5020


# ---------------------------------------------------------------------------
# Test start_container
# ---------------------------------------------------------------------------


class TestStartContainer:
    """Test start_container method"""

    @pytest.mark.asyncio
    async def test_start_container_existing_running(self):
        """Test starting container when existing pod is already running"""
        # Create mock API first
        mock_core_v1 = MagicMock()
        mock_apps_v1 = MagicMock()

        # Create pod with matching name (pod_name is generated, not from fixture)
        pod_name = "mcp-test-service-tenant12-user1234"
        mock_pod = MagicMock()
        mock_pod.metadata = MagicMock()
        mock_pod.metadata.uid = "test-pod-uid-12345"
        mock_pod.metadata.name = pod_name
        mock_pod.status = MagicMock()
        mock_pod.status.phase = "Running"
        mock_pod.status.container_statuses = [MagicMock(ready=True)]
        mock_core_v1.read_namespaced_pod.return_value = mock_pod

        config = KubernetesContainerConfig(
            namespace="test-namespace",
            service_port=5020,
        )

        with patch("nexent.container.k8s_client.client.CoreV1Api", return_value=mock_core_v1), \
             patch("nexent.container.k8s_client.client.AppsV1Api", return_value=mock_apps_v1), \
             patch("nexent.container.k8s_client.kubernetes.config.load_kube_config"):
            client = KubernetesContainerClient(config)
            client.core_v1 = mock_core_v1
            client.apps_v1 = mock_apps_v1

            result = await client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "existing"
            assert result["container_id"] == "test-pod-uid-12345"
            assert result["service_url"] == f"http://{pod_name}:5020/mcp"
            mock_core_v1.read_namespaced_pod.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_container_existing_not_running(self, k8s_container_client, mock_pod):
        """Test starting container when existing pod is not running"""
        mock_pod.status.phase = "Pending"
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        # Mock the new pod that will be created
        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            k8s_container_client.core_v1.delete_namespaced_pod.assert_called_once()
            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_not_found(self, k8s_container_client):
        """Test starting container when no existing pod exists"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            result = await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_api_exception_non_404(self, k8s_container_client):
        """Test starting container when API exception is non-404"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=500)

        with pytest.raises(ContainerError, match="Failed to check existing pod"):
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

    @pytest.mark.asyncio
    async def test_start_container_with_env_vars(self, k8s_container_client):
        """Test starting container with environment variables"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            env_vars = {"CUSTOM_VAR": "value", "ANOTHER_VAR": "another_value"}
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
                env_vars=env_vars,
            )

            call_args = k8s_container_client.core_v1.create_namespaced_pod.call_args
            assert call_args is not None
            env_names = [e.name for e in call_args.kwargs["body"].spec.containers[0].env]
            assert "PORT" in env_names
            assert "TRANSPORT" in env_names
            assert "NODE_ENV" in env_names
            assert "CUSTOM_VAR" in env_names
            assert "ANOTHER_VAR" in env_names

    @pytest.mark.asyncio
    async def test_start_container_npx_command(self, k8s_container_client):
        """Test starting container with npx command uses node image"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            call_args = k8s_container_client.core_v1.create_namespaced_pod.call_args
            assert call_args.kwargs["body"].spec.containers[0].image == "node:22-alpine"

    @pytest.mark.asyncio
    async def test_start_container_node_command(self, k8s_container_client):
        """Test starting container with node command uses node image"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["node", "script.js"],
            )

            call_args = k8s_container_client.core_v1.create_namespaced_pod.call_args
            assert call_args.kwargs["body"].spec.containers[0].image == "node:22-alpine"

    @pytest.mark.asyncio
    async def test_start_container_python_command(self, k8s_container_client):
        """Test starting container with python command uses alpine image"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["python", "script.py"],
            )

            call_args = k8s_container_client.core_v1.create_namespaced_pod.call_args
            assert call_args.kwargs["body"].spec.containers[0].image == "alpine:latest"

    @pytest.mark.asyncio
    async def test_start_container_custom_image(self, k8s_container_client):
        """Test starting container with custom image"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["python", "script.py"],
                image="python:3.11-alpine",
            )

            call_args = k8s_container_client.core_v1.create_namespaced_pod.call_args
            assert call_args.kwargs["body"].spec.containers[0].image == "python:3.11-alpine"

    @pytest.mark.asyncio
    async def test_start_container_with_host_port(self, k8s_container_client):
        """Test starting container with provided host port"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port") as mock_find_port, \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
                host_port=8080,
            )

            mock_find_port.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_container_api_exception_on_create(self, k8s_container_client):
        """Test starting container when API exception occurs during pod creation"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)
        k8s_container_client.core_v1.create_namespaced_pod.side_effect = ApiException(status=500)

        with patch.object(k8s_container_client, "_find_free_port", return_value=5020):
            with pytest.raises(ContainerError, match="Pod startup failed"):
                await k8s_container_client.start_container(
                    service_name="test-service",
                    tenant_id="tenant123",
                    user_id="user12345",
                    full_command=["npx", "-y", "test-mcp"],
                )

    @pytest.mark.asyncio
    async def test_start_container_generic_exception_on_create(self, k8s_container_client):
        """Test starting container when generic exception occurs during pod creation"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)
        k8s_container_client.core_v1.create_namespaced_pod.side_effect = Exception("Unexpected error")

        with patch.object(k8s_container_client, "_find_free_port", return_value=5020):
            with pytest.raises(ContainerError, match="Pod startup failed"):
                await k8s_container_client.start_container(
                    service_name="test-service",
                    tenant_id="tenant123",
                    user_id="user12345",
                    full_command=["npx", "-y", "test-mcp"],
                )

    @pytest.mark.asyncio
    async def test_start_container_service_health_check_fails(self, k8s_container_client):
        """Test starting container when service health check fails"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready",
                          new_callable=AsyncMock, side_effect=ContainerConnectionError("Service not ready")), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            # Should not raise, just log warning
            result = await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
            )

            assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_start_container_with_authorization_token(self, k8s_container_client):
        """Test starting container with authorization_token in env_vars"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        new_pod = MagicMock()
        new_pod.metadata.uid = "new-pod-uid"
        new_pod.metadata.name = "mcp-test-service-tenant12-user12"

        with patch.object(k8s_container_client, "_wait_for_pod_ready", new_callable=AsyncMock, return_value=new_pod), \
             patch.object(k8s_container_client, "_find_free_port", return_value=5020), \
             patch.object(k8s_container_client, "_create_pod_service", return_value=MagicMock()), \
             patch.object(k8s_container_client, "_wait_for_service_ready", new_callable=AsyncMock) as mock_wait, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            env_vars = {"authorization_token": "test-token-123"}
            await k8s_container_client.start_container(
                service_name="test-service",
                tenant_id="tenant123",
                user_id="user12345",
                full_command=["npx", "-y", "test-mcp"],
                env_vars=env_vars,
            )

            # Verify authorization_token is passed to _wait_for_service_ready
            mock_wait.assert_called_once()
            call_kwargs = mock_wait.call_args.kwargs
            assert call_kwargs["authorization_token"] == "test-token-123"


# ---------------------------------------------------------------------------
# Test _wait_for_pod_ready
# ---------------------------------------------------------------------------


class TestWaitForPodReady:
    """Test _wait_for_pod_ready method"""

    @pytest.mark.asyncio
    async def test_wait_for_pod_ready_success(self, k8s_container_client, mock_pod):
        """Test waiting for pod ready successfully"""
        mock_pod.status.phase = "Running"
        mock_pod.status.container_statuses = [MagicMock(ready=True)]
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        result = await k8s_container_client._wait_for_pod_ready("test-pod", "test-namespace")

        assert result == mock_pod

    @pytest.mark.asyncio
    async def test_wait_for_pod_ready_timeout(self, k8s_container_client):
        """Test waiting for pod ready when timeout occurs"""
        mock_pod = MagicMock()
        mock_pod.status.phase = "Pending"
        mock_pod.status.container_statuses = []
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerError, match="did not become ready within"):
                await k8s_container_client._wait_for_pod_ready(
                    "test-pod", "test-namespace", timeout=2)

    @pytest.mark.asyncio
    async def test_wait_for_pod_ready_404_then_success(self, k8s_container_client, mock_pod):
        """Test waiting for pod ready when pod is not found then found"""
        mock_pod.status.phase = "Running"
        mock_pod.status.container_statuses = [MagicMock(ready=True)]

        # First two calls return 404, then return the pod
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = [
            ApiException(status=404),
            ApiException(status=404),
            mock_pod,
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await k8s_container_client._wait_for_pod_ready("test-pod", "test-namespace")

            assert result == mock_pod

    @pytest.mark.asyncio
    async def test_wait_for_pod_ready_api_exception_non_404(self, k8s_container_client):
        """Test waiting for pod ready when API exception is non-404"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=500)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerError, match="Failed to wait for pod"):
                await k8s_container_client._wait_for_pod_ready("test-pod", "test-namespace")

    @pytest.mark.asyncio
    async def test_wait_for_pod_ready_not_running_phase(self, k8s_container_client, mock_pod):
        """Test waiting for pod ready when pod phase is not Running"""
        mock_pod.status.phase = "Pending"
        mock_pod.status.container_statuses = []
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerError, match="did not become ready within"):
                await k8s_container_client._wait_for_pod_ready(
                    "test-pod", "test-namespace", timeout=2)

    @pytest.mark.asyncio
    async def test_wait_for_pod_ready_container_not_ready(self, k8s_container_client, mock_pod):
        """Test waiting for pod ready when container is not ready"""
        mock_pod.status.phase = "Running"
        mock_pod.status.container_statuses = [MagicMock(ready=False)]
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerError, match="did not become ready within"):
                await k8s_container_client._wait_for_pod_ready(
                    "test-pod", "test-namespace", timeout=2)


# ---------------------------------------------------------------------------
# Test _wait_for_service_ready
# ---------------------------------------------------------------------------


class TestWaitForServiceReady:
    """Test _wait_for_service_ready method"""

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_success_mcp(self, k8s_container_client):
        """Test waiting for service ready successfully with /mcp endpoint"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client):
            await k8s_container_client._wait_for_service_ready("http://localhost:5020/mcp")

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_success_sse(self, k8s_container_client):
        """Test waiting for service ready successfully with /sse endpoint"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client):
            await k8s_container_client._wait_for_service_ready("http://localhost:5020/sse")

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_success_other_url(self, k8s_container_client):
        """Test waiting for service ready with non-standard URL"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client):
            await k8s_container_client._wait_for_service_ready("http://localhost:5020/custom")

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_retries(self, k8s_container_client):
        """Test waiting for service ready with retries"""
        mock_client = MagicMock()
        call_count = 0

        def is_connected():
            nonlocal call_count
            call_count += 1
            return call_count >= 3
        mock_client.is_connected.side_effect = is_connected
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await k8s_container_client._wait_for_service_ready(
                "http://localhost:5020/mcp", max_retries=5, retry_delay=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_max_retries_exceeded(self, k8s_container_client):
        """Test waiting for service ready when max retries exceeded"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = False
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerConnectionError, match="Service not ready after"):
                await k8s_container_client._wait_for_service_ready(
                    "http://localhost:5020/mcp", max_retries=3, retry_delay=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_exception(self, k8s_container_client):
        """Test waiting for service ready when exception occurs"""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ContainerConnectionError):
                await k8s_container_client._wait_for_service_ready(
                    "http://localhost:5020/mcp", max_retries=3, retry_delay=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_with_auth(self, k8s_container_client):
        """Test waiting for service ready with authorization token"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client) as mock_client_class:
            await k8s_container_client._wait_for_service_ready(
                "http://localhost:5020/mcp", authorization_token="test-token")

            # Verify Client was called with authorization header
            # Check that transport was created with headers containing Authorization
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args
            # The transport is the first positional or keyword argument
            if call_args.kwargs:
                transport = list(call_args.kwargs.values())[0]
            else:
                transport = call_args.args[0] if call_args.args else None

            if transport:
                # Verify headers attribute exists and contains Authorization
                assert hasattr(transport, 'headers') or hasattr(transport, '_headers')
                headers = getattr(transport, 'headers', None) or getattr(transport, '_headers', {})
                assert headers.get("Authorization") == "test-token" or "Authorization" in str(headers)

    @pytest.mark.asyncio
    async def test_wait_for_service_ready_url_stripped(self, k8s_container_client):
        """Test waiting for service ready with URL containing whitespace"""
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("nexent.container.k8s_client.Client", return_value=mock_client):
            await k8s_container_client._wait_for_service_ready("  http://localhost:5020/mcp  ")


# ---------------------------------------------------------------------------
# Test stop_container
# ---------------------------------------------------------------------------


class TestStopContainer:
    """Test stop_container method"""

    @pytest.mark.asyncio
    async def test_stop_container_success(self, k8s_container_client):
        """Test stopping container successfully"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        # Mock the wait for deletion
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = [
            mock_pod,  # First call finds pod
            ApiException(status=404),  # After deletion, returns 404
        ]

        result = await k8s_container_client.stop_container("test-pod")

        assert result is True
        k8s_container_client.core_v1.delete_namespaced_pod.assert_called()

    @pytest.mark.asyncio
    async def test_stop_container_not_found_by_name(self, k8s_container_client):
        """Test stopping container when pod is not found by name but found by UID"""
        # First call (by name) returns 404
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        # List returns a pod with matching UID
        mock_pod = MagicMock()
        mock_pod.metadata.uid = "test-pod"
        mock_pod.metadata.name = "mcp-real-pod-name"
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        # Mock wait for deletion
        k8s_container_client.core_v1.delete_namespaced_pod.return_value = None

        # After deletion check - first finds pod, then 404
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = [
            ApiException(status=404),  # First check for name (404)
            ApiException(status=404),  # After deletion, 404
        ]

        result = await k8s_container_client.stop_container("test-pod")

        assert result is True

    @pytest.mark.asyncio
    async def test_stop_container_not_found_at_all(self, k8s_container_client):
        """Test stopping container that doesn't exist at all"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[])

        result = await k8s_container_client.stop_container("non-existent-pod")

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_container_api_exception_non_404_on_read(self, k8s_container_client):
        """Test stopping container when API exception is non-404 on read"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=500)

        with pytest.raises(ContainerError, match="Failed to stop pod"):
            await k8s_container_client.stop_container("test-pod")

    @pytest.mark.asyncio
    async def test_stop_container_api_exception_on_delete(self, k8s_container_client):
        """Test stopping container when API exception occurs on delete"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod
        k8s_container_client.core_v1.delete_namespaced_pod.side_effect = ApiException(status=500)

        with pytest.raises(ContainerError, match="Failed to stop pod"):
            await k8s_container_client.stop_container("test-pod")

    @pytest.mark.asyncio
    async def test_stop_container_generic_exception(self, k8s_container_client):
        """Test stopping container when generic exception occurs"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod
        k8s_container_client.core_v1.delete_namespaced_pod.side_effect = Exception("Unexpected error")

        with pytest.raises(ContainerError, match="Failed to stop pod"):
            await k8s_container_client.stop_container("test-pod")

    @pytest.mark.asyncio
    async def test_stop_container_wait_timeout(self, k8s_container_client):
        """Test stopping container when wait for deletion times out"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        # Always return the pod (never 404), simulating timeout scenario
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        # Mock asyncio.sleep to be fast
        with patch("nexent.container.k8s_client.asyncio.sleep", new_callable=AsyncMock):
            result = await k8s_container_client.stop_container("test-pod")

        # Should return True even if pod is not fully deleted after timeout
        assert result is True

    @pytest.mark.asyncio
    async def test_stop_container_deletes_service(self, k8s_container_client):
        """Test stopping container also deletes associated service"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        # Mock the wait for deletion
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = [
            mock_pod,  # First call finds pod
            ApiException(status=404),  # After deletion, returns 404
        ]

        # Mock service deletion - first call succeeds, second returns 404 (already deleted)
        k8s_container_client.core_v1.delete_namespaced_service.side_effect = [
            MagicMock(),
            ApiException(status=404),
        ]

        result = await k8s_container_client.stop_container("test-pod")

        assert result is True
        k8s_container_client.core_v1.delete_namespaced_service.assert_called()

    @pytest.mark.asyncio
    async def test_stop_container_service_delete_non_404_exception(self, k8s_container_client):
        """Test stopping container when service delete fails with non-404"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        # Mock the wait for deletion
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = [
            mock_pod,  # First call finds pod
            ApiException(status=404),  # After deletion, returns 404
        ]

        # Mock service deletion - non-404 error
        k8s_container_client.core_v1.delete_namespaced_service.side_effect = ApiException(status=500)

        result = await k8s_container_client.stop_container("test-pod")

        # Should still return True (just log warning)
        assert result is True


# ---------------------------------------------------------------------------
# Test remove_container
# ---------------------------------------------------------------------------


class TestRemoveContainer:
    """Test remove_container method"""

    @pytest.mark.asyncio
    async def test_remove_container_always_returns_true(self, k8s_container_client):
        """Test remove_container always returns True (same as stop in k8s)"""
        result = await k8s_container_client.remove_container("test-container-id")
        assert result is True


# ---------------------------------------------------------------------------
# Test list_containers
# ---------------------------------------------------------------------------


class TestListContainers:
    """Test list_containers method"""

    def test_list_containers_no_filters(self, k8s_container_client, mock_pod):
        """Test listing containers without filters"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client.list_containers()

        assert len(result) == 1
        assert result[0]["container_id"] == "test-pod-uid-12345"
        assert result[0]["name"] == "mcp-test-service-tenant12-user1234"
        assert result[0]["status"] == "running"

    def test_list_containers_with_tenant_filter(self, k8s_container_client, mock_pod):
        """Test listing containers with tenant filter"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client.list_containers(tenant_id="tenant12")

        assert len(result) == 1

    def test_list_containers_with_tenant_filter_no_match(self, k8s_container_client, mock_pod):
        """Test listing containers with tenant filter that doesn't match"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client.list_containers(tenant_id="different")

        assert len(result) == 0

    def test_list_containers_with_service_filter(self, k8s_container_client, mock_pod):
        """Test listing containers with service filter"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client.list_containers(service_name="test-service")

        assert len(result) == 1

    def test_list_containers_with_service_filter_no_match(self, k8s_container_client, mock_pod):
        """Test listing containers with service filter that doesn't match"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client.list_containers(service_name="other-service")

        assert len(result) == 0

    def test_list_containers_with_both_filters(self, k8s_container_client, mock_pod):
        """Test listing containers with both tenant and service filters"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client.list_containers(
            tenant_id="tenant12",
            service_name="test-service"
        )

        assert len(result) == 1

    def test_list_containers_no_pods(self, k8s_container_client):
        """Test listing containers when no pods exist"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[])

        result = k8s_container_client.list_containers()

        assert len(result) == 0

    def test_list_containers_api_exception(self, k8s_container_client):
        """Test listing containers when API exception occurs"""
        k8s_container_client.core_v1.list_namespaced_pod.side_effect = ApiException(status=500)

        result = k8s_container_client.list_containers()

        assert result == []

    def test_list_containers_generic_exception(self, k8s_container_client):
        """Test listing containers when generic exception occurs"""
        k8s_container_client.core_v1.list_namespaced_pod.side_effect = Exception("Unexpected error")

        result = k8s_container_client.list_containers()

        assert result == []

    def test_list_containers_service_filter_special_chars(self, k8s_container_client, mock_pod):
        """Test listing containers with service filter containing special characters"""
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client.list_containers(service_name="test@service#123")

        assert len(result) == 0

    def test_list_containers_pod_no_ports(self, k8s_container_client):
        """Test listing containers when pod has no ports configured"""
        mock_pod_no_ports = MagicMock()
        mock_pod_no_ports.metadata.uid = "test-pod-uid"
        mock_pod_no_ports.metadata.name = "test-pod"
        mock_pod_no_ports.metadata.labels = {}
        mock_pod_no_ports.status = MagicMock()
        mock_pod_no_ports.status.phase = "Running"
        mock_pod_no_ports.spec = MagicMock()
        mock_pod_no_ports.spec.containers = [MagicMock(ports=[])]

        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod_no_ports])

        result = k8s_container_client.list_containers()

        assert len(result) == 1
        assert result[0]["host_port"] == 5020  # Should use config default

    def test_list_containers_pod_no_containers(self, k8s_container_client):
        """Test listing containers when pod has no containers"""
        mock_pod_no_containers = MagicMock()
        mock_pod_no_containers.metadata.uid = "test-pod-uid"
        mock_pod_no_containers.metadata.name = "test-pod"
        mock_pod_no_containers.metadata.labels = {}
        mock_pod_no_containers.status = MagicMock()
        mock_pod_no_containers.status.phase = "Running"
        mock_pod_no_containers.spec = MagicMock()
        mock_pod_no_containers.spec.containers = []

        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod_no_containers])

        result = k8s_container_client.list_containers()

        assert len(result) == 1
        assert result[0]["host_port"] == 5020  # Should use config default

    def test_list_containers_pod_no_status(self, k8s_container_client):
        """Test listing containers when pod has no status"""
        mock_pod_no_status = MagicMock()
        mock_pod_no_status.metadata.uid = "test-pod-uid"
        mock_pod_no_status.metadata.name = "test-pod"
        mock_pod_no_status.metadata.labels = {}
        mock_pod_no_status.status = None
        mock_pod_no_status.spec = MagicMock()
        container = MagicMock()
        container.ports = [MagicMock(container_port=5020)]
        mock_pod_no_status.spec.containers = [container]

        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod_no_status])

        result = k8s_container_client.list_containers()

        assert len(result) == 1
        assert result[0]["status"] == "unknown"


# ---------------------------------------------------------------------------
# Test _resolve_pod_name
# ---------------------------------------------------------------------------


class TestResolvePodName:
    """Test _resolve_pod_name method"""

    def test_resolve_pod_name_by_name(self, k8s_container_client):
        """Test resolving pod name by name"""
        k8s_container_client.core_v1.read_namespaced_pod.return_value = MagicMock()

        result = k8s_container_client._resolve_pod_name("test-pod")

        assert result == "test-pod"

    def test_resolve_pod_name_by_uid(self, k8s_container_client):
        """Test resolving pod name by UID"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        mock_pod = MagicMock()
        mock_pod.metadata.uid = "test-uid"
        mock_pod.metadata.name = "test-pod"
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        result = k8s_container_client._resolve_pod_name("test-uid")

        assert result == "test-pod"

    def test_resolve_pod_name_not_found(self, k8s_container_client):
        """Test resolving pod name when not found"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[])

        result = k8s_container_client._resolve_pod_name("non-existent")

        assert result is None

    def test_resolve_pod_name_api_exception_non_404(self, k8s_container_client):
        """Test resolving pod name when API exception is non-404"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=500)

        result = k8s_container_client._resolve_pod_name("test-pod")

        assert result is None

    def test_resolve_pod_name_list_exception(self, k8s_container_client):
        """Test resolving pod name when list API fails"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)
        k8s_container_client.core_v1.list_namespaced_pod.side_effect = Exception("Unexpected error")

        result = k8s_container_client._resolve_pod_name("test-uid")

        assert result is None


# ---------------------------------------------------------------------------
# Test get_container_logs
# ---------------------------------------------------------------------------


class TestGetContainerLogs:
    """Test get_container_logs method"""

    def test_get_container_logs_success(self, k8s_container_client):
        """Test getting container logs successfully"""
        k8s_container_client.core_v1.read_namespaced_pod.return_value = MagicMock()
        k8s_container_client.core_v1.read_namespaced_pod_log.return_value = "Log line 1\nLog line 2"

        logs = k8s_container_client.get_container_logs("test-pod", tail=100)

        assert logs == "Log line 1\nLog line 2"
        k8s_container_client.core_v1.read_namespaced_pod_log.assert_called_once_with(
            name="test-pod",
            namespace="test-namespace",
            tail_lines=100,
            container="mcp-server",
        )

    def test_get_container_logs_custom_tail(self, k8s_container_client):
        """Test getting container logs with custom tail"""
        k8s_container_client.core_v1.read_namespaced_pod.return_value = MagicMock()
        k8s_container_client.core_v1.read_namespaced_pod_log.return_value = "Log line 1"

        logs = k8s_container_client.get_container_logs("test-pod", tail=50)

        k8s_container_client.core_v1.read_namespaced_pod_log.assert_called_once_with(
            name="test-pod",
            namespace="test-namespace",
            tail_lines=50,
            container="mcp-server",
        )

    def test_get_container_logs_not_found(self, k8s_container_client):
        """Test getting logs when pod not found"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)

        logs = k8s_container_client.get_container_logs("non-existent-pod")

        assert logs == ""

    def test_get_container_logs_404_exception(self, k8s_container_client):
        """Test getting logs when 404 exception occurs"""
        k8s_container_client.core_v1.read_namespaced_pod.return_value = MagicMock()
        k8s_container_client.core_v1.read_namespaced_pod_log.side_effect = ApiException(status=404)

        logs = k8s_container_client.get_container_logs("test-pod")

        assert logs == ""

    def test_get_container_logs_api_exception_non_404(self, k8s_container_client):
        """Test getting logs when API exception is non-404"""
        k8s_container_client.core_v1.read_namespaced_pod.return_value = MagicMock()
        k8s_container_client.core_v1.read_namespaced_pod_log.side_effect = ApiException(status=500)

        logs = k8s_container_client.get_container_logs("test-pod")

        assert "Error retrieving logs" in logs

    def test_get_container_logs_generic_exception(self, k8s_container_client):
        """Test getting logs when generic exception occurs"""
        k8s_container_client.core_v1.read_namespaced_pod.return_value = MagicMock()
        k8s_container_client.core_v1.read_namespaced_pod_log.side_effect = Exception("Unexpected error")

        logs = k8s_container_client.get_container_logs("test-pod")

        assert "Error retrieving logs" in logs


# ---------------------------------------------------------------------------
# Test get_container_status
# ---------------------------------------------------------------------------


class TestGetContainerStatus:
    """Test get_container_status method"""

    def test_get_container_status_success(self, k8s_container_client, mock_pod):
        """Test getting container status successfully"""
        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        result = k8s_container_client.get_container_status("test-pod")

        assert result is not None
        assert result["container_id"] == "test-pod-uid-12345"
        assert result["name"] == "mcp-test-service-tenant12-user1234"
        assert result["status"] == "running"

    def test_get_container_status_not_found_by_name(self, k8s_container_client):
        """Test getting container status when pod not found by name but found by UID"""
        mock_pod = MagicMock()
        mock_pod.metadata = MagicMock()
        mock_pod.metadata.uid = "test-pod-uid-12345"
        mock_pod.metadata.name = "mcp-test-service-tenant12-user1234"
        mock_pod.metadata.labels = {"app": "nexent-mcp"}
        mock_pod.metadata.creation_timestamp = MagicMock()
        mock_pod.metadata.creation_timestamp.isoformat.return_value = "2024-01-01T00:00:00Z"
        mock_pod.status = MagicMock()
        mock_pod.status.phase = "Running"
        mock_pod.spec = MagicMock()
        container = MagicMock()
        container.ports = [MagicMock(container_port=5020)]
        container.image = "node:22-alpine"
        container.env = [MagicMock(name="PORT", value="5020")]
        mock_pod.spec.containers = [container]

        # First call (read by name "test-uid") returns 404
        # Second call (read by name from found pod) returns mock_pod
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = [
            ApiException(status=404),
            mock_pod,  # This is returned when searching by the found pod name
        ]
        # When searching by UID in list, return mock_pod with matching UID
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])

        # Use the UID as container_id to match mock_pod.metadata.uid
        result = k8s_container_client.get_container_status("test-pod-uid-12345")

        assert result is not None
        assert result["container_id"] == "test-pod-uid-12345"

    def test_get_container_status_not_found_at_all(self, k8s_container_client):
        """Test getting container status when pod not found at all"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=404)
        k8s_container_client.core_v1.list_namespaced_pod.return_value = MagicMock(items=[])

        result = k8s_container_client.get_container_status("non-existent")

        assert result is None

    def test_get_container_status_api_exception_non_404(self, k8s_container_client):
        """Test getting container status when API exception is non-404"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = ApiException(status=500)

        result = k8s_container_client.get_container_status("test-pod")

        assert result is None

    def test_get_container_status_generic_exception(self, k8s_container_client):
        """Test getting container status when generic exception occurs"""
        k8s_container_client.core_v1.read_namespaced_pod.side_effect = Exception("Unexpected error")

        result = k8s_container_client.get_container_status("test-pod")

        assert result is None

    def test_get_container_status_no_ports(self, k8s_container_client):
        """Test getting container status when pod has no ports"""
        mock_pod = MagicMock()
        mock_pod.metadata = MagicMock()
        mock_pod.metadata.uid = "test-pod-uid"
        mock_pod.metadata.name = "test-pod"
        mock_pod.metadata.creation_timestamp = MagicMock()
        mock_pod.metadata.creation_timestamp.isoformat.return_value = "2024-01-01T00:00:00Z"
        mock_pod.status = MagicMock()
        mock_pod.status.phase = "Running"
        mock_pod.spec = MagicMock()
        container = MagicMock()
        container.ports = []  # No ports
        container.image = "node:22-alpine"
        container.env = []  # No env var
        mock_pod.spec.containers = [container]

        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        result = k8s_container_client.get_container_status("test-pod")

        assert result is not None
        assert result["host_port"] == str(k8s_container_client.config.service_port)  # Falls back to config
        assert result["service_url"] == f"http://test-pod:{k8s_container_client.config.service_port}/mcp"

    def test_get_container_status_no_containers(self, k8s_container_client):
        """Test getting container status when pod has no containers"""
        mock_pod = MagicMock()
        mock_pod.metadata.uid = "test-pod-uid"
        mock_pod.metadata.name = "test-pod"
        mock_pod.metadata.creation_timestamp = MagicMock()
        mock_pod.metadata.creation_timestamp.isoformat.return_value = "2024-01-01T00:00:00Z"
        mock_pod.status = MagicMock()
        mock_pod.status.phase = "Running"
        mock_pod.spec = MagicMock()
        mock_pod.spec.containers = []

        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        result = k8s_container_client.get_container_status("test-pod")

        assert result is not None
        assert result["image"] is None

    def test_get_container_status_no_spec(self, k8s_container_client):
        """Test getting container status when pod has no spec"""
        mock_pod = MagicMock()
        mock_pod.metadata = MagicMock()
        mock_pod.metadata.uid = "test-pod-uid"
        mock_pod.metadata.name = "test-pod"
        mock_pod.metadata.creation_timestamp = MagicMock()
        mock_pod.metadata.creation_timestamp.isoformat.return_value = "2024-01-01T00:00:00Z"
        mock_pod.status = MagicMock()
        mock_pod.status.phase = "Running"
        mock_pod.spec = None  # No spec

        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        result = k8s_container_client.get_container_status("test-pod")

        # Should return result with host_port from config fallback
        assert result is not None
        assert result["host_port"] == str(k8s_container_client.config.service_port)  # Falls back to config
        assert result["image"] is None

    def test_get_container_status_port_from_env(self, k8s_container_client):
        """Test getting container status when port is from env var"""
        mock_pod = MagicMock()
        mock_pod.metadata = MagicMock()
        mock_pod.metadata.uid = "test-pod-uid"
        mock_pod.metadata.name = "test-pod"
        mock_pod.metadata.creation_timestamp = MagicMock()
        mock_pod.metadata.creation_timestamp.isoformat.return_value = "2024-01-01T00:00:00Z"
        mock_pod.status = MagicMock()
        mock_pod.status.phase = "Running"
        mock_pod.spec = MagicMock()
        container = MagicMock()
        container.ports = [MagicMock(container_port=5020)]
        container.image = "node:22-alpine"
        # Use spec to ensure proper attribute behavior
        port_env = MagicMock(spec=['name', 'value'])
        port_env.name = "PORT"
        port_env.value = "5020"
        container.env = [port_env]
        mock_pod.spec.containers = [container]

        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        result = k8s_container_client.get_container_status("test-pod")

        assert result is not None
        assert result["host_port"] == "5020"

    def test_get_container_status_no_status(self, k8s_container_client):
        """Test getting container status when pod has no status"""
        mock_pod = MagicMock()
        mock_pod.metadata.uid = "test-pod-uid"
        mock_pod.metadata.name = "test-pod"
        mock_pod.metadata.creation_timestamp = MagicMock()
        mock_pod.metadata.creation_timestamp.isoformat.return_value = "2024-01-01T00:00:00Z"
        mock_pod.status = None
        mock_pod.spec = MagicMock()
        container = MagicMock()
        container.ports = [MagicMock(container_port=5020)]
        container.image = "node:22-alpine"
        mock_pod.spec.containers = [container]

        k8s_container_client.core_v1.read_namespaced_pod.return_value = mock_pod

        result = k8s_container_client.get_container_status("test-pod")

        assert result is not None
        assert result["status"] == "unknown"
