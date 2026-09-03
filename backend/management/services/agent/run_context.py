"""Common memory and monitoring preparation for streaming and background runs."""

from dataclasses import dataclass
from typing import Any

from nexent.monitor import AgentRunMetadata

from services.memory_config_service import build_memory_context
from utils.monitoring import monitoring_manager


@dataclass(frozen=True)
class AgentRunContext:
    metadata: Any
    enable_memory: bool


def build_agent_run_context(request, user_id: str, tenant_id: str, language: str, *, extra_metadata: dict):
    """Preview memory once and bind the metadata shared by both consumers."""
    memory = build_memory_context(user_id, tenant_id, request.agent_id, skip_query=request.is_debug)
    enabled = memory.user_config.memory_switch
    metadata = monitoring_manager.bind_agent_context(AgentRunMetadata(
        agent_id=request.agent_id,
        conversation_id=request.conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        query=request.query,
        is_debug=request.is_debug,
        language=language,
        memory_enabled=enabled,
        history_count=len(request.history) if request.history else 0,
        minio_files_count=len(request.minio_files) if request.minio_files else 0,
        extra_metadata={
            "agent_share_option": getattr(memory.user_config, "agent_share_option", "unknown"),
            **extra_metadata,
        },
    ))
    return AgentRunContext(metadata, enabled and not request.is_debug)
