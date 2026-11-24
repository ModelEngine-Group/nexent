# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Global Monitoring Manager for Backend

This module initializes and configures the global monitoring manager instance
with backend environment variables using OTLP protocol. All other backend modules
should import `monitoring_manager` directly from this module.

Usage:
    from infrastructure.trace.bootstrap import monitoring_manager

    @monitoring_manager.monitor_endpoint("my_service.my_function")
    async def my_function():
        return {"status": "ok"}
"""

import logging
from dataclasses import replace
from importlib import import_module

from infrastructure.rdb.model_monitoring import write_model_monitoring_record
from nexent.monitor import MonitoringConfig, configure_monitoring_records, get_monitoring_manager

try:
    environment = import_module("contracts.constants.environment")
except ImportError:
    environment = import_module("backend.contracts.constants.environment")

logger = logging.getLogger(__name__)

monitoring_manager = get_monitoring_manager()


local_trajectory_processor = None


def _initialize_monitoring():
    """Configure the shared telemetry defaults before any service adds capture."""
    remote_enabled = environment.ENABLE_TELEMETRY and environment.MONITORING_PROVIDER != "local_file"
    config = MonitoringConfig(
        enable_telemetry=remote_enabled,
        service_name=environment.OTEL_SERVICE_NAME,
        provider=environment.MONITORING_PROVIDER or "otlp",
        otlp_endpoint=environment.OTEL_EXPORTER_OTLP_ENDPOINT,
        otlp_traces_endpoint=environment.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT or None,
        otlp_metrics_endpoint=environment.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT or None,
        otlp_protocol=environment.OTEL_EXPORTER_OTLP_PROTOCOL,
        otlp_headers=environment.OTLP_HEADERS,
        export_traces=remote_enabled,
        export_metrics=remote_enabled and environment.OTEL_EXPORTER_OTLP_METRICS_ENABLED,
        instrument_requests=environment.MONITORING_INSTRUMENT_REQUESTS,
        fastapi_included_urls=environment.MONITORING_FASTAPI_INCLUDED_URLS,
        fastapi_excluded_urls=environment.MONITORING_FASTAPI_EXCLUDED_URLS,
        fastapi_exclude_spans=environment.MONITORING_FASTAPI_EXCLUDE_SPANS,
        excluded_elasticsearch_operations=environment.MONITORING_EXCLUDED_ELASTICSEARCH_OPERATIONS,
        excluded_span_names=environment.MONITORING_EXCLUDED_SPAN_NAMES,
        project_name=environment.MONITORING_PROJECT_NAME or None,
        telemetry_sample_rate=environment.TELEMETRY_SAMPLE_RATE,
        trace_content_mode=environment.MONITORING_TRACE_CONTENT_MODE,
        trace_max_chars=environment.MONITORING_TRACE_MAX_CHARS,
        trace_max_items=environment.MONITORING_TRACE_MAX_ITEMS,
    )

    monitoring_manager.configure(config)
    configure_monitoring_records(
        write_model_monitoring_record if environment.ENABLE_MODEL_MONITORING else None,
        batch_size=environment.MODEL_MONITORING_BATCH_SIZE,
        flush_interval=environment.MODEL_MONITORING_FLUSH_INTERVAL_SECONDS,
    )
    logger.info(
        f"OTLP monitoring initialized: service_name={environment.OTEL_SERVICE_NAME}, "
        f"enable_telemetry={config.enable_telemetry}, provider={config.provider}, "
        f"endpoint={config.otlp_endpoint}, trace_endpoint={config.get_trace_endpoint()}, "
        f"protocol={environment.OTEL_EXPORTER_OTLP_PROTOCOL}"
    )
    return config


_monitoring_config = _initialize_monitoring()


def configure_trajectory(processor, observer):
    """Attach Runtime capture while preserving an existing remote tracer provider."""
    global local_trajectory_processor
    local_trajectory_processor = processor
    if environment.LOCAL_FILE_MONITORING_ENABLED:
        monitoring_manager.configure_local_capture(replace(
            _monitoring_config,
            enable_telemetry=True,
            capture_local_traces=True,
            local_span_processor=processor,
            local_execution_observer=observer,
        ))
    else:
        _monitoring_config.local_execution_observer = observer


__all__ = ['monitoring_manager']
