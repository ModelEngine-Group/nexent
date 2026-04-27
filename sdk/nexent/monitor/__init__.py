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
    get_monitoring_manager,
    is_opentelemetry_available,
)

__version__ = "0.2.0"
__all__ = [
    'MonitoringConfig',
    'MonitoringManager',
    'LLMTokenTracker',
    'get_monitoring_manager',
    'is_opentelemetry_available',
]