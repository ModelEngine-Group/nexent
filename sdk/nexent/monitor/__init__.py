"""
Nexent Monitor Package - LLM Performance Monitoring System

A comprehensive monitoring solution using OpenTelemetry OTLP protocol.
Provides distributed tracing, token-level performance monitoring, and seamless
integration with AI observability platforms like Arize Phoenix and Langfuse.
"""

from .monitoring import (
    MonitoringConfig,
    MonitoringManager,
    LLMTokenTracker,
    MonitoringRecordBuffer,
    RecordModelCallContext,
    get_monitoring_manager,
    get_monitoring_buffer,
    is_opentelemetry_available,
    set_monitoring_context,
    get_monitoring_context,
    set_monitoring_operation,
    record_model_call,
)

__version__ = "0.2.0"
__all__ = [
    'MonitoringConfig',
    'MonitoringManager',
    'LLMTokenTracker',
    'MonitoringRecordBuffer',
    'RecordModelCallContext',
    'get_monitoring_manager',
    'get_monitoring_buffer',
    'is_opentelemetry_available',
    'set_monitoring_context',
    'get_monitoring_context',
    'set_monitoring_operation',
    'record_model_call',
]
