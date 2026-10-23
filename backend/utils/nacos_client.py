"""
Nacos Client for service discovery.

Provides functionality to query service instances from Nacos service registry.
Used by A2A agent discovery to find external A2A agents registered in Nacos.
"""
import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class NacosClientError(Exception):
    """Base exception for Nacos client errors."""
    pass


class NacosConnectionError(NacosClientError):
    """Raised when connection to Nacos fails."""
    pass


class NacosServiceNotFoundError(NacosClientError):
    """Raised when the requested service is not found in Nacos."""
    pass


class NacosClient:
    """Async client for Nacos service registry operations.

    Provides methods to query service instances for A2A agent discovery.
    """

    def __init__(
        self,
        nacos_addr: str,
        username: Optional[str] = None,
        password: Optional[str] = None
    ):
        """Initialize Nacos client.

        Args:
            nacos_addr: Nacos server address (e.g., http://nacos-server:8848).
            username: Optional Nacos username for authentication.
            password: Optional Nacos password for authentication.
        """
        self.nacos_addr = nacos_addr.rstrip("/")
        self.username = username
        self.password = password
        self._session: Optional[aiohttp.ClientSession] = None
        self._access_token: Optional[str] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _build_auth_params(self) -> Dict[str, str]:
        """Build authentication parameters for Nacos API requests."""
        params = {}
        if self.username:
            params["username"] = self.username
        if self.password:
            params["password"] = self.password
        return params

    async def query_a2a_agent(
        self,
        agent_name: str,
        namespace: str = "public"
    ) -> Optional[Dict[str, Any]]:
        """Query A2A agent info from Nacos using the dedicated A2A endpoint.

        Args:
            agent_name: The name of the A2A agent to query.
            namespace: Nacos namespace ID (defaults to "public").

        Returns:
            A dict containing agent information:
            - agent_name: Agent name
            - agent_url: A2A agent endpoint URL
            - metadata: Additional metadata
            Or None if no agent is found.

        Raises:
            NacosConnectionError: If connection to Nacos fails.
        """
        params = self._build_auth_params()
        agent_name = agent_name.strip()
        params["agentName"] = agent_name
        params["namespaceId"] = namespace.strip() if namespace else "public"

        url = f"{self.nacos_addr}/nacos/v3/admin/ai/a2a"

        try:
            session = await self._get_session()
            async with session.get(url, params=params) as response:
                text = await response.text()

                if response.status == 200:
                    data = await response.json()
                    return self._parse_a2a_response(data, agent_name)
                elif response.status == 404:
                    logger.warning(
                        f"A2A agent '{agent_name}' not found in Nacos namespace '{namespace}'"
                    )
                    return None
                else:
                    raise NacosConnectionError(
                        f"Nacos A2A API returned status {response.status}: {text}"
                    )

        except aiohttp.ClientError as e:
            logger.error(f"Failed to connect to Nacos at {self.nacos_addr}: {e}")
            raise NacosConnectionError(f"Failed to connect to Nacos: {e}") from e

    def _parse_a2a_response(
        self,
        response_data: Dict[str, Any],
        agent_name: str
    ) -> Optional[Dict[str, Any]]:
        """Parse Nacos A2A agent response.

        Args:
            response_data: Response data from Nacos A2A API.
            agent_name: Agent name for logging.

        Returns:
            Agent info dict or None if no agent found.
        """
        if response_data.get("code") != 0:
            msg = response_data.get("message", "unknown error")
            logger.warning(f"Nacos A2A API error for '{agent_name}': {msg}")
            return None

        data = response_data.get("data")
        if not data:
            logger.info(f"No A2A agent data found for '{agent_name}'")
            return None

        logger.info(f"[Nacos A2A Parse] Found agent: {data}")
        return data

    async def query_service_instance(
        self,
        service_name: str,
        namespace: str = "public",
        clusters: Optional[str] = None,
        healthy_only: bool = False,
        group_name: str = "DEFAULT_GROUP"
    ) -> Optional[Dict[str, Any]]:
        """Query service instance(s) from Nacos using v3 client API.

        Args:
            service_name: The name of the service to query.
            namespace: Nacos namespace ID (defaults to "public").
            clusters: Comma-separated cluster names (optional).
            healthy_only: If True, only return healthy instances.
            group_name: Nacos group name (defaults to "DEFAULT_GROUP").

        Returns:
            A dict containing instance information with keys:
            - ip: Instance IP address
            - port: Instance port
            - metadata: Instance metadata dict (may contain 'a2a_card_url')
            Or None if no instance is found.

        Raises:
            NacosConnectionError: If connection to Nacos fails.
            NacosServiceNotFoundError: If the service does not exist.
        """
        params = self._build_auth_params()
        service_name = service_name.strip()
        params["serviceName"] = service_name
        params["namespaceId"] = namespace.strip() if namespace else "public"
        params["groupName"] = group_name
        if clusters:
            params["clusterName"] = clusters
        if healthy_only:
            params["healthyOnly"] = "true"

        url = f"{self.nacos_addr}/nacos/v3/client/ns/instance/list"

        logger.info(
            f"[Nacos Query] URL: {url}, params: "
            f"serviceName='{service_name}', namespaceId='{namespace}', groupName='{group_name}'"
        )

        try:
            session = await self._get_session()
            async with session.get(url, params=params) as response:
                text = await response.text()
                logger.info(
                    f"[Nacos Response] status={response.status}, "
                    f"body_len={len(text)}, body={text[:300]}"
                )

                if response.status == 200:
                    data = await response.json()
                    return self._parse_v3_instance_response(data, service_name)
                elif response.status == 404:
                    logger.warning(
                        f"Service '{service_name}' not found in Nacos namespace '{namespace}'"
                    )
                    return None
                else:
                    raise NacosConnectionError(
                        f"Nacos API returned status {response.status}: {text}"
                    )

        except aiohttp.ClientError as e:
            logger.error(f"Failed to connect to Nacos at {self.nacos_addr}: {e}")
            raise NacosConnectionError(f"Failed to connect to Nacos: {e}") from e

    def _parse_v3_instance_response(
        self,
        response_data: Dict[str, Any],
        service_name: str
    ) -> Optional[Dict[str, Any]]:
        """Parse Nacos v3 client API instance list response.

        Nacos v3 API returns: { "code": 0, "message": "success", "data": [...] }

        Args:
            response_data: Response data from Nacos v3 API.
            service_name: Service name for fallback metadata.

        Returns:
            First instance as a dict or None if no instances exist.
        """
        if response_data.get("code") != 0:
            msg = response_data.get("message", "unknown error")
            logger.warning(f"Nacos API error for '{service_name}': {msg}")
            return None

        data = response_data.get("data")
        if data is None:
            logger.info(f"[Nacos Parse] No data field in response for service '{service_name}'")
            return None

        hosts = data if isinstance(data, list) else []
        logger.info(f"[Nacos Parse] Found {len(hosts)} instances for service '{service_name}'")

        if not hosts:
            logger.info(f"[Nacos Parse] No hosts found for service '{service_name}'")
            return None

        for instance in hosts:
            instance_data = {
                "ip": instance.get("ip"),
                "port": instance.get("port"),
                "healthy": instance.get("healthy", False),
                "weight": instance.get("weight", 1.0),
                "enabled": instance.get("enabled", True),
                "metadata": instance.get("metadata") or {}
            }

            if instance_data["enabled"] and instance_data.get("healthy", False):
                logger.info(
                    f"[Nacos Parse] Found healthy instance for '{service_name}': "
                    f"{instance_data['ip']}:{instance_data['port']}"
                )
                return instance_data

        first_instance = hosts[0]
        logger.info(
            f"[Nacos Parse] No healthy instance found, returning first instance for '{service_name}': "
            f"{first_instance.get('ip')}:{first_instance.get('port')}"
        )
        return {
            "ip": first_instance.get("ip"),
            "port": first_instance.get("port"),
            "healthy": first_instance.get("healthy", False),
            "weight": first_instance.get("weight", 1.0),
            "enabled": first_instance.get("enabled", True),
            "metadata": first_instance.get("metadata") or {}
        }

    def _parse_instance_response(
        self,
        data: Dict[str, Any],
        service_name: str
    ) -> Optional[Dict[str, Any]]:
        """Parse Nacos instance list response (v1 API legacy format).

        Args:
            data: Response data from Nacos /instance/list API.
            service_name: Service name for fallback metadata.

        Returns:
            First instance as a dict or None if no instances exist.
        """
        hosts = data.get("hosts") or []

        if not hosts:
            logger.debug(f"No hosts found for service '{service_name}'")
            return None

        for instance in hosts:
            instance_data = {
                "ip": instance.get("ip"),
                "port": instance.get("port"),
                "healthy": instance.get("healthy", False),
                "weight": instance.get("weight", 1.0),
                "enabled": instance.get("enabled", True),
                "metadata": instance.get("metadata") or {}
            }

            if instance_data["enabled"] and instance_data.get("healthy", False):
                logger.debug(
                    f"Found healthy instance for '{service_name}': "
                    f"{instance_data['ip']}:{instance_data['port']}"
                )
                return instance_data

        first_instance = hosts[0]
        return {
            "ip": first_instance.get("ip"),
            "port": first_instance.get("port"),
            "healthy": first_instance.get("healthy", False),
            "weight": first_instance.get("weight", 1.0),
            "enabled": first_instance.get("enabled", True),
            "metadata": first_instance.get("metadata") or {}
        }

    async def list_services(
        self,
        namespace: str = "public",
        page_no: int = 1,
        page_size: int = 100,
        group_name: str = "DEFAULT_GROUP"
    ) -> Dict[str, Any]:
        """List all services in a namespace using v3 Admin API.

        Args:
            namespace: Nacos namespace ID (defaults to "public").
            page_no: Page number (1-indexed).
            page_size: Number of services per page.
            group_name: Group name filter (defaults to "DEFAULT_GROUP").

        Returns:
            Dict containing:
            - count: Total number of services
            - services: List of service names

        Raises:
            NacosConnectionError: If connection to Nacos fails.
        """
        session = await self._get_session()
        access_token = None
        if self.username and self.password:
            access_token = await self._get_access_token(session)
            if not access_token:
                raise NacosConnectionError("Authentication failed. Please check username and password.")

        params = {
            "pageNo": page_no,
            "pageSize": page_size,
            "namespaceId": namespace,
            "groupName": group_name
        }
        headers = {}
        if access_token:
            headers["AccessToken"] = access_token

        url = f"{self.nacos_addr}/nacos/v3/admin/ns/service"

        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 0:
                        return {
                            "count": data.get("data", {}).get("count", 0),
                            "services": data.get("data", {}).get("doms", [])
                        }
                    elif data.get("code") == 403:
                        self._clear_access_token()
                        raise NacosConnectionError("Authentication failed. Please check username and password.")
                    else:
                        raise NacosConnectionError(
                            f"Nacos API error: {data.get('message', 'unknown')}"
                        )
                elif response.status == 403:
                    self._clear_access_token()
                    raise NacosConnectionError("Authentication failed. Please check username and password.")
                else:
                    text = await response.text()
                    raise NacosConnectionError(
                        f"Nacos API returned status {response.status}: {text}"
                    )

        except aiohttp.ClientError as e:
            logger.error(f"Failed to list services from Nacos: {e}")
            raise NacosConnectionError(f"Failed to list services from Nacos: {e}") from e

    async def get_service_detail(
        self,
        service_name: str,
        namespace: str = "public",
        group_name: str = "DEFAULT_GROUP"
    ) -> Optional[Dict[str, Any]]:
        """Get detailed information about a service using v3 Admin API.

        Args:
            service_name: The name of the service.
            namespace: Nacos namespace ID (defaults to "public").
            group_name: Nacos group name (defaults to "DEFAULT_GROUP").

        Returns:
            Service detail dict or None if not found.

        Raises:
            NacosConnectionError: If connection to Nacos fails.
        """
        session = await self._get_session()
        access_token = None
        if self.username and self.password:
            access_token = await self._get_access_token(session)
            if not access_token:
                raise NacosConnectionError("Authentication failed. Please check username and password.")

        params = {
            "serviceName": service_name,
            "namespaceId": namespace,
            "groupName": group_name
        }
        headers = {}
        if access_token:
            headers["AccessToken"] = access_token

        url = f"{self.nacos_addr}/nacos/v3/admin/ns/service"

        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 0:
                        return data.get("data")
                    elif data.get("code") == 403:
                        self._clear_access_token()
                        raise NacosConnectionError("Authentication failed. Please check username and password.")
                    else:
                        msg = data.get("message", "")
                        if "not found" in msg.lower() or "not exist" in msg.lower():
                            return None
                        raise NacosConnectionError(
                            f"Nacos API error: {msg}"
                        )
                elif response.status == 404:
                    return None
                elif response.status == 403:
                    self._clear_access_token()
                    raise NacosConnectionError("Authentication failed. Please check username and password.")
                else:
                    text = await response.text()
                    raise NacosConnectionError(
                        f"Nacos API returned status {response.status}: {text}"
                    )

        except aiohttp.ClientError as e:
            logger.error(f"Failed to get service detail from Nacos: {e}")
            raise NacosConnectionError(
                f"Failed to get service detail from Nacos: {e}"
            ) from e

    async def check_health(
        self,
        host: str,
        port: int,
        namespace: str = "public"
    ) -> bool:
        """Check if an instance is healthy.

        Args:
            host: Instance IP address.
            port: Instance port.
            namespace: Nacos namespace ID.

        Returns:
            True if the instance is healthy, False otherwise.

        Raises:
            NacosConnectionError: If connection to Nacos fails.
        """
        params = self._build_auth_params()
        params["serviceName"] = "__nacos^naming*"
        params["ip"] = host
        params["port"] = port
        params["namespaceId"] = namespace

        url = f"{self.nacos_addr}/nacos/v1/ns/instance/health"

        try:
            session = await self._get_session()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    text = await response.text()
                    return text.lower() == "ok"
                return False

        except aiohttp.ClientError as e:
            logger.error(f"Failed to check instance health: {e}")
            return False

    async def test_connectivity(
        self,
        namespace: str = "public"
    ) -> Dict[str, Any]:
        """Test connectivity to the Nacos server.

        Args:
            namespace: Nacos namespace ID to test connectivity with.

        Returns:
            Dict containing:
            - success: Whether the connection was successful
            - message: Human-readable message about the result
        """
        try:
            session = await self._get_session()

            access_token = None
            if self.username and self.password:
                access_token = await self._get_access_token(session)
                if not access_token:
                    return {
                        "success": False,
                        "message": "Authentication failed. Please check username and password."
                    }

            url = f"{self.nacos_addr}/nacos/v3/admin/ns/ops/metrics"
            headers = {}
            if access_token:
                headers["AccessToken"] = access_token

            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 0:
                        return {
                            "success": True,
                            "message": "Successfully connected to Nacos server"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"Nacos API error: {data.get('message', 'unknown')}"
                        }
                elif response.status == 403:
                    return {
                        "success": False,
                        "message": "Authentication failed. Please check username and password."
                    }
                else:
                    text = await response.text()
                    return {
                        "success": False,
                        "message": f"Nacos server returned status {response.status}: {text}"
                    }

        except aiohttp.ClientError as e:
            logger.error(f"Failed to connect to Nacos at {self.nacos_addr}: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to Nacos server: {e}"
            }

    async def _get_access_token(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Get access token from Nacos authentication endpoint with caching.

        Args:
            session: aiohttp session to use for the request.

        Returns:
            Access token string if authentication successful, None otherwise.
        """
        if self._access_token:
            return self._access_token

        try:
            url = f"{self.nacos_addr}/nacos/v1/auth/login"
            form_data = aiohttp.FormData()
            form_data.add_field("username", self.username)
            form_data.add_field("password", self.password)

            async with session.post(url, data=form_data) as response:
                if response.status == 200:
                    result = await response.json()
                    token = result.get("accessToken")
                    if token:
                        self._access_token = token
                        return token
                    logger.warning(f"Nacos login failed: {result.get('message', 'unknown')}")
                else:
                    text = await response.text()
                    logger.warning(f"Nacos login request returned status {response.status}: {text}")
                return None

        except aiohttp.ClientError as e:
            logger.error(f"Failed to login to Nacos: {e}")
            return None

    def _clear_access_token(self) -> None:
        """Clear the cached access token."""
        self._access_token = None

    async def __aenter__(self) -> "NacosClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
