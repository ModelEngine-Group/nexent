"""
Nexent Monitor Package - LLM Performance Monitoring System

A comprehensive monitoring solution using OpenTelemetry OTLP protocol.
Provides distributed tracing, token-level performance monitoring, and seamless
integration with AI observability platforms like Arize Phoenix, Langfuse,
and LangSmith.
"""

from .monitoring import (
    MonitoringConfig,
    MonitoringManager,
    AgentMonitoringContext,
    AgentRunMetadata,
    LLMTokenTracker,
    MonitoringRecordBuffer,
    RecordModelCallContext,
    get_monitoring_manager,
    get_monitoring_buffer,
    is_opentelemetry_available,
    set_monitoring_context,
    get_monitoring_context,
    set_agent_monitoring_context,
    get_agent_monitoring_context,
    agent_monitoring_context,
    set_monitoring_operation,
    record_model_call,
    OPENINFERENCE_SPAN_KIND,
    OPENINFERENCE_SPAN_KIND_AGENT,
    OPENINFERENCE_SPAN_KIND_CHAIN,
    OPENINFERENCE_SPAN_KIND_LLM,
    OPENINFERENCE_SPAN_KIND_TOOL,
    OPENINFERENCE_SPAN_KIND_RETRIEVER,
    OPENINFERENCE_INPUT_VALUE,
    OPENINFERENCE_OUTPUT_VALUE,
    OPENINFERENCE_METADATA,
    OPENINFERENCE_SESSION_ID,
    OPENINFERENCE_USER_ID,
    OPENINFERENCE_TAG_TAGS,
)

__version__ = "0.2.0"
__all__ = [
    'MonitoringConfig',
    'MonitoringManager',
    'AgentMonitoringContext',
    'AgentRunMetadata',
    'LLMTokenTracker',
    'MonitoringRecordBuffer',
    'RecordModelCallContext',
    'get_monitoring_manager',
    'get_monitoring_buffer',
    'is_opentelemetry_available',
    'set_monitoring_context',
    'get_monitoring_context',
    'set_agent_monitoring_context',
    'get_agent_monitoring_context',
    'agent_monitoring_context',
    'set_monitoring_operation',
    'record_model_call',
    'OPENINFERENCE_SPAN_KIND',
    'OPENINFERENCE_SPAN_KIND_AGENT',
    'OPENINFERENCE_SPAN_KIND_CHAIN',
    'OPENINFERENCE_SPAN_KIND_LLM',
    'OPENINFERENCE_SPAN_KIND_TOOL',
    'OPENINFERENCE_SPAN_KIND_RETRIEVER',
    'OPENINFERENCE_INPUT_VALUE',
    'OPENINFERENCE_OUTPUT_VALUE',
    'OPENINFERENCE_METADATA',
    'OPENINFERENCE_SESSION_ID',
    'OPENINFERENCE_USER_ID',
    'OPENINFERENCE_TAG_TAGS',
]
