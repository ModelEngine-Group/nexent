"""
Kubernetes container client implementation

This client manages MCP server containers as Kubernetes Pods with associated Services
for network access.
"""

import asyncio
import logging
import socket
import uuid
import kubernetes
from typing import Any, Dict, List, Optional

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport, SSETransport
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from .container_client_base import ContainerClient
from .k8s_config import KubernetesContainerConfig

logger = logging.getLogger("nexent.container.kubernetes")


class ContainerError(Exception):
    """Raised when container operation fails"""

    pass


class ContainerConnectionError(Exception):
    """Raised when container connection fails"""

    pass


class KubernetesContainerClient(ContainerClient):
    """Kubernetes container client implementation"""

    LABEL_APP = "app"
    LABEL_TENANT = "tenant"
    LABEL_USER = "user"
    LABEL_COMPONENT = "component"

    def __init__(self, config: KubernetesContainerConfig):
        """
        Initialize Kubernetes client

        Args:
            config: Kubernetes container configuration

        Raises:
            ContainerError: If Kubernetes connection fails
        """
        config.validate()
        self.config = config

        try:
            if config.in_cluster:
                kubernetes.config.load_incluster_config()
            elif config.kubeconfig_path:
                kubernetes.config.load_kube_config_from_dict(config.kubeconfig_path)
            else:
                kubernetes.config.load_kube_config()

            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()

            # Test connection
            self.core_v1.list_namespaced_pod(namespace=config.namespace, limit=1)
            logger.info(f"Kubernetes client initialized for namespace={config.namespace}")
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise ContainerError(f"Cannot connect to Kubernetes: {e}")

    def _generate_pod_name(self, service_name: str, tenant_id: str, user_id: str) -> str:
        """Generate unique pod name with service, tenant, and user segments."""
        safe_name = "".join(c if c.isalnum() or c == "-" else "-" for c in service_name)
        tenant_part = (tenant_id or "")[:8]
        user_part = (user_id or "")[:8]
        uuid_part = uuid.uuid4().hex[:8]
        return f"mcp-{safe_name}-{tenant_part}-{user_part}-{uuid_part}"

    def _get_labels(self, service_name: str, tenant_id: str, user_id: str) -> Dict[str, str]:
        """Generate labels for pod and service."""
        return {
            # Use a distinct app label to avoid conflicts with the native nexent-mcp deployment
            self.LABEL_APP: "nexent-mcp-container",
            self.LABEL_COMPONENT: service_name,
            self.LABEL_TENANT: tenant_id[:8] if tenant_id else "",
            self.LABEL_USER: user_id[:8] if user_id else "",
        }

    def _find_free_port(self, start_port: int = 5020, max_attempts: int = 100) -> int:
        """Find an available port on host."""
        for i in range(max_attempts):
            port = start_port + i
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(("localhost", port))
                if result != 0:
                    logger.debug(f"Found free port: {port}")
                    return port
        raise ContainerError(
            f"No available port found in range {start_port}-{start_port + max_attempts}"
        )

    def _get_pod_port_from_env(self, pod: client.V1Pod) -> Optional[str]:
        """Get service port from pod environment variables."""
        try:
            containers = pod.spec.containers if pod.spec else []
            for container in containers:
                env_list = container.env or []
                for item in env_list:
                    if item.name == "PORT":
                        return item.value
        except Exception:
            pass
        return None

    def _get_service_url(self, pod_name: str, host_port: Optional[int] = None) -> str:
        """Construct service URL from pod info."""
        port = str(host_port) if host_port else str(self.config.service_port)
        return f"http://{pod_name}:{port}/mcp"

    def _create_pod_service(self, pod_name: str, namespace: str, port: int, labels: Dict[str, str]) -> client.V1Service:
        """Create a ClusterIP service for the pod."""
        service = client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels=labels,
            ),
            spec=client.V1ServiceSpec(
                selector=labels,
                ports=[client.V1ServicePort(port=port, target_port=port, name="http")],
                type="ClusterIP",
            ),
        )
        return self.core_v1.create_namespaced_service(namespace=namespace, body=service)

    async def start_container(
        self,
        service_name: str,
        tenant_id: str,
        user_id: str,
        full_command: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        host_port: Optional[int] = None,
        image: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start container (Pod) and return access URL

        Args:
            service_name: Name of the service
            tenant_id: Tenant ID for isolation
            user_id: User ID for isolation
            full_command: Optional complete command list to run inside container
            env_vars: Optional environment variables
            host_port: Optional port (used for service mapping)

        Returns:
            Dictionary with pod_name, service_url, port, and status

        Raises:
            ContainerError: If pod startup fails
        """
        pod_name = self._generate_pod_name(service_name, tenant_id, user_id)
        labels = self._get_labels(service_name, tenant_id, user_id)
        namespace = self.config.namespace

        # Check if pod already exists
        try:
            existing_pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            if existing_pod.status.phase == "Running":
                service_url = self._get_service_url(pod_name)
                logger.info(f"Using existing pod {pod_name} (already running)")
                return {
                    "container_id": existing_pod.metadata.uid,
                    "service_url": service_url,
                    "host_port": str(host_port) if host_port else str(self.config.service_port),
                    "status": "existing",
                    "container_name": pod_name,
                }
            # Delete existing pod if not running
            if existing_pod:
                logger.info(f"Removing existing stopped pod {pod_name}")
                self.core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
                await asyncio.sleep(2)
        except ApiException as e:
            if e.status != 404:
                raise ContainerError(f"Failed to check existing pod: {e}")

        # Determine port
        if host_port is None:
            host_port = self._find_free_port()

        # Prepare environment variables
        container_env = [
            client.V1EnvVar(name="PORT", value=str(host_port)),
            client.V1EnvVar(name="TRANSPORT", value="streamable-http"),
            client.V1EnvVar(name="NODE_ENV", value="production"),
        ]
        if env_vars:
            for key, value in env_vars.items():
                container_env.append(client.V1EnvVar(name=key, value=value))

        # Determine image
        command0 = full_command[0] if full_command else ""
        if image:
            image_name = image
        elif command0 in ["npx", "node", "npm"]:
            image_name = "node:22-alpine"
        else:
            image_name = "alpine:latest"

        # Extract authorization_token for health check
        authorization_token = None
        if env_vars:
            authorization_token = env_vars.get("authorization_token")

        # Create pod
        command_to_run = full_command if full_command else None

        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels=labels,
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="mcp-server",
                        image=image_name,
                        image_pull_policy="IfNotPresent",
                        env=container_env,
                        command=command_to_run,
                        ports=[
                            client.V1ContainerPort(
                                container_port=host_port,
                                name="http",
                            )
                        ],
                        readiness_probe=client.V1Probe(
                            tcp_socket=client.V1TCPSocketAction(
                                port=host_port,
                            ),
                            initial_delay_seconds=30,
                            period_seconds=10,
                            failure_threshold=12,
                        ),
                    )
                ],
                restart_policy="Always",
            ),
        )

        try:
            logger.info(f"Creating pod {pod_name} with image {image_name}")
            self.core_v1.create_namespaced_pod(namespace=namespace, body=pod)

            # Wait for pod to be ready (returns pod with UID)
            pod = await self._wait_for_pod_ready(pod_name, namespace)

            # Create service for the pod with matching labels
            service = self._create_pod_service(pod_name, namespace, host_port or self.config.service_port, labels)
            logger.info(f"Creating service {pod_name} for pod")

            service_url = self._get_service_url(pod_name, host_port)

            # Wait for service to be ready
            try:
                await self._wait_for_service_ready(service_url, authorization_token=authorization_token)
            except ContainerConnectionError:
                logger.warning(
                    f"Service health check failed for {service_url}, but pod is running"
                )

            logger.info(f"Pod {pod_name} started successfully on port {host_port}")
            logger.info(f"Pod uid is: {pod.metadata.uid}")
            return {
                "container_id": pod.metadata.uid,
                "service_url": service_url,
                "host_port": str(host_port),
                "status": "started",
                "container_name": pod_name,
            }

        except ApiException as e:
            logger.error(f"Kubernetes API error starting pod: {e}")
            raise ContainerError(f"Pod startup failed: {e}")
        except Exception as e:
            logger.error(f"Failed to start pod: {e}")
            raise ContainerError(f"Pod startup failed: {e}")

    async def _wait_for_pod_ready(self, pod_name: str, namespace: str, timeout: int = 120):
        """Wait for pod to be ready and return the pod object."""
        for _ in range(timeout):
            try:
                pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                if pod.status.phase == "Running":
                    # Also check if container is ready
                    container_statuses = pod.status.container_statuses or []
                    if all(cs.ready for cs in container_statuses):
                        logger.info(f"Pod {pod_name} is ready")
                        return pod
                await asyncio.sleep(1)
            except ApiException as e:
                if e.status == 404:
                    await asyncio.sleep(1)
                    continue
                raise ContainerError(f"Failed to wait for pod: {e}")
        raise ContainerError(f"Pod {pod_name} did not become ready within {timeout} seconds")

    async def _wait_for_service_ready(
        self,
        url: str,
        max_retries: int = 30,
        retry_delay: int = 5,
        authorization_token: Optional[str] = None,
    ):
        """Wait for service to be ready by checking connection."""
        for i in range(max_retries):
            try:
                url_stripped = url.strip()
                headers = {"Authorization": authorization_token} if authorization_token else {}

                if url_stripped.endswith("/sse"):
                    transport = SSETransport(url=url_stripped, headers=headers)
                elif url_stripped.endswith("/mcp"):
                    transport = StreamableHttpTransport(url=url_stripped, headers=headers)
                else:
                    transport = StreamableHttpTransport(url=url_stripped, headers=headers)

                client_instance = Client(transport=transport)
                async with client_instance:
                    if client_instance.is_connected():
                        logger.info(f"Service ready at {url}")
                        return
                    if i < max_retries - 1:
                        logger.debug(f"Service not ready yet (attempt {i+1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                    else:
                        raise ContainerConnectionError(f"Service not ready after {max_retries * retry_delay}s")
            except BaseException as e:
                if i < max_retries - 1:
                    logger.debug(f"Service not ready yet (attempt {i+1}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Service not ready after {max_retries} attempts: {e}")
                    raise ContainerConnectionError(f"Service not ready after {max_retries * retry_delay}s: {e}")

    async def stop_container(self, container_id: str) -> bool:
        """
        Stop container (Pod)

        Args:
            container_id: Pod name or ID

        Returns:
            True if pod was stopped successfully, False if not found

        Raises:
            ContainerError: If pod stop fails
        """
        namespace = self.config.namespace

        try:
            # Find pod by name (use the container_id as pod name)
            pod_name = container_id
            try:
                self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            except ApiException as e:
                if e.status == 404:
                    # Try to find by UID
                    pods = self.core_v1.list_namespaced_pod(
                        namespace=namespace,
                        label_selector=f"{self.LABEL_APP}=nexent-mcp-container",
                    )
                    for p in pods.items:
                        if p.metadata.uid == container_id:
                            pod_name = p.metadata.name
                            break
                    else:
                        logger.warning(f"Pod {container_id} not found")
                        return False
                else:
                    raise

            logger.info(f"Stopping pod {pod_name}")
            self.core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)

            # Wait for pod to be fully deleted
            pod_deleted = False
            for _ in range(60):  # 60 second timeout
                try:
                    self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                except ApiException as e:
                    if e.status == 404:
                        logger.info(f"Pod {pod_name} deleted successfully")
                        pod_deleted = True
                        break
                    # For other API errors (e.g., network issues), continue waiting
                    logger.debug(f"API error while waiting for pod deletion: {e}")
                except Exception as e:
                    logger.debug(f"Unexpected error while waiting for pod deletion: {e}")
                await asyncio.sleep(1)

            if not pod_deleted:
                logger.warning(f"Pod {pod_name} was not deleted after 60 seconds, returning anyway")
                return True  # Pod was marked for deletion, return success

            # Also delete the associated service
            try:
                self.core_v1.delete_namespaced_service(name=pod_name, namespace=namespace)
                logger.info(f"Service {pod_name} deleted")
            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"Failed to delete service {pod_name}: {e}")

            logger.info(f"Pod {pod_name} stopped")
            return True

        except ApiException as e:
            logger.error(f"Failed to stop pod {container_id}: {e}")
            raise ContainerError(f"Failed to stop pod: {e}")
        except Exception as e:
            logger.error(f"Unexpected error stopping pod {container_id}: {e}")
            raise ContainerError(f"Failed to stop pod: {e}")

    async def remove_container(self, container_id: str) -> bool:
        """
        Remove container (Pod)

        Args:
            container_id: Pod name or ID

        Returns:
            True if pod was removed successfully, False if not found

        Raises:
            ContainerError: If pod removal fails
        """
        # In Kubernetes, stop and remove are the same operation
        return True

    def list_containers(
        self, tenant_id: Optional[str] = None, service_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all pods, optionally filtered by tenant or service

        Args:
            tenant_id: Optional tenant ID to filter pods
            service_name: Optional service name to filter pods

        Returns:
            List of pod information dictionaries
        """
        namespace = self.config.namespace
        result = []

        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"{self.LABEL_APP}=nexent-mcp-container",
            )
            logger.info(f"Found {len(pods.items)} pods in namespace {namespace}")

            for pod in pods.items:
                labels = pod.metadata.labels or {}

                # Filter by tenant_id if provided
                if tenant_id:
                    pod_tenant = labels.get(self.LABEL_TENANT, "")
                    if tenant_id[:8] not in pod_tenant:
                        continue

                # Filter by service_name if provided
                if service_name:
                    safe_name = "".join(c if c.isalnum() or c == "-" else "-" for c in service_name)
                    pod_component = labels.get(self.LABEL_COMPONENT, "")
                    if safe_name not in pod_component:
                        continue

                # Get port from environment
                container_port = pod.spec.containers[0].ports[0].container_port if pod.spec.containers and pod.spec.containers[0].ports else self.config.service_port
                service_url = self._get_service_url(pod.metadata.name, container_port)

                result.append({
                    "container_id": pod.metadata.uid,
                    "name": pod.metadata.name,
                    "status": pod.status.phase.lower() if pod.status else "unknown",
                    "service_url": service_url,
                    "host_port": container_port,
                })

            return result

        except ApiException as e:
            logger.error(f"Failed to list pods: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing pods: {e}")
            return []

    def _resolve_pod_name(self, container_id: str) -> Optional[str]:
        """
        Resolve container_id (which could be UID or name) to actual Pod name.

        Args:
            container_id: Pod name or UID

        Returns:
            Pod name if found, None otherwise
        """
        namespace = self.config.namespace
        try:
            # Try to find pod by name first
            self.core_v1.read_namespaced_pod(name=container_id, namespace=namespace)
            return container_id
        except ApiException as e:
            if e.status != 404:
                return None
        # Pod not found by name, try to find by UID
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"{self.LABEL_APP}=nexent-mcp-container",
            )
            for p in pods.items:
                if p.metadata.uid == container_id:
                    return p.metadata.name
        except Exception:
            pass
        return None

    def get_container_logs(self, container_id: str, tail: int = 100) -> str:
        """
        Get container (Pod) logs

        Args:
            container_id: Pod name or ID
            tail: Number of log lines to retrieve

        Returns:
            Pod logs as string
        """
        namespace = self.config.namespace
        pod_name = self._resolve_pod_name(container_id)

        if not pod_name:
            logger.warning(f"Pod {container_id} not found")
            return ""

        try:
            logs = self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=tail,
                container="mcp-server",
            )
            return logs

        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Pod {container_id} not found")
                return ""
            logger.error(f"Failed to get pod logs: {e}")
            return f"Error retrieving logs: {e}"
        except Exception as e:
            logger.error(f"Failed to get pod logs: {e}")
            return f"Error retrieving logs: {e}"

    def get_container_status(self, container_id: str) -> Optional[Dict[str, Any]]:
        """
        Get container (Pod) status information

        Args:
            container_id: Pod name or ID

        Returns:
            Dictionary with pod status information, or None if not found
        """
        namespace = self.config.namespace
        pod_name = container_id

        try:
            # Try to find pod by name first
            try:
                pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            except ApiException as e:
                if e.status == 404:
                    # Pod not found by name, try to find by UID
                    pods = self.core_v1.list_namespaced_pod(
                        namespace=namespace,
                        label_selector=f"{self.LABEL_APP}=nexent-mcp-container",
                    )
                    for p in pods.items:
                        if p.metadata.uid == container_id:
                            pod = p
                            pod_name = p.metadata.name
                            break
                    else:
                        return None
                else:
                    raise

            service_port = self._get_pod_port_from_env(pod) or str(self.config.service_port)
            if self._get_pod_port_from_env(pod):
                container_port = str(self.config.service_port)
            else:
                containers_list = getattr(pod.spec, 'containers', []) if pod.spec else []
                container_port = containers_list[0].ports[0].container_port if containers_list and containers_list[0].ports else self.config.service_port

            service_url = self._get_service_url(pod.metadata.name, container_port)

            containers = getattr(pod.spec, 'containers', []) if pod.spec else []
            image = containers[0].image if containers else None

            return {
                "container_id": pod.metadata.uid,
                "name": pod.metadata.name,
                "status": pod.status.phase.lower() if pod.status else "unknown",
                "service_url": service_url,
                "host_port": service_port,
                "created": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
                "image": image,
            }

        except ApiException as e:
            logger.error(f"Failed to get pod status: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to get pod status: {e}")
            return None
