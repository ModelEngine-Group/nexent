"""
Global Monitoring Manager for Backend

This module initializes and configures the global monitoring manager instance
with backend environment variables using OTLP protocol. All other backend modules
should import `monitoring_manager` directly from this module.

Usage:
    from utils.monitoring import monitoring_manager
    
    @monitoring_manager.monitor_endpoint("my_service.my_function")
    async def my_function():
        return {"status": "ok"}
"""

from nexent.monitor import (
    MonitoringConfig,
    get_monitoring_manager
)
try:
    from consts.const import (
        ENABLE_TELEMETRY,
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_EXPORTER_OTLP_PROTOCOL,
        OTLP_HEADERS,
        TELEMETRY_SAMPLE_RATE,
        LLM_SLOW_REQUEST_THRESHOLD_SECONDS,
        LLM_SLOW_TOKEN_RATE_THRESHOLD
    )
except ImportError:
    from backend.consts.const import (
        ENABLE_TELEMETRY,
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_EXPORTER_OTLP_PROTOCOL,
        OTLP_HEADERS,
        TELEMETRY_SAMPLE_RATE,
        LLM_SLOW_REQUEST_THRESHOLD_SECONDS,
        LLM_SLOW_TOKEN_RATE_THRESHOLD
    )

import logging

logger = logging.getLogger(__name__)

monitoring_manager = get_monitoring_manager()


def _initialize_monitoring():
    """Initialize monitoring configuration with OTLP settings."""
    config = MonitoringConfig(
        enable_telemetry=ENABLE_TELEMETRY,
        service_name=OTEL_SERVICE_NAME,
        otlp_endpoint=OTEL_EXPORTER_OTLP_ENDPOINT,
        otlp_protocol=OTEL_EXPORTER_OTLP_PROTOCOL,
        otlp_headers=OTLP_HEADERS,
        telemetry_sample_rate=TELEMETRY_SAMPLE_RATE,
        llm_slow_request_threshold_seconds=LLM_SLOW_REQUEST_THRESHOLD_SECONDS,
        llm_slow_token_rate_threshold=LLM_SLOW_TOKEN_RATE_THRESHOLD
    )

    monitoring_manager.configure(config)
    logger.info(
        f"OTLP monitoring initialized: service_name={OTEL_SERVICE_NAME}, "
        f"enable_telemetry={ENABLE_TELEMETRY}, endpoint={OTEL_EXPORTER_OTLP_ENDPOINT}, "
        f"protocol={OTEL_EXPORTER_OTLP_PROTOCOL}"
    )


_initialize_monitoring()

__all__ = ['monitoring_manager']