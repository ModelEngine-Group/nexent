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
        MONITORING_PROVIDER,
        MONITORING_PROJECT_NAME,
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
        OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
        OTEL_EXPORTER_OTLP_PROTOCOL,
        OTEL_EXPORTER_OTLP_METRICS_ENABLED,
        MONITORING_INSTRUMENT_REQUESTS,
        MONITORING_FASTAPI_INCLUDED_URLS,
        MONITORING_FASTAPI_EXCLUDED_URLS,
        MONITORING_FASTAPI_EXCLUDE_SPANS,
        MONITORING_TRACE_CONTENT_MODE,
        MONITORING_TRACE_MAX_CHARS,
        MONITORING_TRACE_MAX_ITEMS,
        OTLP_HEADERS,
        TELEMETRY_SAMPLE_RATE
    )
except ImportError:
    from backend.consts.const import (
        ENABLE_TELEMETRY,
        MONITORING_PROVIDER,
        MONITORING_PROJECT_NAME,
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
        OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
        OTEL_EXPORTER_OTLP_PROTOCOL,
        OTEL_EXPORTER_OTLP_METRICS_ENABLED,
        MONITORING_INSTRUMENT_REQUESTS,
        MONITORING_FASTAPI_INCLUDED_URLS,
        MONITORING_FASTAPI_EXCLUDED_URLS,
        MONITORING_FASTAPI_EXCLUDE_SPANS,
        MONITORING_TRACE_CONTENT_MODE,
        MONITORING_TRACE_MAX_CHARS,
        MONITORING_TRACE_MAX_ITEMS,
        OTLP_HEADERS,
        TELEMETRY_SAMPLE_RATE
    )

import logging

logger = logging.getLogger(__name__)

monitoring_manager = get_monitoring_manager()


def _initialize_monitoring():
    """Initialize monitoring configuration with OTLP settings."""
    config = MonitoringConfig(
        enable_telemetry=ENABLE_TELEMETRY,
        service_name=OTEL_SERVICE_NAME,
        provider=MONITORING_PROVIDER or "otlp",
        otlp_endpoint=OTEL_EXPORTER_OTLP_ENDPOINT,
        otlp_traces_endpoint=OTEL_EXPORTER_OTLP_TRACES_ENDPOINT or None,
        otlp_metrics_endpoint=OTEL_EXPORTER_OTLP_METRICS_ENDPOINT or None,
        otlp_protocol=OTEL_EXPORTER_OTLP_PROTOCOL,
        otlp_headers=OTLP_HEADERS,
        export_metrics=OTEL_EXPORTER_OTLP_METRICS_ENABLED,
        instrument_requests=MONITORING_INSTRUMENT_REQUESTS,
        fastapi_included_urls=MONITORING_FASTAPI_INCLUDED_URLS,
        fastapi_excluded_urls=MONITORING_FASTAPI_EXCLUDED_URLS,
        fastapi_exclude_spans=MONITORING_FASTAPI_EXCLUDE_SPANS,
        project_name=MONITORING_PROJECT_NAME or None,
        telemetry_sample_rate=TELEMETRY_SAMPLE_RATE,
        trace_content_mode=MONITORING_TRACE_CONTENT_MODE,
        trace_max_chars=MONITORING_TRACE_MAX_CHARS,
        trace_max_items=MONITORING_TRACE_MAX_ITEMS
    )

    monitoring_manager.configure(config)
    logger.info(
        f"OTLP monitoring initialized: service_name={OTEL_SERVICE_NAME}, "
        f"enable_telemetry={config.enable_telemetry}, provider={config.provider}, "
        f"endpoint={config.otlp_endpoint}, trace_endpoint={config.get_trace_endpoint()}, "
        f"protocol={OTEL_EXPORTER_OTLP_PROTOCOL}"
    )


_initialize_monitoring()

__all__ = ['monitoring_manager']
