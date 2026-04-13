"""
External A2A Agent Proxy Tool.

This tool allows Nexent agents to call external A2A agents as sub-agents.
It provides a unified interface for invoking remote A2A endpoints.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
from threading import Event
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("a2a_agent_proxy")


@dataclass
class A2AAgentInfo:
    """Configuration for an external A2A agent."""
    agent_id: str
    name: str
    url: str
    api_key: Optional[str] = None
    transport_type: str = "http-streaming"
    protocol_version: str = "1.0"
    protocol_type: str = "JSONRPC"  # Protocol type from database: JSONRPC, HTTP+JSON, GRPC
    timeout: float = 300.0
    raw_card: Optional[Dict[str, Any]] = None

    def get_protocol_type(self) -> str:
        """Get the protocol type for calling this agent.

        Returns:
            'JSONRPC', 'HTTP+JSON', or 'GRPC' from database field.
        """
        return self.protocol_type

    def get_skills_description(self) -> str:
        """Generate a description with capabilities from raw_card."""
        skills = []
        if self.raw_card:
            skills = self.raw_card.get("skills", [])
        
        if not skills:
            return f"External A2A agent: {self.name}"
        
        # Build capability description
        capability_names = [skill.get("name", "") for skill in skills if skill.get("name")]
        capability_str = "、".join(capability_names) if capability_names else ""
        
        # Build examples
        examples_lines = []
        for skill in skills:
            examples = skill.get("examples", [])
            if examples:
                examples_lines.extend(examples[:2])
        
        examples_section = ""
        if examples_lines:
            examples_str = ', '.join(f'"{ex}"' for ex in examples_lines[:6])
            examples_section = f"\n调用示例: {examples_str}"
        
        return f"External A2A agent: {self.name} [Capabilities: {capability_str}]{examples_section}"


class ExternalA2AAgentProxy:
    """Proxy for calling external A2A agents.

    This class provides methods to invoke external A2A agents
    using the A2A protocol (JSON-RPC 2.0).
    """

    def __init__(
        self,
        agent_info: A2AAgentInfo,
        stop_event: Optional[Event] = None
    ):
        """Initialize the A2A agent proxy.

        Args:
            agent_info: Configuration for the external A2A agent.
            stop_event: Optional stop event for cancellation.
        """
        self.agent_info = agent_info
        self.stop_event = stop_event or Event()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        # Configure httpx explicitly to match curl behavior
        # - HTTP/2 disabled to use HTTP/1.1 like curl
        # - trust_env=False to ignore proxy env vars
        # - limits configured for connection pool
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.agent_info.timeout),
            http2=False,  # Force HTTP/1.1 like curl
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            trust_env=False,  # Ignore HTTP_PROXY env vars
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers for A2A requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.agent_info.api_key:
            headers["Authorization"] = f"Bearer {self.agent_info.api_key}"
        return headers

    def _build_message_payload(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Build A2A message payload.

        Args:
            query: The user query.
            history: Optional conversation history.
            context: Optional context metadata.

        Returns:
            A2A message payload dict.
        """
        message = {
            "role": "ROLE_USER",
            "parts": [{"text": query}]
        }

        payload = {
            "message": message
        }

        if context:
            payload["metadata"] = context

        return payload

    def _get_endpoint_url(self, protocol_type: str, streaming: bool = False) -> str:
        """Get the endpoint URL for the A2A agent.

        Args:
            protocol_type: Protocol type (JSONRPC, HTTP+JSON, GRPC).
            streaming: Whether this is a streaming request.

        Returns:
            Complete endpoint URL.
        """
        base_url = self.agent_info.url.rstrip("/")

        # HTTP+JSON protocol requires /message:send or /message:stream path
        if protocol_type == "HTTP+JSON":
            # Check if URL already contains the full path (avoid duplicate)
            if streaming:
                if "/message:stream" not in base_url:
                    return f"{base_url}/message:stream"
                return base_url
            else:
                if "/message:send" not in base_url:
                    return f"{base_url}/message:send"
                return base_url

        # JSONRPC and other protocols use base URL directly
        return base_url

    async def call(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Call external A2A agent (non-streaming).

        Args:
            query: The user query.
            history: Optional conversation history.
            context: Optional context metadata.

        Returns:
            A2A response dict.

        Raises:
            httpx.HTTPError: On request failure.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        protocol_type = self.agent_info.get_protocol_type()
        endpoint_url = self._get_endpoint_url(protocol_type)

        if protocol_type == "JSONRPC":
            # JSON-RPC 2.0 format
            payload = self._build_message_payload(query, history, context)
            request_body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "SendMessage",
                "params": payload
            }
        else:
            # HTTP+JSON (REST) format - direct message payload
            request_body = self._build_message_payload(query, history, context)

        headers = self._build_headers()

        logger.info(f"[A2A-SDK] === Calling external A2A agent (sync) === name={self.agent_info.name}, protocol={protocol_type}, url={endpoint_url}")
        logger.info(f"[A2A-SDK] Headers: {headers}")
        logger.info(f"[A2A-SDK] Request body: {request_body}")

        try:
            parsed_url = urlparse(endpoint_url)
            logger.info(f"[A2A-SDK] Connecting to host={parsed_url.hostname}, port={parsed_url.port or 80}")
            logger.info(f"[A2A-SDK] Client HTTP/2: {self._client._transport._pool._http2}")
            logger.info(f"[A2A-SDK] Client timeout: {self._client.timeout}")

            response = await self._client.post(
                endpoint_url,
                json=request_body,
                headers=headers,
            )
            logger.info(f"[A2A-SDK] Response status: {response.status_code}")
            logger.info(f"[A2A-SDK] Response headers: {dict(response.headers)}")
            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException as e:
            logger.error(f"A2A request timeout for {self.agent_info.name}: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"A2A HTTP error for {self.agent_info.name}: status={e.response.status_code}, response_body={e.response.text[:500]}")
            raise
        except Exception as e:
            logger.error(f"A2A request failed for {self.agent_info.name}: {e}")
            raise

    def sync_call(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Synchronous wrapper for calling external A2A agent.

        This method runs the async call in a new event loop.

        Args:
            query: The user query.
            history: Optional conversation history.
            context: Optional context metadata.

        Returns:
            Extracted text response from the external agent.
        """
        import asyncio

        async def execute():
            async with self as proxy:
                response = await proxy.call(query, history, context)
                return proxy.extract_text_from_response(response)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(execute())
        finally:
            loop.close()

    async def call_streaming(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Call external A2A agent with streaming response.

        Args:
            query: The user query.
            history: Optional conversation history.
            context: Optional context metadata.

        Yields:
            A2A task events (taskProgress, taskStatusUpdate, taskArtifact, etc.).
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        protocol_type = self.agent_info.get_protocol_type()
        endpoint_url = self._get_endpoint_url(protocol_type, streaming=True)

        if protocol_type == "JSONRPC":
            # JSON-RPC 2.0 format
            payload = self._build_message_payload(query, history, context)
            request_body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "SendMessage",
                "params": payload
            }
        else:
            # HTTP+JSON (REST) format - direct message payload
            request_body = self._build_message_payload(query, history, context)

        headers = self._build_headers()

        logger.info(f"[A2A-SDK] === Calling external A2A agent (streaming) === name={self.agent_info.name}, protocol={protocol_type}, url={endpoint_url}, request_body={request_body}")

        try:
            async with self._client.stream(
                "POST",
                endpoint_url,
                json=request_body,
                headers=headers,
                timeout=self.agent_info.timeout
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str:
                            try:
                                event = json.loads(data_str)
                                yield event

                                # Check for terminal state
                                if event.get("kind") == "taskStatusUpdate":
                                    status = event.get("status", {})
                                    state = status.get("state", "")
                                    if state in ("completed", "failed", "canceled"):
                                        break

                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse SSE data: {data_str}")

        except httpx.TimeoutException as e:
            logger.error(f"A2A streaming timeout for {self.agent_info.name}: {e}")
            yield {
                "kind": "taskStatusUpdate",
                "status": {"state": "failed", "message": f"Timeout: {str(e)}"}
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"A2A streaming HTTP error for {self.agent_info.name}: {e.response.status_code}")
            yield {
                "kind": "taskStatusUpdate",
                "status": {"state": "failed", "message": f"HTTP {e.response.status_code}"}
            }

    def extract_text_from_response(self, response: Dict[str, Any]) -> str:
        """Extract text content from A2A response.

        Args:
            response: A2A response dict.

        Returns:
            Extracted text string.
        """
        # Check for error
        if "error" in response:
            error = response["error"]
            message = error.get("message", "Unknown error")
            raise RuntimeError(f"A2A agent error: {message}")

        # Extract from result
        result = response.get("result", response)

        # Try to extract from messages array (A2A spec format)
        if "messages" in result:
            messages = result["messages"]
            for msg in messages:
                if msg.get("role") == "agent":
                    parts = msg.get("parts", [])
                    for part in parts:
                        if "text" in part:
                            return part["text"]

        # Fallback: try status.message format
        if "status" in result:
            status = result["status"]
            if "message" in status:
                message = status["message"]
                if isinstance(message, dict):
                    parts = message.get("parts", [])
                    for part in parts:
                        if "text" in part:
                            return part["text"]
                return str(message)

        # Fallback: return whole result as string
        return json.dumps(result, ensure_ascii=False)

    def extract_text_from_events(self, events) -> str:
        """Extract accumulated text from streaming events.

        Args:
            events: Async iterator of A2A task events.

        Yields:
            Text chunks as they arrive.
        """
        accumulated = []

        async def process():
            async for event in events:
                kind = event.get("kind", "")

                if kind == "taskProgress":
                    # Extract from parts if present
                    content = event.get("content", "")
                    if isinstance(content, dict):
                        parts = content.get("parts", [])
                        for part in parts:
                            if "text" in part:
                                text = part["text"]
                                if text:
                                    accumulated.append(text)
                                    yield text
                    elif content:
                        accumulated.append(content)
                        yield content

                elif kind == "taskStatusUpdate":
                    status = event.get("status", {})
                    state = status.get("state", "")

                    if state == "completed":
                        # Try to get final message
                        if "message" in status:
                            message = status["message"]
                            if isinstance(message, dict):
                                parts = message.get("parts", [])
                                for part in parts:
                                    if "text" in part:
                                        text = part["text"]
                                        if text and text not in accumulated:
                                            yield text
                            else:
                                text = str(message)
                                if text and text not in accumulated:
                                    yield text
                        break

                    elif state in ("failed", "canceled"):
                        message = status.get("message", "")
                        if message:
                            error_text = f"[Error: {message}]"
                            if error_text not in accumulated:
                                yield error_text
                        break

        return process()


class A2AAgentProxyTool:
    """Tool wrapper for external A2A agent invocation.

    This class wraps ExternalA2AAgentProxy to be used as a tool
    in the Nexent agent framework.
    """

    name = "call_external_a2a_agent"
    description = """Call an external A2A agent as a sub-agent.
Input should be a JSON object with the following fields:
- agent_id: The external agent ID (string)
- query: The task description or question (string)
- history: Optional conversation history (array of {role, content} objects)
- stream: Whether to use streaming mode (boolean, default: false)

Returns the external agent's response."""

    def __init__(
        self,
        agent_configs: List[A2AAgentInfo],
        stop_event: Optional[Event] = None,
        observer: Optional[Any] = None
    ):
        """Initialize the A2A agent proxy tool.

        Args:
            agent_configs: List of external A2A agent configurations.
            stop_event: Optional stop event for cancellation.
            observer: Optional message observer for logging.
        """
        self.agent_configs = {agent.agent_id: agent for agent in agent_configs}
        self.stop_event = stop_event or Event()
        self.observer = observer

    def forward(self, input_str: str) -> str:
        """Execute the tool with the given input.

        Args:
            input_str: JSON string with agent_id and query.

        Returns:
            External agent's response as string.
        """
        import asyncio

        try:
            # Parse input
            if isinstance(input_str, str):
                input_data = json.loads(input_str)
            else:
                input_data = input_str

            agent_id = input_data.get("agent_id")
            query = input_data.get("query")
            history = input_data.get("history", [])
            use_stream = input_data.get("stream", False)

            if not agent_id:
                return json.dumps({"error": "agent_id is required"})
            if not query:
                return json.dumps({"error": "query is required"})

            # Get agent config
            agent_info = self.agent_configs.get(agent_id)
            if not agent_info:
                return json.dumps({"error": f"Agent {agent_id} not found"})

            # Execute call
            async def execute():
                async with ExternalA2AAgentProxy(agent_info, self.stop_event) as proxy:
                    if use_stream:
                        events = proxy.call_streaming(query, history)
                        result_parts = []
                        async for text in proxy.extract_text_from_events(events):
                            result_parts.append(text)
                            # Log progress if observer available
                            if self.observer:
                                self.observer.append_message(text)
                        return "".join(result_parts) if result_parts else "No response received"
                    else:
                        response = await proxy.call(query, history)
                        return proxy.extract_text_from_response(response)

            # Run async code
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(execute())
            finally:
                loop.close()

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse input JSON: {e}")
            return json.dumps({"error": f"Invalid JSON: {str(e)}"})
        except Exception as e:
            logger.error(f"A2A agent call failed: {e}", exc_info=True)
            return json.dumps({"error": f"Call failed: {str(e)}"})

    def add_agent(self, agent_info: A2AAgentInfo) -> None:
        """Add or update an external agent configuration.

        Args:
            agent_info: External A2A agent configuration.
        """
        self.agent_configs[agent_info.agent_id] = agent_info

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an external agent configuration.

        Args:
            agent_id: Agent ID to remove.

        Returns:
            True if removed, False if not found.
        """
        if agent_id in self.agent_configs:
            del self.agent_configs[agent_id]
            return True
        return False

    def list_agents(self) -> List[Dict[str, str]]:
        """List all configured external agents.

        Returns:
            List of agent info dicts.
        """
        return [
            {
                "agent_id": info.agent_id,
                "name": info.name,
                "url": info.url,
                "transport_type": info.transport_type
            }
            for info in self.agent_configs.values()
        ]


class ExternalA2AAgentWrapper:
    """Wrapper for external A2A agents to be used as managed agents.

    This wrapper makes external A2A agents callable like local agents,
    allowing the model to use syntax like: agent_name(task="...")

    The wrapper implements the same interface as CoreAgent so that
    the parent agent can treat it as a sub-agent.
    """

    def __init__(
        self,
        agent_info: A2AAgentInfo,
        stop_event: Optional[Event] = None,
        observer: Optional[Any] = None
    ):
        """Initialize the external A2A agent wrapper.

        Args:
            agent_info: Configuration for the external A2A agent.
            stop_event: Optional stop event for cancellation.
            observer: Optional message observer for logging.
        """
        self.name = agent_info.name
        # Use skills description if available
        self.description = agent_info.get_skills_description()
        self.agent_info = agent_info
        self.stop_event = stop_event or Event()
        self.observer = observer
        self._proxy: Optional[ExternalA2AAgentProxy] = None
        # Required by smolagents for managed agents
        self.inputs = {
            "task": {"type": "string", "description": "Task description for the external agent."},
            "additional_args": {
                "type": "object",
                "description": "Additional arguments (history, etc.)",
                "nullable": True,
            },
        }
        self.output_type = "string"

    def __call__(self, task: str = None, **kwargs) -> str:
        """Call external A2A agent synchronously.

        This method is called by the parent agent's Python execution
        when the model outputs: agent_name(task="...")

        Args:
            task: The task description string.
            **kwargs: Additional arguments (history, etc.)

        Returns:
            The external agent's response as string.
        """
        if not self._proxy:
            self._proxy = ExternalA2AAgentProxy(
                self.agent_info,
                stop_event=self.stop_event
            )

        history = kwargs.get("history", [])
        query = task or kwargs.get("query", "")

        if not query:
            return "Error: No task provided"

        try:
            result = self._proxy.sync_call(query, history)
            return result
        except Exception as e:
            logger.error(f"External A2A agent '{self.name}' call failed: {e}")
            return f"Error: {str(e)}"

    def run(self, task: str = None, **kwargs) -> str:
        """Run external agent and return result (alias for __call__).

        Args:
            task: The task description string.
            **kwargs: Additional arguments.

        Returns:
            The external agent's response as string.
        """
        return self(task, **kwargs)
