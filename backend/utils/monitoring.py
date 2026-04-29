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
        ENABLE_TELEMETRY_RAW,
        MONITORING_CONFIG_FILE,
        MONITORING_PROVIDER,
        MONITORING_USE_PLATFORM_SDK_RAW,
        MONITORING_USE_PLATFORM_SDK,
        MONITORING_PROJECT_NAME,
        OTEL_SERVICE_NAME_RAW,
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT_RAW,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
        OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
        OTEL_EXPORTER_OTLP_PROTOCOL_RAW,
        OTEL_EXPORTER_OTLP_PROTOCOL,
        OTEL_EXPORTER_OTLP_HEADERS_RAW,
        OTEL_EXPORTER_OTLP_AUTHORIZATION,
        OTEL_EXPORTER_OTLP_X_API_KEY,
        OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION,
        OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW,
        OTEL_EXPORTER_OTLP_METRICS_ENABLED,
        OTLP_HEADERS,
        TELEMETRY_SAMPLE_RATE_RAW,
        TELEMETRY_SAMPLE_RATE,
        LLM_SLOW_REQUEST_THRESHOLD_SECONDS_RAW,
        LLM_SLOW_REQUEST_THRESHOLD_SECONDS,
        LLM_SLOW_TOKEN_RATE_THRESHOLD_RAW,
        LLM_SLOW_TOKEN_RATE_THRESHOLD
    )
except ImportError:
    from backend.consts.const import (
        ENABLE_TELEMETRY,
        ENABLE_TELEMETRY_RAW,
        MONITORING_CONFIG_FILE,
        MONITORING_PROVIDER,
        MONITORING_USE_PLATFORM_SDK_RAW,
        MONITORING_USE_PLATFORM_SDK,
        MONITORING_PROJECT_NAME,
        OTEL_SERVICE_NAME_RAW,
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT_RAW,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
        OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
        OTEL_EXPORTER_OTLP_PROTOCOL_RAW,
        OTEL_EXPORTER_OTLP_PROTOCOL,
        OTEL_EXPORTER_OTLP_HEADERS_RAW,
        OTEL_EXPORTER_OTLP_AUTHORIZATION,
        OTEL_EXPORTER_OTLP_X_API_KEY,
        OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION,
        OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW,
        OTEL_EXPORTER_OTLP_METRICS_ENABLED,
        OTLP_HEADERS,
        TELEMETRY_SAMPLE_RATE_RAW,
        TELEMETRY_SAMPLE_RATE,
        LLM_SLOW_REQUEST_THRESHOLD_SECONDS_RAW,
        LLM_SLOW_REQUEST_THRESHOLD_SECONDS,
        LLM_SLOW_TOKEN_RATE_THRESHOLD_RAW,
        LLM_SLOW_TOKEN_RATE_THRESHOLD
    )

import logging

logger = logging.getLogger(__name__)

monitoring_manager = get_monitoring_manager()


def _is_explicit_non_default(raw_value: str | None, default_value: str) -> bool:
    """Return True when an env value should override a config-file value."""
    return raw_value not in (None, "", default_value)


def _build_env_overrides() -> dict:
    """Build config overrides from environment-derived constants."""
    overrides = {}
    if ENABLE_TELEMETRY_RAW is not None:
        overrides["enable_telemetry"] = ENABLE_TELEMETRY
    if MONITORING_PROVIDER:
        overrides["provider"] = MONITORING_PROVIDER
    if _is_explicit_non_default(OTEL_SERVICE_NAME_RAW, "nexent-backend"):
        overrides["service_name"] = OTEL_SERVICE_NAME
    if _is_explicit_non_default(OTEL_EXPORTER_OTLP_ENDPOINT_RAW, "http://localhost:4318"):
        overrides["otlp_endpoint"] = OTEL_EXPORTER_OTLP_ENDPOINT
    if OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:
        overrides["otlp_traces_endpoint"] = OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
    if OTEL_EXPORTER_OTLP_METRICS_ENDPOINT:
        overrides["otlp_metrics_endpoint"] = OTEL_EXPORTER_OTLP_METRICS_ENDPOINT
    if _is_explicit_non_default(OTEL_EXPORTER_OTLP_PROTOCOL_RAW, "http"):
        overrides["otlp_protocol"] = OTEL_EXPORTER_OTLP_PROTOCOL
    if (
        OTEL_EXPORTER_OTLP_HEADERS_RAW
        or OTEL_EXPORTER_OTLP_AUTHORIZATION
        or OTEL_EXPORTER_OTLP_X_API_KEY
        or OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION
    ):
        overrides["otlp_headers"] = OTLP_HEADERS
    if OTEL_EXPORTER_OTLP_METRICS_ENABLED_RAW is not None:
        overrides["export_metrics"] = OTEL_EXPORTER_OTLP_METRICS_ENABLED
    if MONITORING_USE_PLATFORM_SDK_RAW is not None:
        overrides["use_platform_sdk"] = MONITORING_USE_PLATFORM_SDK
    if MONITORING_PROJECT_NAME:
        overrides["project_name"] = MONITORING_PROJECT_NAME
    if _is_explicit_non_default(TELEMETRY_SAMPLE_RATE_RAW, "1.0"):
        overrides["telemetry_sample_rate"] = TELEMETRY_SAMPLE_RATE
    if _is_explicit_non_default(LLM_SLOW_REQUEST_THRESHOLD_SECONDS_RAW, "5.0"):
        overrides["llm_slow_request_threshold_seconds"] = LLM_SLOW_REQUEST_THRESHOLD_SECONDS
    if _is_explicit_non_default(LLM_SLOW_TOKEN_RATE_THRESHOLD_RAW, "10.0"):
        overrides["llm_slow_token_rate_threshold"] = LLM_SLOW_TOKEN_RATE_THRESHOLD
    return overrides


def _initialize_monitoring():
    """Initialize monitoring configuration with OTLP settings."""
    if MONITORING_CONFIG_FILE:
        config = MonitoringConfig.from_file(
            MONITORING_CONFIG_FILE,
            overrides=_build_env_overrides()
        )
    else:
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
            use_platform_sdk=MONITORING_USE_PLATFORM_SDK,
            project_name=MONITORING_PROJECT_NAME or None,
            telemetry_sample_rate=TELEMETRY_SAMPLE_RATE,
            llm_slow_request_threshold_seconds=LLM_SLOW_REQUEST_THRESHOLD_SECONDS,
            llm_slow_token_rate_threshold=LLM_SLOW_TOKEN_RATE_THRESHOLD
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
