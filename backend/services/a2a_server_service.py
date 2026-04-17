"""
A2A Server Service.

This service manages A2A Server endpoints - exposing local Nexent agents as A2A endpoints
for external callers.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from database import a2a_agent_db
from database.a2a_agent_db import PROTOCOL_HTTP_JSON, PROTOCOL_JSONRPC
from database.client import get_db_session
from services.a2a_agent_adapter import A2AAgentAdapter, A2AExecutionContext
from consts.a2a_models import A2AAgentCard, A2AAgentCapabilities, A2AAgentProvider
from consts.const import NORTHBOUND_EXTERNAL_URL

logger = logging.getLogger(__name__)


class A2AServerServiceError(Exception):
    """Base exception for A2A Server Service errors."""
    pass


class EndpointNotFoundError(A2AServerServiceError):
    """Raised when endpoint is not found."""
    pass


class AgentNotEnabledError(A2AServerServiceError):
    """Raised when agent A2A Server is not enabled."""
    pass


class TaskNotFoundError(A2AServerServiceError):
    """Raised when A2A task is not found (per A2A spec Section 3.4.2)."""
    pass


class UnsupportedOperationError(A2AServerServiceError):
    """Raised when A2A operation is not supported (e.g., task already terminated)."""
    pass


class TaskNotFoundError(A2AServerServiceError):
    """Raised when task is not found."""
    pass


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    return f"task_{uuid4().hex}"


def _generate_endpoint_id(agent_id: int) -> str:
    """Generate a unique endpoint ID."""
    return f"a2a_{agent_id}_{uuid4().hex[:8]}"


class A2AServerService:
    """Service for managing A2A Server endpoints."""

    def __init__(self):
        self.adapter = A2AAgentAdapter()

    # =============================================================================
    # Agent Registration
    # =============================================================================

    def register_agent(
        self,
        agent_id: int,
        user_id: str,
        tenant_id: str,
        name: str,
        description: Optional[str] = None,
        version: Optional[str] = None,
        agent_url: Optional[str] = None,
        streaming: bool = False,
        supported_interfaces: Optional[List[Dict[str, Any]]] = None,
        card_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Register or update a local agent as A2A Server endpoint.

        Args:
            agent_id: Local agent ID.
            user_id: Owner user ID.
            tenant_id: Tenant ID.
            name: Agent name exposed in Agent Card.
            description: Agent description.
            version: Agent version.
            agent_url: Primary A2A endpoint URL.
            streaming: Whether streaming is supported.
            supported_interfaces: All supported interfaces.
            card_overrides: Optional Agent Card customizations.

        Returns:
            Server agent registration info.
        """
        return a2a_agent_db.create_server_agent(
            agent_id=agent_id,
            user_id=user_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            version=version,
            agent_url=agent_url,
            streaming=streaming,
            supported_interfaces=supported_interfaces,
            card_overrides=card_overrides
        )

    def unregister_agent(self, agent_id: int, tenant_id: str, user_id: str) -> bool:
        """Unregister an A2A Server endpoint.

        Args:
            agent_id: Local agent ID.
            tenant_id: Tenant ID.
            user_id: User requesting unregistration.

        Returns:
            True if unregistered, False if not found.
        """
        return a2a_agent_db.disable_server_agent(agent_id, tenant_id, user_id)

    def get_registration(self, agent_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get A2A Server registration for an agent.

        Args:
            agent_id: Local agent ID.
            tenant_id: Tenant ID.

        Returns:
            Registration info or None.
        """
        return a2a_agent_db.get_server_agent_by_agent_id(agent_id, tenant_id)

    def list_registrations(
        self,
        tenant_id: str,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all A2A Server registrations.

        Args:
            tenant_id: Tenant ID.
            user_id: Optional filter by owner.

        Returns:
            List of registration info.
        """
        return a2a_agent_db.list_server_agents(tenant_id, user_id)

    # =============================================================================
    # Enable/Disable
    # =============================================================================

    def enable_a2a(
        self,
        agent_id: int,
        tenant_id: str,
        user_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        agent_url: Optional[str] = None,
        streaming: bool = False,
        supported_interfaces: Optional[List[Dict[str, Any]]] = None,
        card_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Enable A2A Server for an agent.

        Args:
            agent_id: Local agent ID.
            tenant_id: Tenant ID.
            user_id: User requesting enable.
            name: Agent name exposed in Agent Card.
            description: Agent description.
            version: Agent version.
            agent_url: Primary A2A endpoint URL.
            streaming: Whether streaming is supported.
            supported_interfaces: All supported interfaces.
            card_overrides: Optional Agent Card customizations.

        Returns:
            Updated registration info.

        Raises:
            EndpointNotFoundError: If registration not found.
        """
        result = a2a_agent_db.enable_server_agent(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            description=description,
            version=version,
            agent_url=agent_url,
            streaming=streaming,
            supported_interfaces=supported_interfaces,
            card_overrides=card_overrides
        )

        if not result:
            raise EndpointNotFoundError(f"No registration found for agent {agent_id}")

        logger.info(f"Enabled A2A Server for agent {agent_id}")
        return result

    def disable_a2a(self, agent_id: int, tenant_id: str, user_id: str) -> bool:
        """Disable A2A Server for an agent.

        Args:
            agent_id: Local agent ID.
            tenant_id: Tenant ID.
            user_id: User requesting disable.

        Returns:
            True if disabled.

        Raises:
            EndpointNotFoundError: If registration not found.
        """
        result = a2a_agent_db.disable_server_agent(agent_id, tenant_id, user_id)

        if not result:
            raise EndpointNotFoundError(f"No registration found for agent {agent_id}")

        logger.info(f"Disabled A2A Server for agent {agent_id}")
        return result

    def update_settings(
        self,
        agent_id: int,
        tenant_id: str,
        user_id: str,
        is_enabled: Optional[bool] = None,
        card_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Update A2A Server settings.

        Args:
            agent_id: Local agent ID.
            tenant_id: Tenant ID.
            user_id: User requesting update.
            is_enabled: Optional enable/disable.
            card_overrides: Optional Agent Card customizations.

        Returns:
            Updated registration info.

        Raises:
            EndpointNotFoundError: If registration not found.
        """
        current = a2a_agent_db.get_server_agent_by_agent_id(agent_id, tenant_id)
        if not current:
            raise EndpointNotFoundError(f"No registration found for agent {agent_id}")

        if is_enabled is not None:
            if is_enabled:
                return self.enable_a2a(
                    agent_id, tenant_id, user_id,
                    card_overrides=card_overrides
                )
            else:
                self.disable_a2a(agent_id, tenant_id, user_id)
                return {**current, "is_enabled": False}

        # Update card overrides without changing enabled state
        from datetime import datetime, timezone
        with get_db_session() as session:
            from database.db_models import A2AServerAgent
            agent = session.query(A2AServerAgent).filter(
                A2AServerAgent.agent_id == agent_id,
                A2AServerAgent.tenant_id == tenant_id,
                A2AServerAgent.delete_flag != 'Y'
            ).first()

            if agent:
                if card_overrides is not None:
                    agent.card_overrides = card_overrides
                agent.updated_by = user_id

        return a2a_agent_db.get_server_agent_by_agent_id(agent_id, tenant_id)

    # =============================================================================
    # Agent Card
    # =============================================================================

    def _resolve_base_url(self, use_northbound: bool, base_url: Optional[str]) -> str:
        """Resolve effective base URL with priority: NORTHBOUND_EXTERNAL_URL > base_url > empty."""
        if use_northbound:
            return NORTHBOUND_EXTERNAL_URL
        if base_url:
            return base_url
        logger.warning("A2A Agent Card: no base URL available")
        return ""

    def _resolve_agent_url(self, stored_url: Optional[str], effective_base: str) -> str:
        """Resolve the primary agent URL: stored URL > constructed from base."""
        if stored_url:
            return stored_url
        return effective_base.rstrip("/") if effective_base else ""

    def _build_agent_card_base(
        self,
        name: str,
        description: str,
        version: str,
        streaming: bool,
        effective_base_url: str,
        supported_interfaces: List[Dict[str, Any]],
        agent_url: str,
        agent_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build the base Agent Card dict before applying overrides."""
        return {
            "name": name,
            "description": description,
            "version": version,
            "provider": {
                "organization": "Nexent",
                "url": effective_base_url or "https://nexent.ai"
            },
            "capabilities": {
                "streaming": streaming,
                "pushNotifications": False,
                "extendedAgentCard": False,
                "stateTransitionHistory": False,
            },
            "defaultInputModes": ["text/plain", "application/json"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": self._build_skills_from_agent(agent_info),
            "supportedInterfaces": supported_interfaces,
            "url": agent_url,
            "securitySchemes": {},
            "security": [],
        }

    def get_agent_card(
        self,
        endpoint_id: str,
        base_url: Optional[str] = None,
        use_northbound: bool = True
    ) -> Dict[str, Any]:
        """Generate Agent Card for an endpoint.

        Args:
            endpoint_id: The endpoint ID.
            base_url: Optional base URL override for constructing endpoint URLs.

        Returns:
            Agent Card dict.

        Raises:
            EndpointNotFoundError: If endpoint not found or disabled.
        """
        server_agent = a2a_agent_db.get_server_agent_by_endpoint(endpoint_id)
        if not server_agent:
            raise EndpointNotFoundError(f"Endpoint {endpoint_id} not found")
        if not server_agent.get("is_enabled"):
            raise EndpointNotFoundError(f"Endpoint {endpoint_id} is not enabled")

        from database.agent_db import search_agent_info_by_agent_id
        agent_info = search_agent_info_by_agent_id(
            agent_id=server_agent["agent_id"],
            tenant_id=server_agent["tenant_id"]
        )

        name = server_agent.get("name") or agent_info.get("name", "Nexent Agent")
        description = server_agent.get("description") or agent_info.get("description", "")
        version = server_agent.get("version") or "1.0.0"
        streaming = server_agent.get("streaming", False)

        effective_base_url = self._resolve_base_url(use_northbound, base_url)
        prefix = "/nb/a2a" if use_northbound else "/a2a"

        if effective_base_url:
            supported_interfaces = self._build_supported_interfaces(effective_base_url, endpoint_id, prefix)
        else:
            supported_interfaces = []

        agent_url = self._resolve_agent_url(server_agent.get("agent_url"), effective_base_url)

        agent_card = self._build_agent_card_base(
            name=name,
            description=description,
            version=version,
            streaming=streaming,
            effective_base_url=effective_base_url,
            supported_interfaces=supported_interfaces,
            agent_url=agent_url,
            agent_info=agent_info
        )

        card_overrides = server_agent.get("card_overrides", {})
        if card_overrides:
            agent_card.update(card_overrides)

        return agent_card

    def _build_supported_interfaces(self, base_url: str, endpoint_id: str, prefix: str = "/a2a") -> List[Dict[str, Any]]:
        """Build supportedInterfaces array per A2A 1.0 spec.

        Args:
            base_url: Base URL for constructing endpoint URLs.
            endpoint_id: The endpoint ID.
            prefix: URL prefix for the API (default "/a2a", use "/nb/a2a" for northbound).

        Returns:
            List of supported interfaces.
        """
        base = base_url.rstrip("/") if base_url else ""
        return [
            {"protocolBinding": PROTOCOL_JSONRPC, "url": f"{base}{prefix}/{endpoint_id}/v1", "protocolVersion": "1.0"},
            {"protocolBinding": PROTOCOL_HTTP_JSON, "url": f"{base}{prefix}/{endpoint_id}", "protocolVersion": "1.0"},
        ]

    def _build_skills_from_agent(self, agent_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build skills array from agent configuration."""
        return [
            {
                "id": "chat",
                "name": agent_info.get("name", "Nexent Agent"),
                "description": agent_info.get("description", "AI conversation assistant"),
                "tags": ["chat", "conversation", "assistant"],
                "examples": ["Hello", "Help me query"],
            }
        ]

    # =============================================================================
    # Task Management
    # =============================================================================

    TERMINAL_STATES = frozenset(("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED"))

    def _validate_endpoint(self, endpoint_id: str) -> Dict[str, Any]:
        """Validate endpoint exists and is enabled. Returns server_agent dict."""
        server_agent = a2a_agent_db.get_server_agent_by_endpoint(endpoint_id)
        if not server_agent:
            raise EndpointNotFoundError(f"Endpoint {endpoint_id} not found")
        if not server_agent.get("is_enabled"):
            raise AgentNotEnabledError(f"A2A Server not enabled for endpoint {endpoint_id}")
        return server_agent

    def _resolve_task_id(
        self,
        parsed_message: Dict[str, Any],
        endpoint_id: str,
        user_id: Optional[str],
        tenant_id: Optional[str],
        server_agent: Dict[str, Any],
    ) -> tuple[Optional[str], Optional[str], bool]:
        """Resolve task_id, context_id, and is_complex flag from parsed A2A message.

        Returns:
            Tuple of (task_id, context_id, is_complex_request).
        Raises TaskNotFoundError or UnsupportedOperationError on invalid client taskId.
        """
        message_obj = parsed_message.get("message", {})
        client_task_id = message_obj.get("taskId")
        context_id = message_obj.get("contextId")
        has_history = bool(parsed_message.get("history"))
        is_complex_request = bool(context_id or has_history or client_task_id)

        if client_task_id:
            existing_task = a2a_agent_db.get_task(client_task_id)
            if not existing_task:
                raise TaskNotFoundError(f"Task {client_task_id} not found")
            if existing_task.get("task_state") in self.TERMINAL_STATES:
                raise UnsupportedOperationError(f"Task {client_task_id} is already terminated")
            task_id = client_task_id
        elif is_complex_request:
            task_id = _generate_task_id()
        else:
            task_id = None

        if is_complex_request and not client_task_id:
            a2a_agent_db.create_task(
                task_id=task_id,
                endpoint_id=endpoint_id,
                caller_user_id=user_id,
                caller_tenant_id=tenant_id,
                raw_request=parsed_message.get("raw_request", {}),
                context_id=context_id
            )

        return task_id, context_id, is_complex_request

    async def _collect_stream_text(self, stream_response) -> str:
        """Collect and accumulate text from a streaming response."""
        accumulated = []
        async for chunk in stream_response.body_iterator:
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8")
            if chunk.startswith("data: "):
                data_str = chunk[6:].strip()
                if not data_str:
                    continue
                try:
                    chunk_data = json.loads(data_str)
                    text = self.adapter.extract_stream_chunk(chunk_data)
                    if text:
                        accumulated.append(text)
                except json.JSONDecodeError:
                    pass
        return "".join(accumulated)

    def _store_user_message(self, task_id: Optional[str], message_obj: Dict[str, Any], endpoint_id: str) -> None:
        """Extract and store user message parts."""
        user_parts = message_obj.get("parts", [])
        if not user_parts and message_obj.get("text"):
            user_parts = [{"type": "text", "text": message_obj.get("text")}]
        a2a_agent_db.create_message(
            task_id=task_id,
            role="ROLE_USER",
            parts=user_parts,
            metadata={"endpoint_id": endpoint_id}
        )

    def _store_agent_response(self, task_id: Optional[str], accumulated_text: str, endpoint_id: str) -> None:
        """Store agent response and update task state."""
        agent_parts = [{"type": "text", "text": accumulated_text, "mediaType": "text/plain"}] if accumulated_text else []
        a2a_agent_db.create_message(
            task_id=task_id,
            role="ROLE_AGENT",
            parts=agent_parts,
            metadata={"endpoint_id": endpoint_id}
        )
        if task_id:
            a2a_agent_db.update_task_state(
                task_id=task_id,
                task_state="TASK_STATE_COMPLETED",
                result_data={"message": accumulated_text}
            )

    def _store_error_response(self, task_id: Optional[str], error: str, endpoint_id: str) -> None:
        """Store error message and update task state on failure."""
        error_parts = [{"type": "text", "text": f"Error: {error}", "mediaType": "text/plain"}]
        a2a_agent_db.create_message(
            task_id=task_id,
            role="ROLE_AGENT",
            parts=error_parts,
            metadata={"endpoint_id": endpoint_id, "error": True}
        )
        if task_id:
            a2a_agent_db.update_task_state(
                task_id=task_id,
                task_state="TASK_STATE_FAILED",
                result_data={"error": error}
            )

    async def handle_message_send(
        self,
        endpoint_id: str,
        message: Dict[str, Any],
        token_id: Optional[int] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        base_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Handle incoming message:send request.

        This is a synchronous request that waits for task completion.

        Args:
            endpoint_id: The endpoint ID.
            message: A2A message payload.
            token_id: Token ID from authentication.
            user_id: User ID from authentication.
            tenant_id: Tenant ID from authentication.
            base_url: Optional base URL.

        Returns:
            A2A Task response.

        Raises:
            EndpointNotFoundError: If endpoint not found.
            AgentNotEnabledError: If agent is not enabled.
        """
        server_agent = self._validate_endpoint(endpoint_id)
        parsed_message = self.adapter.parse_a2a_message(message)
        message_obj = parsed_message.get("message", {})

        task_id, context_id, is_complex_request = self._resolve_task_id(
            parsed_message, endpoint_id, user_id, tenant_id, server_agent
        )

        context = A2AExecutionContext(
            task_id=task_id or "simple",
            endpoint_id=endpoint_id,
            token_id=token_id,
            user_id=user_id,
            tenant_id=tenant_id or server_agent.get("tenant_id"),
            correlation_id=message.get("correlationId"),
            metadata=message.get("metadata", {}),
            is_debug=True
        )

        self._store_user_message(task_id, message_obj, endpoint_id)

        internal_request = self.adapter.build_agent_request(
            parsed_message,
            context,
            server_agent["agent_id"]
        )

        try:
            from services.agent_service import run_agent_stream
            from consts.model import AgentRequest
            from starlette.requests import Request

            agent_request = AgentRequest(
                conversation_id=None,
                agent_id=internal_request["agent_id"],
                query=internal_request["query"],
                history=internal_request.get("history", []),
                minio_files=None,
                is_debug=internal_request.get("is_debug", True)
            )

            mock_request = Request({
                "type": "http",
                "method": "POST",
                "path": f"/a2a/{endpoint_id}/message:send",
                "headers": [],
                "query_string": b""
            })

            stream_response = await run_agent_stream(
                agent_request=agent_request,
                http_request=mock_request,
                authorization=None,
                user_id=user_id,
                tenant_id=tenant_id or server_agent.get("tenant_id")
            )

            accumulated_text = await self._collect_stream_text(stream_response)
            self._store_agent_response(task_id, accumulated_text, endpoint_id)

            if is_complex_request:
                from datetime import datetime, timezone
                return self.adapter.build_a2a_task_response(
                    task_id=task_id,
                    status="TASK_STATE_COMPLETED",
                    parts=[{"type": "text", "text": accumulated_text, "mediaType": "text/plain"}] if accumulated_text else None,
                    context_id=context_id,
                    timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                )
            else:
                return self.adapter.build_a2a_message_response(
                    role="ROLE_AGENT",
                    text=accumulated_text,
                    context_id=context_id,
                    task_id=task_id
                )

        except Exception as e:
            logger.error(f"A2A task execution failed: {e}")
            self._store_error_response(task_id, str(e), endpoint_id)
            return self.adapter.build_a2a_message_response(
                role="ROLE_AGENT",
                text=f"Error: {str(e)}",
                context_id=context_id,
                task_id=task_id
            )

    async def handle_message_stream(
        self,
        endpoint_id: str,
        message: Dict[str, Any],
        token_id: Optional[int] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Handle incoming message:stream request.

        This is a streaming request that yields task events.

        Args:
            endpoint_id: The endpoint ID.
            message: A2A message payload.
            token_id: Token ID from authentication.
            user_id: User ID from authentication.
            tenant_id: Tenant ID from authentication.
            base_url: Optional base URL.

        Yields:
            A2A Task events.

        Raises:
            EndpointNotFoundError: If endpoint not found.
            AgentNotEnabledError: If agent is not enabled.
        """
        server_agent = self._validate_endpoint(endpoint_id)
        parsed_message = self.adapter.parse_a2a_message(message)
        message_obj = parsed_message.get("message", {})

        task_id, context_id, _ = self._resolve_task_id(
            parsed_message, endpoint_id, user_id, tenant_id, server_agent
        )

        context = A2AExecutionContext(
            task_id=task_id or "simple",
            endpoint_id=endpoint_id,
            token_id=token_id,
            user_id=user_id,
            tenant_id=tenant_id or server_agent.get("tenant_id"),
            correlation_id=message.get("correlationId"),
            metadata=message.get("metadata", {}),
            is_debug=True
        )

        self._store_user_message(task_id, message_obj, endpoint_id)

        # Yield initial working status
        yield self.adapter.build_a2a_task_event(
            task_id=task_id or "simple",
            event_type="taskStatusUpdate",
            data={"status": {"state": "TASK_STATE_WORKING"}},
            context_id=context_id
        )

        internal_request = self.adapter.build_agent_request(
            parsed_message,
            context,
            server_agent["agent_id"]
        )

        try:
            from consts.model import AgentRequest
            from starlette.requests import Request

            agent_request = AgentRequest(
                conversation_id=None,
                agent_id=internal_request["agent_id"],
                query=internal_request["query"],
                history=internal_request.get("history", []),
                minio_files=None,
                is_debug=internal_request.get("is_debug", True)
            )

            mock_request = Request({
                "type": "http",
                "method": "POST",
                "path": f"/a2a/{endpoint_id}/message:stream",
                "headers": [],
                "query_string": b""
            })

            from services.agent_service import run_agent_stream
            stream_response = await run_agent_stream(
                agent_request=agent_request,
                http_request=mock_request,
                authorization=None,
                user_id=user_id,
                tenant_id=tenant_id or server_agent.get("tenant_id")
            )

            accumulated_text = ""
            async for chunk in stream_response.body_iterator:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8")
                if not chunk.startswith("data: "):
                    continue
                data_str = chunk[6:].strip()
                if not data_str:
                    continue
                try:
                    chunk_data = json.loads(data_str)
                    text = self.adapter.extract_stream_chunk(chunk_data)
                    if text:
                        accumulated_text += text
                        yield self.adapter.build_a2a_task_event(
                            task_id=task_id,
                            event_type="taskProgress",
                            data={"content": text, "lastChunk": False},
                            context_id=context_id
                        )
                except json.JSONDecodeError:
                    pass

            self._store_agent_response(task_id, accumulated_text, endpoint_id)

            yield self.adapter.build_a2a_task_event(
                task_id=task_id or "simple",
                event_type="taskProgress",
                data={"content": accumulated_text, "lastChunk": True},
                context_id=context_id
            )

            from datetime import datetime, timezone
            yield self.adapter.build_a2a_task_event(
                task_id=task_id or "simple",
                event_type="taskStatusUpdate",
                data={
                    "status": {
                        "state": "TASK_STATE_COMPLETED",
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    }
                },
                context_id=context_id
            )

        except Exception as e:
            logger.error(f"A2A streaming task failed: {e}")
            self._store_error_response(task_id, str(e), endpoint_id)
            yield self.adapter.build_a2a_task_event(
                task_id=task_id or "simple",
                event_type="taskStatusUpdate",
                data={"status": {"state": "TASK_STATE_FAILED", "message": str(e)}},
                context_id=context_id
            )

    def get_task(
        self,
        task_id: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get task details in A2A standard format.

        Args:
            task_id: The task ID.
            user_id: User ID for authorization.
            tenant_id: Tenant ID for authorization.

        Returns:
            Task information in A2A standard format with history.

        Raises:
            TaskNotFoundError: If task not found.
        """
        task = a2a_agent_db.get_task(task_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found")

        # Verify authorization
        if user_id and task.get("caller_user_id") != user_id:
            raise A2AServerServiceError("Unauthorized: caller does not match task owner")

        # Build A2A standard response format following A2A 1.0 spec
        task_state = task.get("task_state", "TASK_STATE_UNKNOWN")

        # Map internal status to A2A TASK_STATE format (already in TASK_STATE format)
        state_map = {
            "TASK_STATE_WORKING": "TASK_STATE_WORKING",
            "TASK_STATE_COMPLETED": "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED": "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED": "TASK_STATE_CANCELED",
            "TASK_STATE_INPUT_REQUIRED": "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_REJECTED": "TASK_STATE_REJECTED",
            "TASK_STATE_AUTH_REQUIRED": "TASK_STATE_AUTH_REQUIRED",
        }
        a2a_state = state_map.get(task_state, task_state)

        current_time = task.get("update_time") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Build task object
        task_obj = {
            "id": task["id"],
            "status": {
                "state": a2a_state,
                "timestamp": current_time
            }
        }

        # Add contextId if available
        if task.get("context_id"):
            task_obj["contextId"] = task["context_id"]

        # Add result as artifact if exists
        result = task.get("result")
        if result:
            message = result.get("message", "")
            if message:
                task_obj["artifacts"] = [{
                    "parts": [{"type": "text", "text": str(message)}],
                    "lastChunk": True
                }]

        return task_obj

    def list_tasks(
        self,
        endpoint_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List tasks.

        Args:
            endpoint_id: Optional filter by endpoint.
            user_id: Optional filter by caller.
            tenant_id: Optional filter by tenant.
            status: Optional filter by status.
            limit: Maximum results.
            offset: Results offset.

        Returns:
            List of tasks.
        """
        return a2a_agent_db.list_tasks(
            endpoint_id=endpoint_id,
            caller_user_id=user_id,
            caller_tenant_id=tenant_id,
            status=status,
            limit=limit,
            offset=offset
        )

    def list_tasks_paginated(
        self,
        endpoint_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[Dict[str, Any]] = None
    ) -> tuple[List[Dict[str, Any]], Optional[str]]:
        """List tasks with cursor-based pagination.

        Args:
            endpoint_id: Optional filter by endpoint.
            user_id: Optional filter by caller.
            tenant_id: Optional filter by tenant.
            status: Optional filter by status.
            limit: Maximum results.
            cursor: Optional cursor dict with update_time.

        Returns:
            Tuple of (tasks list, next_page_token or None).
        """
        import base64
        tasks, next_token = a2a_agent_db.list_tasks_paginated(
            endpoint_id=endpoint_id,
            caller_user_id=user_id,
            caller_tenant_id=tenant_id,
            status=status,
            limit=limit,
            cursor=cursor
        )
        return tasks, next_token

    def cancel_task(
        self,
        task_id: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Cancel a task.

        Args:
            task_id: The task ID.
            user_id: User ID for authorization.
            tenant_id: Tenant ID for authorization.

        Returns:
            Updated task info.

        Raises:
            TaskNotFoundError: If task not found.
        """
        # Get task first for authorization check
        task = a2a_agent_db.get_task(task_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found")

        # Verify authorization
        if user_id and task.get("caller_user_id") != user_id:
            raise A2AServerServiceError("Unauthorized: caller does not match task owner")

        # Cancel task
        result = a2a_agent_db.cancel_task(task_id)
        if not result:
            raise A2AServerServiceError(f"Task {task_id} cannot be canceled (may already be completed)")

        return a2a_agent_db.get_task(task_id)


# Singleton instance
a2a_server_service = A2AServerService()
