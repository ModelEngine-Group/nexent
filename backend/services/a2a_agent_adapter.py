"""
A2A Agent Adapter.

This adapter layer converts between A2A protocol format and internal Nexent agent format.
"""
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
from dataclasses import dataclass, field
from uuid import uuid4

logger = logging.getLogger(__name__)

# Shared A2A protocol constants
_MEDIA_TYPE_TEXT = "text/plain"


@dataclass
class A2AExecutionContext:
    """Context for A2A task execution."""
    task_id: str
    endpoint_id: str
    token_id: Optional[int] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_debug: bool = False


class A2AAgentAdapter:
    """Adapter layer between A2A protocol and existing agent execution.

    Responsibilities:
    - Convert A2A protocol format → internal agent payload
    - Convert internal result → A2A Task format
    - Handle streaming response conversion
    """

    def __init__(self):
        # This adapter is stateless; no instance attributes need initialization.
        # All methods operate purely on input data without side effects.
        pass

    def build_agent_request(
        self,
        a2a_message: Dict[str, Any],
        context: A2AExecutionContext,
        agent_id: int
    ) -> Dict[str, Any]:
        """Build internal agent request from A2A message.

        Args:
            a2a_message: A2A message payload containing message, history, etc.
            context: A2A execution context.
            agent_id: Target agent ID.

        Returns:
            Internal AgentRequest dict.
        """
        # Extract message content from A2A 1.0 parts format
        message = a2a_message.get("message", {})
        parts = message.get("parts", [])

        if parts and isinstance(parts, list):
            first_part = parts[0]
            if isinstance(first_part, dict):
                user_input = first_part.get("text", str(first_part))
            else:
                user_input = str(first_part)
        else:
            user_input = ""

        # Build history
        history = self._build_history(a2a_message)

        # Build internal request
        return {
            "agent_id": agent_id,
            "query": user_input,
            "history": history,
            "task_id": context.task_id,
            "correlation_id": context.correlation_id,
            "metadata": context.metadata,
            "is_debug": context.is_debug,
        }

    def _build_history(self, a2a_message: Dict[str, Any]) -> List[Dict[str, str]]:
        """Build history list from A2A message.

        Args:
            a2a_message: A2A message with optional history.

        Returns:
            List of history items in internal format.
        """
        history = []
        message_history = a2a_message.get("history", [])

        for msg in message_history:
            role = msg.get("role", "ROLE_USER")
            parts = msg.get("parts", [])

            # Extract text from A2A 1.0 parts format
            if parts and isinstance(parts, list):
                first_part = parts[0]
                if isinstance(first_part, dict):
                    text = first_part.get("text", str(first_part))
                else:
                    text = str(first_part)
            else:
                text = ""

            # Map A2A role to internal role: ROLE_USER → user, ROLE_AGENT → assistant
            if role == "ROLE_USER":
                internal_role = "user"
            elif role == "ROLE_AGENT":
                internal_role = "assistant"
            else:
                internal_role = "user"  # Default fallback

            history.append({
                "role": internal_role,
                "content": text
            })

        return history

    def parse_a2a_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Parse incoming A2A JSON-RPC message.

        Args:
            payload: Raw A2A request payload.

        Returns:
            Parsed message params dict with taskId extracted.
        """
        # Handle JSON-RPC format
        if "jsonrpc" in payload:
            params = payload.get("params", {})
            # JSON-RPC 2.0: taskId can be in params.message or params directly
            # For SendMessage/SendStreamingMessage, taskId is typically in params.message.taskId
            return params

        # Handle direct message format - taskId may be at top level or in message
        return payload

    def build_a2a_task_response(
        self,
        task_id: str,
        status: str,
        message: Optional[Dict[str, Any]] = None,
        parts: Optional[List[Dict[str, Any]]] = None,
        artifacts: Optional[List[Dict[str, Any]]] = None,
        context_id: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build A2A Task response following A2A 1.0 specification.

        SendMessage returns: {"task": {...}}

        Args:
            task_id: Task ID.
            status: Task status (submitted, working, completed, failed, canceled, input_required).
            message: Optional legacy message format (converted to parts if provided).
            parts: Message parts following A2A Part structure.
            artifacts: Result artifacts (list of artifact objects).
            context_id: Optional context ID for grouping related tasks.
            timestamp: Optional ISO timestamp for status (defaults to current time).

        Returns:
            A2A Task response dict wrapped in {"task": {...}}.
        """
        from datetime import datetime
        
        # Map internal status to A2A TASK_STATE format (handle both short and full format)
        state_map = {
            # Short format (legacy/internal)
            "submitted": "TASK_STATE_SUBMITTED",
            "working": "TASK_STATE_WORKING",
            "completed": "TASK_STATE_COMPLETED",
            "failed": "TASK_STATE_FAILED",
            "canceled": "TASK_STATE_CANCELED",
            "input_required": "TASK_STATE_INPUT_REQUIRED",
            "rejected": "TASK_STATE_REJECTED",
            "auth_required": "TASK_STATE_AUTH_REQUIRED",
            # Full format (A2A standard)
            "TASK_STATE_SUBMITTED": "TASK_STATE_SUBMITTED",
            "TASK_STATE_WORKING": "TASK_STATE_WORKING",
            "TASK_STATE_COMPLETED": "TASK_STATE_COMPLETED",
            "TASK_STATE_FAILED": "TASK_STATE_FAILED",
            "TASK_STATE_CANCELED": "TASK_STATE_CANCELED",
            "TASK_STATE_INPUT_REQUIRED": "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_REJECTED": "TASK_STATE_REJECTED",
            "TASK_STATE_AUTH_REQUIRED": "TASK_STATE_AUTH_REQUIRED",
        }
        state = state_map.get(status, f"TASK_STATE_{status.upper()}")

        # Generate timestamp if not provided
        if not timestamp:
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        task = {
            "id": task_id,
            "status": {
                "state": state,
                "timestamp": timestamp
            }
        }

        if context_id:
            task["contextId"] = context_id

        # Handle message content - always use parts format with mediaType
        if parts:
            # Use provided parts as the message
            task["status"]["message"] = {
                "role": "ROLE_AGENT",
                "parts": parts
            }
        elif message:
            # Convert legacy message format to parts
            content = message.get("content", {})
            if isinstance(content, dict) and content.get("type") == "text":
                text_content = content.get("text", "")
            else:
                text_content = str(message)
            task["status"]["message"] = {
                "role": message.get("role", "agent"),
                "parts": [{"type": "text", "text": text_content, "mediaType": _MEDIA_TYPE_TEXT}]
            }

        # Handle artifacts
        if artifacts:
            task["artifacts"] = artifacts

        return {"task": task}

    def build_a2a_message_response(
        self,
        message_id: Optional[str] = None,
        role: str = "ROLE_AGENT",
        parts: Optional[List[Dict[str, Any]]] = None,
        text: Optional[str] = None,
        context_id: Optional[str] = None,
        task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build A2A Message response following A2A 1.0 specification.

        For simple tasks that don't require task tracking.

        Args:
            message_id: Optional message ID (generated if not provided).
            role: Message role (ROLE_UNSPECIFIED, ROLE_USER, or ROLE_AGENT).
            parts: Message parts following A2A Part structure.
            text: Alternative to parts - create single text part.
            context_id: Optional context ID for grouping related tasks.
            task_id: Optional associated task ID.

        Returns:
            A2A Message response dict wrapped in {"message": {...}}.
        """
        if not message_id:
            message_id = f"msg_{uuid4().hex[:16]}"

        if parts:
            message_parts = parts
        elif text:
            message_parts = [{"type": "text", "text": text, "mediaType": _MEDIA_TYPE_TEXT}]
        else:
            message_parts = [{"type": "text", "text": "", "mediaType": _MEDIA_TYPE_TEXT}]

        message_obj = {
            "messageId": message_id,
            "role": role,
            "parts": message_parts
        }

        # Optional fields
        if context_id:
            message_obj["contextId"] = context_id
        if task_id:
            message_obj["taskId"] = task_id

        return {"message": message_obj}

    def build_a2a_task_event(
        self,
        task_id: str,
        event_type: str,
        data: Dict[str, Any],
        context_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build A2A Task event following A2A 1.0 streaming specification.

        SendStreamingMessage returns SSE events:
        - {"task": {"id": "xxx", "status": {"state": "TASK_STATE_WORKING"}}}
        - {"artifactUpdate": {"taskId": "xxx", "contextId": "xxx", "artifact": {...}, "append": true, "lastChunk": false}}
        - {"statusUpdate": {"taskId": "xxx", "contextId": "xxx", "status": {"state": "TASK_STATE_COMPLETED", "timestamp": "..."}}}

        Args:
            task_id: Task ID.
            event_type: Event type (taskProgress, taskStatusUpdate, taskArtifact).
            data: Event data.
            context_id: Optional context ID for grouping related tasks.

        Returns:
            A2A Task event dict for SSE.
        """
        # Common fields for all events
        common_fields = {"taskId": task_id}
        if context_id:
            common_fields["contextId"] = context_id

        if event_type == "taskProgress":
            # Use artifactUpdate format with append=true for streaming content
            content = data.get("content", "")
            is_last = data.get("lastChunk", False)
            parts = data.get("parts", [])

            if parts:
                artifact_parts = parts
            else:
                # Convert content to parts format
                if isinstance(content, dict):
                    if content.get("type") == "text":
                        text_content = content.get("text", "")
                    else:
                        text_content = str(content)
                else:
                    text_content = str(content)
                artifact_parts = [{"type": "text", "text": text_content}]

            event = {
                "artifactUpdate": {
                    **common_fields,
                    "artifact": {
                        "parts": artifact_parts,
                        "lastChunk": is_last
                    },
                    "append": True,
                    "lastChunk": is_last
                }
            }
            return event

        elif event_type == "taskStatusUpdate":
            # Use statusUpdate format
            status_data = data.get("status", {})
            state = status_data.get("state", "TASK_STATE_WORKING")
            message = status_data.get("message")
            timestamp = status_data.get("timestamp")

            # Map state if not already in TASK_STATE format
            state_map = {
                "working": "TASK_STATE_WORKING",
                "completed": "TASK_STATE_COMPLETED",
                "failed": "TASK_STATE_FAILED",
                "canceled": "TASK_STATE_CANCELED",
                "input_required": "TASK_STATE_INPUT_REQUIRED",
                "rejected": "TASK_STATE_REJECTED",
                "auth_required": "TASK_STATE_AUTH_REQUIRED",
            }
            if state.startswith("TASK_STATE_"):
                status_obj = {"state": state}
            else:
                status_obj = {"state": state_map.get(state, f"TASK_STATE_{state.upper()}")}
            if timestamp:
                status_obj["timestamp"] = timestamp

            # Add message if present
            if message:
                if isinstance(message, dict) and "parts" in message:
                    status_obj["message"] = message
                else:
                    # Convert to parts format
                    role = message.get("role", "agent") if isinstance(message, dict) else "agent"
                    content = message.get("content", {}) if isinstance(message, dict) else message
                    if isinstance(content, dict) and content.get("type") == "text":
                        text_content = content.get("text", "")
                    else:
                        text_content = str(message)
                    status_obj["message"] = {
                        "role": role,
                        "parts": [{"type": "text", "text": text_content}]
                    }

            event = {
                "statusUpdate": {
                    **common_fields,
                    "status": status_obj
                }
            }
            return event

        elif event_type == "taskArtifact":
            return {
                "artifactUpdate": {
                    **common_fields,
                    "artifact": data.get("artifact", {}),
                    "append": data.get("append", False),
                    "lastChunk": data.get("lastChunk", True)
                }
            }

        # Fallback for unknown event types
        return {
            "task": {
                "id": task_id,
                "status": {"state": "TASK_STATE_WORKING"}
            }
        }

    def extract_stream_chunk(self, chunk: Dict[str, Any]) -> Optional[str]:
        """Extract text content from internal stream chunk.

        Args:
            chunk: Internal stream chunk.

        Returns:
            Extracted text or None.
        """
        # Handle different chunk formats
        chunk_type = chunk.get("type", "")

        if chunk_type == "text" or chunk_type == "message":
            return chunk.get("content", "")

        if chunk_type == "answer":
            return chunk.get("answer", "")

        # Direct content field
        if "content" in chunk:
            return str(chunk.get("content", ""))

        return None

    def is_terminal_chunk(self, chunk: Dict[str, Any]) -> bool:
        """Check if chunk indicates end of stream.

        Args:
            chunk: Stream chunk.

        Returns:
            True if this is a terminal chunk.
        """
        chunk_type = chunk.get("type", "")

        # Terminal markers
        if chunk_type in ("done", "end", "stop"):
            return True

        # Status-based terminals
        status = chunk.get("status", "")
        if status in ("completed", "failed", "canceled"):
            return True

        # Final answer marker
        if chunk_type == "final":
            return True

        return False

    def parse_task_status(self, state: Dict[str, Any]) -> str:
        """Parse task status from internal state.

        Args:
            state: Internal task state.

        Returns:
            A2A task state string.
        """
        if isinstance(state, dict):
            # Check for explicit state field
            if "state" in state:
                return state["state"]

            # Check for status field
            if "status" in state:
                status = state["status"]
                if isinstance(status, str):
                    return status
                if isinstance(status, dict):
                    return status.get("state", "working")

        # Default to working if unknown
        if isinstance(state, str):
            return state

        return "working"


# Singleton instance
a2a_agent_adapter = A2AAgentAdapter()
