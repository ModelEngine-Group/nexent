"""
SDK-owned Agent observability entrypoint.

Business code should bind AgentRunMetadata once at the request boundary. The
SDK lifecycle then creates Agent, Chain, LLM, Tool, and future Retriever spans.
"""

from .monitoring import (
    AgentMonitoringContext,
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
    get_monitoring_manager,
    set_agent_monitoring_context,
)

__all__ = [
    "AgentMonitoringContext",
    "AgentRunMetadata",
    "agent_monitoring_context",
    "get_agent_monitoring_context",
    "get_monitoring_manager",
    "set_agent_monitoring_context",
]
