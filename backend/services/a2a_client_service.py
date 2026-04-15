"""
A2A Client Service.

This service provides functionality for discovering and calling external A2A agents.
Used internally by Nexent to call external A2A agents as sub-agents (similar to MCP pattern).
"""
import asyncio
import logging
import aiohttp
from typing import Any, AsyncIterator, Dict, List, Optional

from database import a2a_agent_db
from database.a2a_agent_db import _extract_protocol_type, PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC
from utils.a2a_http_client import A2AHttpClient, build_a2a_headers

logger = logging.getLogger(__name__)


class A2AClientServiceError(Exception):
    """Base exception for A2A Client Service errors."""
    pass


class AgentDiscoveryError(A2AClientServiceError):
    """Raised when agent discovery fails."""
    pass


class AgentCallError(A2AClientServiceError):
    """Raised when calling an external agent fails."""
    pass


class A2AClientService:
    """Service for discovering and calling external A2A agents."""

    def __init__(self):
        pass

    # =============================================================================
    # Agent Discovery
    # =============================================================================

    async def discover_from_url(
        self,
        url: str,
        tenant_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Discover an external A2A agent from a URL.

        Fetches the Agent Card from the URL, caches it, and stores the agent info.

        Args:
            url: Direct URL to the Agent Card (e.g., https://example.com/.well-known/agent-xxx.json).
            tenant_id: Tenant ID for isolation.
            user_id: User who initiated the discovery.

        Returns:
            Discovered agent information dict.

        Raises:
            AgentDiscoveryError: If discovery fails.
        """
        try:
            async with A2AHttpClient() as client:
                headers = build_a2a_headers()
                card = await client.get_json(url, headers=headers)

            # Extract agent info from Card
            # Support multiple field names for agent ID
            agent_id = (
                card.get("agent_id") 
                or card.get("id") 
                or card.get("endpoint_id")
                or card.get("name")  # Fallback to name if no ID
            )
            if not agent_id:
                # Generate a hash-based ID from name and URL as last resort
                import hashlib
                name = card.get("name", "unknown")
                url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                agent_id = f"{name.lower().replace(' ', '-')}-{url_hash}"

            name = card.get("name", agent_id)
            description = card.get("description", "")

            # Extract endpoint URL - prioritize supportedInterfaces (A2A v1.0 standard)
            agent_url = self._extract_agent_url(card)

            # Extract protocol info and supported interfaces
            capabilities = card.get("capabilities", {})
            protocol_version = capabilities.get("protocolVersion", "1.0")
            streaming = capabilities.get("streaming", False)
            transport_type = "http-streaming" if streaming else "http-polling"

            # Extract supported interfaces (A2A v1.0 standard format)
            supported_interfaces = card.get("supportedInterfaces", [])

            # Store in database
            result = a2a_agent_db.create_external_agent_from_url(
                source_url=url,
                name=name,
                description=description,
                agent_url=agent_url,
                version=protocol_version,
                streaming=(transport_type == "http-streaming"),
                tenant_id=tenant_id,
                user_id=user_id,
                raw_card=card,
                supported_interfaces=supported_interfaces
            )

            logger.info(f"Discovered A2A agent {agent_id} from URL: {url}")
            return result

        except Exception as e:
            import traceback
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(
                f"Agent discovery failed for {url}: [{error_type}] {error_msg}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            raise AgentDiscoveryError(f"Discovery failed: [{error_type}] {error_msg}") from e

    async def discover_from_nacos(
        self,
        nacos_config_id: str,
        agent_names: List[str],
        tenant_id: str,
        user_id: str,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Discover external A2A agents from Nacos service registry.

        Args:
            nacos_config_id: Nacos config ID for connection settings.
            agent_names: List of agent names to discover.
            tenant_id: Tenant ID for isolation.
            user_id: User who initiated the discovery.
            namespace: Optional Nacos namespace override.

        Returns:
            List of discovered agent information dicts.

        Raises:
            AgentDiscoveryError: If discovery fails.
        """
        # Get Nacos config
        nacos_config = a2a_agent_db.get_nacos_config_by_id(nacos_config_id, tenant_id)
        if not nacos_config:
            raise AgentDiscoveryError(f"Nacos config {nacos_config_id} not found")

        if not nacos_config.get("is_active"):
            raise AgentDiscoveryError(f"Nacos config {nacos_config_id} is not active")

        # Use namespace from config or parameter
        target_namespace = namespace or nacos_config.get("namespace_id", "public")

        discovered_agents = []
        errors = []

        # For each agent name, query Nacos and fetch Agent Card
        for agent_name in agent_names:
            try:
                agent_info = await self._discover_single_from_nacos(
                    nacos_config=nacos_config,
                    agent_name=agent_name,
                    namespace=target_namespace,
                    tenant_id=tenant_id,
                    user_id=user_id
                )
                if agent_info:
                    discovered_agents.append(agent_info)
            except Exception as e:
                logger.warning(f"Failed to discover agent '{agent_name}' from Nacos: {e}")
                errors.append({"name": agent_name, "error": str(e)})

        # Update last scan timestamp
        a2a_agent_db.update_nacos_config_last_scan(nacos_config_id, tenant_id)

        if not discovered_agents and errors:
            error_msg = "; ".join([f"{e['name']}: {e['error']}" for e in errors])
            raise AgentDiscoveryError(f"All agent discoveries failed: {error_msg}")

        logger.info(f"Discovered {len(discovered_agents)} agents from Nacos config {nacos_config_id}")
        return discovered_agents

    async def _discover_single_from_nacos(
        self,
        nacos_config: Dict[str, Any],
        agent_name: str,
        namespace: str,
        tenant_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Discover a single agent from Nacos.

        Args:
            nacos_config: Nacos configuration dict.
            agent_name: Agent name to discover.
            namespace: Nacos namespace.
            tenant_id: Tenant ID.
            user_id: User ID.

        Returns:
            Discovered agent info or None.
        """
        # Import Nacos client (lazy import to avoid hard dependency)
        try:
            from utils.nacos_client import NacosClient
        except ImportError:
            logger.warning("Nacos client not available, using mock discovery")
            return None

        nacos_addr = nacos_config["nacos_addr"]
        username = nacos_config.get("nacos_username")
        password = nacos_config.get("nacos_password")

        # Initialize Nacos client
        client = NacosClient(nacos_addr, username, password)

        try:
            # Query service instance from Nacos
            instance = await client.query_service_instance(agent_name, namespace)
            if not instance:
                logger.warning(f"No instance found for agent '{agent_name}' in Nacos")
                return None

            # Fetch Agent Card from instance
            agent_card_url = instance.get("metadata", {}).get("a2a_card_url")
            if not agent_card_url:
                # Construct URL from instance host/port
                host = instance.get("ip")
                port = instance.get("port")
                if host and port:
                    agent_card_url = f"http://{host}:{port}/.well-known/agent-{agent_name}.json"

            if not agent_card_url:
                logger.warning(f"No Agent Card URL found for agent '{agent_name}'")
                return None

            # Fetch Agent Card
            async with A2AHttpClient() as http_client:
                card = await http_client.get_json(agent_card_url)

            # Extract endpoint URL and supported interfaces
            agent_url = self._extract_agent_url(card)
            supported_interfaces = card.get("supportedInterfaces", [])

            # Store in database
            result = a2a_agent_db.create_external_agent_from_nacos(
                name=card.get("name", agent_name),
                description=card.get("description", ""),
                agent_url=agent_url,
                protocol_version=card.get("capabilities", {}).get("protocolVersion", "1.0"),
                transport_type="http-streaming" if card.get("capabilities", {}).get("streaming") else "http-polling",
                nacos_config_id=nacos_config["config_id"],
                nacos_agent_name=agent_name,
                tenant_id=tenant_id,
                user_id=user_id,
                raw_card=card,
                supported_interfaces=supported_interfaces
            )

            return result

        finally:
            await client.close()

    def _extract_agent_url(self, card: Dict[str, Any]) -> str:
        """Extract the A2A endpoint URL from an Agent Card.

        According to A2A v1.0 specification, the agent URL should be extracted
        from supportedInterfaces array, prioritizing http-json-rpc protocol.

        Args:
            card: Agent Card dict.

        Returns:
            A2A endpoint URL string.
        """
        url = self._find_url_in_interfaces(card.get("supportedInterfaces", []))
        if url:
            return url

        url = self._find_url_in_endpoints(card.get("endpoints", {}))
        if url:
            return url

        provider = card.get("provider", {})
        if isinstance(provider, dict):
            url = provider.get("url", "")
            if url:
                return url

        url = card.get("url", "")
        if url:
            return url

        logger.warning("_extract_agent_url: No URL found in Agent Card")
        return ""

    def _find_url_in_interfaces(self, interfaces: List[Any]) -> str:
        """Find URL from supportedInterfaces array, preferring http-json-rpc."""
        json_rpc_protocols = ("http-json-rpc", "jsonrpc", "httpjsonrpc")
        for iface in interfaces:
            if iface.get("protocolBinding", "").lower() in json_rpc_protocols:
                url = iface.get("url", "")
                if url:
                    return url
        for iface in interfaces:
            url = iface.get("url", "")
            if url:
                return url
        return ""

    def _find_url_in_endpoints(self, endpoints: Dict[str, Any]) -> str:
        """Find URL from endpoints dict, preferring streaming then polling."""
        transport_preference = ("http-streaming", "http-polling")
        for transport in transport_preference:
            url = endpoints.get(transport, "")
            if url:
                return url
        first_key = next(iter(endpoints.keys()), None)
        if first_key:
            return endpoints[first_key]
        return ""

    # =============================================================================
    # Agent Management
    # =============================================================================

    def get_external_agent(self, external_agent_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get an external agent by ID.

        Args:
            external_agent_id: External agent database ID.
            tenant_id: Tenant ID for isolation.

        Returns:
            Agent information dict or None.
        """
        return a2a_agent_db.get_external_agent_by_id(external_agent_id, tenant_id)

    def list_external_agents(
        self,
        tenant_id: str,
        source_type: Optional[str] = None,
        is_available: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """List all discovered external agents for a tenant.

        Args:
            tenant_id: Tenant ID.
            source_type: Filter by source type (url or nacos).
            is_available: Filter by availability.

        Returns:
            List of agent information dicts.
        """
        return a2a_agent_db.list_external_agents(
            tenant_id=tenant_id,
            source_type=source_type,
            is_available=is_available
        )

    def update_agent_protocol(
        self,
        external_agent_id: int,
        tenant_id: str,
        protocol_type: str
    ) -> Optional[Dict[str, Any]]:
        """Update the protocol type for an external agent.

        Args:
            external_agent_id: External agent database ID.
            tenant_id: Tenant ID for isolation.
            protocol_type: New protocol type (JSONRPC, HTTP+JSON, or GRPC).

        Returns:
            Updated agent information dict or None if not found.
        """
        result = a2a_agent_db.update_external_agent_protocol(
            external_agent_id=external_agent_id,
            tenant_id=tenant_id,
            protocol_type=protocol_type
        )

        if result:
            logger.info(f"Updated agent {external_agent_id} protocol to {protocol_type}")

        return result

    async def refresh_agent_card(
        self,
        external_agent_id: int,
        tenant_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Refresh the cached Agent Card for an external agent.

        Args:
            external_agent_id: External agent database ID.
            tenant_id: Tenant ID.
            user_id: User who requested the refresh.

        Returns:
            Updated agent information.

        Raises:
            AgentDiscoveryError: If refresh fails.
        """
        # Get current agent info
        agent = a2a_agent_db.get_external_agent_by_id(external_agent_id, tenant_id)
        if not agent:
            raise AgentDiscoveryError(f"Agent {external_agent_id} not found")

        try:
            # Fetch fresh Agent Card
            source_url = agent.get("source_url")
            if not source_url:
                raise AgentDiscoveryError("No source URL available for refresh")

            async with A2AHttpClient() as client:
                card = await client.get_json(source_url)

            # Extract updated info - use _extract_agent_url for A2A v1.0 standard
            new_url = self._extract_agent_url(card)
            new_name = card.get("name")
            new_description = card.get("description")
            new_supported_interfaces = card.get("supportedInterfaces", [])

            # Note: Do NOT update protocol_type and agent_url during refresh
            # These are user-configured values and should not be overwritten
            # The refresh should only update metadata (name, description, supported_interfaces, raw_card)

            # Update cache
            result = a2a_agent_db.refresh_external_agent_cache(
                external_agent_id=external_agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                new_raw_card=card,
                new_name=new_name,
                new_description=new_description,
                new_supported_interfaces=new_supported_interfaces
            )

            # Update availability
            a2a_agent_db.update_agent_availability(
                external_agent_id=external_agent_id,
                tenant_id=tenant_id,
                is_available=True,
                check_result="OK"
            )

            logger.info(f"Refreshed agent {external_agent_id}")
            return result

        except aiohttp.ClientError as e:
            logger.error(f"Failed to refresh agent {external_agent_id}: {e}")
            a2a_agent_db.update_agent_availability(
                external_agent_id=external_agent_id,
                tenant_id=tenant_id,
                is_available=False,
                check_result="ERROR"
            )
            raise AgentDiscoveryError(f"Failed to refresh: {str(e)}") from e

    def delete_external_agent(self, external_agent_id: int, tenant_id: str) -> bool:
        """Delete a discovered external agent.

        Args:
            external_agent_id: External agent database ID.
            tenant_id: Tenant ID.

        Returns:
            True if deleted, False if not found.
        """
        return a2a_agent_db.delete_external_agent(external_agent_id, tenant_id)

    # =============================================================================
    # Agent Calling
    # =============================================================================

    def _build_endpoint_url(self, agent_url: str, protocol_type: str, streaming: bool = False) -> str:
        """Build the complete endpoint URL by appending protocol-specific path.

        Args:
            agent_url: Base agent URL from database.
            protocol_type: Protocol type (JSONRPC, HTTP+JSON, GRPC).
            streaming: Whether this is a streaming request.

        Returns:
            Complete endpoint URL with protocol path appended.
        """
        base_url = agent_url.rstrip("/")
        path_suffix = self._get_protocol_path(protocol_type, streaming)
        if path_suffix and path_suffix not in base_url:
            return f"{base_url}{path_suffix}"
        return base_url

    def _get_protocol_path(self, protocol_type: str, streaming: bool) -> str:
        """Get the path suffix for a given protocol type and streaming mode."""
        if protocol_type == PROTOCOL_HTTP_JSON:
            return "/message:stream" if streaming else "/message:send"
        if protocol_type == PROTOCOL_JSONRPC:
            return "/v1"
        return ""

    async def call_agent(
        self,
        external_agent_id: int,
        tenant_id: str,
        message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call an external A2A agent (non-streaming).

        Args:
            external_agent_id: External agent database ID to call.
            tenant_id: Tenant ID for isolation.
            message: A2A message payload.
            api_key: Optional API key for authentication.

        Returns:
            A2A Task result dict.

        Raises:
            AgentCallError: If the call fails.
        """
        # Get agent info
        agent = a2a_agent_db.get_external_agent_by_id(external_agent_id, tenant_id)
        if not agent:
            raise AgentCallError(f"Agent {external_agent_id} not found")

        if not agent.get("is_available"):
            raise AgentCallError(f"Agent {external_agent_id} is not available")

        agent_url = agent["agent_url"]
        protocol_type = agent.get("protocol_type", PROTOCOL_JSONRPC)

        # Build complete endpoint URL with protocol path
        endpoint_url = self._build_endpoint_url(agent_url, protocol_type, streaming=False)

        logger.info(f"[A2A-CLIENT] === Calling external A2A agent === id={external_agent_id}, url={endpoint_url}, protocol={protocol_type}, message={message}")

        try:
            # Build request based on protocol type
            if protocol_type == PROTOCOL_JSONRPC:
                # JSON-RPC 2.0 format
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "SendMessage",
                    "params": {
                        "message": message
                    }
                }
            else:
                # HTTP+JSON (REST) format - direct message payload
                payload = {
                    "message": message
                }

            logger.info(f"Calling external A2A agent {external_agent_id}: url={endpoint_url}, protocol={protocol_type}, payload={payload}")

            headers = build_a2a_headers()
            async with A2AHttpClient() as client:
                response = await client.post_json(endpoint_url, payload, headers)

            # Parse response
            if "error" in response:
                error = response["error"]
                raise AgentCallError(f"Agent error: {error.get('message', 'Unknown error')}")

            return response.get("result", response)

        except aiohttp.ClientError as e:
            logger.error(f"Failed to call agent {external_agent_id}: {e}")
            raise AgentCallError(f"Call failed: {str(e)}") from e

    async def call_agent_streaming(
        self,
        external_agent_id: int,
        tenant_id: str,
        message: Dict[str, Any],
        api_key: Optional[str] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Call an external A2A agent with streaming response.

        Args:
            external_agent_id: External agent database ID to call.
            tenant_id: Tenant ID for isolation.
            message: A2A message payload.
            api_key: Optional API key for authentication.

        Yields:
            A2A task events (taskProgress, taskArtifact, etc.).

        Raises:
            AgentCallError: If the call setup fails.
        """
        # Get agent info
        agent = a2a_agent_db.get_external_agent_by_id(external_agent_id, tenant_id)
        if not agent:
            raise AgentCallError(f"Agent {external_agent_id} not found")

        if not agent.get("is_available"):
            raise AgentCallError(f"Agent {external_agent_id} is not available")

        agent_url = agent["agent_url"]
        protocol_type = agent.get("protocol_type", PROTOCOL_JSONRPC)

        # Build complete endpoint URL with protocol path
        endpoint_url = self._build_endpoint_url(agent_url, protocol_type, streaming=True)

        # Build request based on protocol type
        if protocol_type == PROTOCOL_JSONRPC:
            # JSON-RPC 2.0 format
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "SendMessage",
                "params": {
                    "message": message
                }
            }
        else:
            # HTTP+JSON (REST) format - direct message payload
            payload = {
                "message": message
            }

        logger.info(f"Calling external A2A agent {external_agent_id} (streaming): url={endpoint_url}, protocol={protocol_type}, payload={payload}")

        headers = build_a2a_headers(api_key)

        try:
            async with A2AHttpClient() as client:
                async for event in client.post_stream(endpoint_url, payload, headers):
                    yield event
        except aiohttp.ClientError as e:
            logger.error(f"Streaming call failed for agent {external_agent_id}: {e}")
            raise AgentCallError(f"Streaming call failed: {str(e)}") from e

# Singleton instance
a2a_client_service = A2AClientService()
