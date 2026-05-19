"""
Nexent LLM Performance Monitoring System

A comprehensive monitoring solution specifically designed for LLM applications.
Provides distributed tracing, token-level performance monitoring, and seamless
integration with OpenTelemetry OTLP protocol for AI observability platforms
like Arize Phoenix, Langfuse, LangSmith, and others.

This module uses a singleton pattern for consistent monitoring across the SDK.
When OpenTelemetry dependencies are not available, the module gracefully degrades
and disables monitoring functionality without breaking the application.

Installation:
- Basic: pip install nexent
- With monitoring: pip install nexent[performance]
"""

# Optional OpenTelemetry imports - gracefully handle missing dependencies
try:
    from opentelemetry.trace.status import Status, StatusCode
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPSpanExporterHTTP
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as OTLPSpanExporterGRPC
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPMetricExporterHTTP
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as OTLPMetricExporterGRPC
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.resources import Resource
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False

import logging
import os
import threading
import time
import functools
import json
import inspect
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Callable, TypeVar, cast, Iterator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Context variables for passing request-scoped metadata from service layer
# to monitoring layer without polluting function signatures.
_monitoring_tenant_id: ContextVar[Optional[str]] = ContextVar(
    "_monitoring_tenant_id", default=None)
_monitoring_user_id: ContextVar[Optional[str]] = ContextVar(
    "_monitoring_user_id", default=None)
_monitoring_agent_id: ContextVar[Optional[int]] = ContextVar(
    "_monitoring_agent_id", default=None)
_monitoring_conversation_id: ContextVar[Optional[int]] = ContextVar(
    "_monitoring_conversation_id", default=None)
_monitoring_agent_run_metadata: ContextVar[Optional["AgentRunMetadata"]] = ContextVar(
    "_monitoring_agent_run_metadata", default=None)
_monitoring_agent_run_active: ContextVar[bool] = ContextVar(
    "_monitoring_agent_run_active", default=False)

# Operation tag to identify which business scenario triggered the model call.
# Set at the service/call-site layer; read by the client-level monitoring wrapper.
_monitoring_operation: ContextVar[str] = ContextVar(
    "_monitoring_operation", default="unknown")

# display_name carried from model instance to client-level monitoring wrapper
_monitoring_display_name: ContextVar[Optional[str]] = ContextVar(
    "_monitoring_display_name", default=None)


def set_monitoring_context(
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[int] = None,
    conversation_id: Optional[int] = None,
) -> None:
    """Set monitoring context variables for the current async/task scope.

    Call this at the service layer where tenant_id, user_id, etc. are resolved,
    so that downstream monitoring code can access them automatically.
    """
    if tenant_id is not None:
        _monitoring_tenant_id.set(tenant_id)
    if user_id is not None:
        _monitoring_user_id.set(user_id)
    if agent_id is not None:
        _monitoring_agent_id.set(agent_id)
    if conversation_id is not None:
        _monitoring_conversation_id.set(conversation_id)


def set_monitoring_operation(operation: str, display_name: Optional[str] = None) -> None:
    _monitoring_operation.set(operation)
    if display_name is not None:
        _monitoring_display_name.set(display_name)


def get_monitoring_context() -> Dict[str, Any]:
    """Retrieve current monitoring context as a dict."""
    return {
        "tenant_id": _monitoring_tenant_id.get(),
        "user_id": _monitoring_user_id.get(),
        "agent_id": _monitoring_agent_id.get(),
        "conversation_id": _monitoring_conversation_id.get(),
    }


F = TypeVar('F', bound=Callable[..., Any])

DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"
TRACE_PATH = "/v1/traces"
METRIC_PATH = "/v1/metrics"
DEFAULT_TRACE_CONTENT_MODE = "summary"
DEFAULT_TRACE_MAX_CHARS = 4000
DEFAULT_TRACE_MAX_ITEMS = 20

OPENINFERENCE_SPAN_KIND = "openinference.span.kind"
OPENINFERENCE_SPAN_KIND_AGENT = "AGENT"
OPENINFERENCE_SPAN_KIND_CHAIN = "CHAIN"
OPENINFERENCE_SPAN_KIND_LLM = "LLM"
OPENINFERENCE_SPAN_KIND_TOOL = "TOOL"
OPENINFERENCE_SPAN_KIND_RETRIEVER = "RETRIEVER"
OPENINFERENCE_INPUT_VALUE = "input.value"
OPENINFERENCE_OUTPUT_VALUE = "output.value"
OPENINFERENCE_METADATA = "metadata"
OPENINFERENCE_SESSION_ID = "session.id"
OPENINFERENCE_USER_ID = "user.id"
OPENINFERENCE_TAG_TAGS = "tag.tags"

AGENT_OPERATION_NAMES = {
    "agent.run",
}
SUPPORTED_PROVIDERS = {
    "otlp",
    "phoenix",
    "langfuse",
    "langsmith",
    "grafana",
    "zipkin",
}


@dataclass
class AgentRunMetadata:
    """Request-scoped Agent observability metadata owned by the SDK."""
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[int] = None
    conversation_id: Optional[int] = None
    agent_name: Optional[str] = None
    query: Optional[str] = None
    is_debug: Optional[bool] = None
    language: Optional[str] = None
    model_name: Optional[str] = None
    memory_enabled: Optional[bool] = None
    history_count: Optional[int] = None
    minio_files_count: Optional[int] = None
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def metadata(self) -> Dict[str, Any]:
        """Return compact metadata for OpenInference/Langfuse attributes."""
        metadata: Dict[str, Any] = {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "tenant_id": self.tenant_id,
            "conversation_id": self.conversation_id,
            "is_debug": self.is_debug,
            "language": self.language,
            "model_name": self.model_name,
            "memory_enabled": self.memory_enabled,
            "history_count": self.history_count,
            "minio_files_count": self.minio_files_count,
        }
        metadata.update(self.extra_metadata or {})
        return {key: value for key, value in metadata.items() if value is not None}

    def tags(self) -> List[str]:
        """Return stable tags shared by Agent, LLM and Tool spans."""
        tags = ["nexent", "agent"]
        if self.agent_id is not None:
            tags.append(f"agent_id:{self.agent_id}")
        if self.tenant_id:
            tags.append(f"tenant_id:{self.tenant_id}")
        if self.is_debug is True:
            tags.append("debug")
        if self.memory_enabled is True:
            tags.append("memory_enabled")
        elif self.memory_enabled is False:
            tags.append("memory_disabled")
        return tags


AgentMonitoringContext = AgentRunMetadata


def _coerce_agent_run_metadata(
    metadata: Optional[AgentRunMetadata | Dict[str, Any]] = None,
) -> AgentRunMetadata:
    if metadata is None:
        current = _monitoring_agent_run_metadata.get()
        return current or AgentRunMetadata()
    if isinstance(metadata, AgentRunMetadata):
        return metadata
    if isinstance(metadata, dict):
        return AgentRunMetadata(**metadata)
    raise TypeError("metadata must be AgentRunMetadata, dict, or None")


def set_agent_monitoring_context(
    metadata: AgentRunMetadata | Dict[str, Any],
) -> AgentRunMetadata:
    """Bind Agent run metadata to the current request/task scope."""
    agent_metadata = _coerce_agent_run_metadata(metadata)
    _monitoring_agent_run_metadata.set(agent_metadata)
    _monitoring_tenant_id.set(agent_metadata.tenant_id)
    _monitoring_user_id.set(agent_metadata.user_id)
    _monitoring_agent_id.set(agent_metadata.agent_id)
    _monitoring_conversation_id.set(agent_metadata.conversation_id)
    return agent_metadata


def get_agent_monitoring_context() -> Optional[AgentRunMetadata]:
    """Return the current Agent run metadata, if any."""
    return _monitoring_agent_run_metadata.get()


@contextmanager
def agent_monitoring_context(
    metadata: AgentRunMetadata | Dict[str, Any],
) -> Iterator[AgentRunMetadata]:
    """Temporarily bind Agent run metadata and restore previous values."""
    agent_metadata = _coerce_agent_run_metadata(metadata)
    tokens = [
        (_monitoring_agent_run_metadata, _monitoring_agent_run_metadata.set(agent_metadata)),
        (_monitoring_tenant_id, _monitoring_tenant_id.set(agent_metadata.tenant_id)),
        (_monitoring_user_id, _monitoring_user_id.set(agent_metadata.user_id)),
        (_monitoring_agent_id, _monitoring_agent_id.set(agent_metadata.agent_id)),
        (_monitoring_conversation_id, _monitoring_conversation_id.set(agent_metadata.conversation_id)),
    ]
    try:
        yield agent_metadata
    finally:
        for context_var, token in reversed(tokens):
            context_var.reset(token)


def _as_bool(value: Any, default: bool = False) -> bool:
    """Convert common configuration values to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _as_float(value: Any, default: float) -> float:
    """Convert common configuration values to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    """Convert common configuration values to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_header_value(value: Any) -> str:
    """Normalize header values from config files or environment variables."""
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def _parse_headers(headers: Any) -> Dict[str, str]:
    """Parse headers from a dict or a key=value comma-separated string."""
    if not headers:
        return {}
    if isinstance(headers, dict):
        return {
            str(key).strip(): _normalize_header_value(value).strip()
            for key, value in headers.items()
            if str(key).strip() and value not in (None, "")
        }
    if isinstance(headers, str):
        parsed = {}
        for pair in headers.split(","):
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            key = key.strip()
            if key:
                parsed[key] = value.strip()
        return parsed
    return {}


def _split_url_patterns(value: str) -> List[str]:
    """Split comma-separated URL regex patterns and drop empty entries."""
    return [
        item.strip()
        for item in (value or "").split(",")
        if item.strip()
    ]


def _build_fastapi_excluded_urls(
    included_urls: str,
    excluded_urls: str,
) -> str:
    """Build FastAPI excluded URL regex from included/excluded settings.

    Excluded URL patterns are always skipped. If included URLs are empty, every
    non-excluded URL is monitored. If included URLs have entries, only matching
    URLs are monitored and every non-matching URL is excluded.
    """
    excluded = _split_url_patterns(excluded_urls)
    included = _split_url_patterns(included_urls)
    if not included:
        return ",".join(excluded)

    allow_group = "|".join(f"(?:{pattern})" for pattern in included)
    exclude_non_included = f"^(?!.*(?:{allow_group})).*$"
    return ",".join([*excluded, exclude_non_included])


def _derive_http_signal_endpoint(endpoint: str, signal_path: str) -> str:
    """
    Build a signal-specific OTLP HTTP endpoint from a base or signal endpoint.

    This accepts both base endpoints like `/api/public/otel` and existing signal
    endpoints like `/api/public/otel/v1/traces`, avoiding duplicated `/v1/*`
    suffixes.
    """
    endpoint = (endpoint or DEFAULT_OTLP_ENDPOINT).rstrip("/")
    if endpoint.endswith(signal_path):
        return endpoint
    if endpoint.endswith(TRACE_PATH):
        return endpoint[: -len(TRACE_PATH)] + signal_path
    if endpoint.endswith(METRIC_PATH):
        return endpoint[: -len(METRIC_PATH)] + signal_path
    return endpoint + signal_path


def is_opentelemetry_available() -> bool:
    """Check if OpenTelemetry dependencies are available."""
    return OPENTELEMETRY_AVAILABLE


@dataclass
class MonitoringConfig:
    """
    Configuration for monitoring system using OTLP protocol.

    Supports HTTP and gRPC protocols for exporting traces and metrics
    to any OpenTelemetry-compatible backend (Arize Phoenix, Langfuse, LangSmith, etc).
    """
    enable_telemetry: bool = False
    service_name: str = "nexent-backend"
    provider: str = "otlp"
    otlp_endpoint: str = DEFAULT_OTLP_ENDPOINT
    otlp_traces_endpoint: Optional[str] = None
    otlp_metrics_endpoint: Optional[str] = None
    otlp_protocol: str = "http"  # "http" or "grpc"
    otlp_headers: Dict[str, str] = field(default_factory=dict)
    export_traces: bool = True
    export_metrics: bool = True
    instrument_requests: bool = False
    fastapi_included_urls: str = ""
    fastapi_excluded_urls: str = ""
    fastapi_exclude_spans: List[str] = field(default_factory=lambda: ["receive", "send"])
    project_name: Optional[str] = None
    telemetry_sample_rate: float = 1.0
    trace_content_mode: str = DEFAULT_TRACE_CONTENT_MODE
    trace_max_chars: int = DEFAULT_TRACE_MAX_CHARS
    trace_max_items: int = DEFAULT_TRACE_MAX_ITEMS

    def __post_init__(self):
        """Validate configuration and adjust based on OpenTelemetry availability."""
        self.provider = (self.provider or "otlp").strip().lower()
        if self.provider not in SUPPORTED_PROVIDERS:
            logger.warning(
                f"Unknown monitoring provider '{self.provider}'. Using 'otlp'."
            )
            self.provider = "otlp"

        self.enable_telemetry = _as_bool(self.enable_telemetry)
        self.export_traces = _as_bool(self.export_traces, True)
        self.export_metrics = _as_bool(self.export_metrics, True)
        self.instrument_requests = _as_bool(self.instrument_requests, False)
        self.fastapi_included_urls = str(self.fastapi_included_urls or "").strip()
        self.fastapi_excluded_urls = str(self.fastapi_excluded_urls or "").strip()
        if isinstance(self.fastapi_exclude_spans, str):
            self.fastapi_exclude_spans = [
                item.strip()
                for item in self.fastapi_exclude_spans.split(",")
                if item.strip()
            ]
        else:
            self.fastapi_exclude_spans = [
                str(item).strip()
                for item in self.fastapi_exclude_spans
                if str(item).strip()
            ]
        self.telemetry_sample_rate = _as_float(self.telemetry_sample_rate, 1.0)
        self.trace_content_mode = str(
            self.trace_content_mode or DEFAULT_TRACE_CONTENT_MODE
        ).strip().lower()
        if self.trace_content_mode not in {"summary", "metrics", "full"}:
            logger.warning(
                f"Unknown trace content mode '{self.trace_content_mode}'. Using 'summary'."
            )
            self.trace_content_mode = DEFAULT_TRACE_CONTENT_MODE
        self.trace_max_chars = max(
            0,
            _as_int(self.trace_max_chars, DEFAULT_TRACE_MAX_CHARS),
        )
        self.trace_max_items = max(
            0,
            _as_int(self.trace_max_items, DEFAULT_TRACE_MAX_ITEMS),
        )
        self.otlp_headers = _parse_headers(self.otlp_headers)

        if self.enable_telemetry and not OPENTELEMETRY_AVAILABLE:
            logger.warning(
                "OpenTelemetry dependencies not available. Disabling telemetry. "
                "Install with: pip install nexent[performance]"
            )
            self.enable_telemetry = False

        # Validate protocol
        self.otlp_protocol = (self.otlp_protocol or "http").strip().lower()
        if self.otlp_protocol not in ("http", "grpc"):
            logger.warning(
                f"Invalid OTLP protocol '{self.otlp_protocol}'. Using 'http'."
            )
            self.otlp_protocol = "http"

        if self.provider in {"phoenix", "langfuse", "langsmith"} and self.otlp_protocol == "grpc":
            logger.warning(
                f"{self.provider} OTLP integration only supports HTTP in this configuration. Using 'http'."
            )
            self.otlp_protocol = "http"

    def get_trace_endpoint(self) -> str:
        """Return the resolved trace exporter endpoint."""
        if self.otlp_protocol == "grpc":
            return self.otlp_traces_endpoint or self.otlp_endpoint
        return _derive_http_signal_endpoint(
            self.otlp_traces_endpoint or self.otlp_endpoint,
            TRACE_PATH,
        )

    def get_metric_endpoint(self) -> str:
        """Return the resolved metric exporter endpoint."""
        if self.otlp_protocol == "grpc":
            return self.otlp_metrics_endpoint or self.otlp_endpoint
        return _derive_http_signal_endpoint(
            self.otlp_metrics_endpoint or self.otlp_endpoint,
            METRIC_PATH,
        )


class MonitoringManager:
    """Singleton monitoring manager for the entire SDK."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MonitoringManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._config: Optional[MonitoringConfig] = None
        self._tracer_provider: Optional[Any] = None
        self._meter_provider: Optional[Any] = None
        self._tracer: Optional[Any] = None
        self._meter: Optional[Any] = None

        # LLM-specific metrics (OpenInference semantics)
        self._llm_request_duration: Optional[Any] = None
        self._llm_token_generation_rate: Optional[Any] = None
        self._llm_ttft_duration: Optional[Any] = None
        self._llm_token_count_prompt: Optional[Any] = None
        self._llm_token_count_completion: Optional[Any] = None
        self._llm_error_count: Optional[Any] = None

        # Agent-specific metrics (OpenInference semantics)
        self._agent_step_count: Optional[Any] = None
        self._agent_error_count: Optional[Any] = None

        self._initialized = True
        logger.info("MonitoringManager singleton created")

    def configure(self, config: MonitoringConfig) -> None:
        """Configure the monitoring system."""
        self._config = config
        logger.info(
            f"Monitoring configured: enabled={config.enable_telemetry}, "
            f"service={config.service_name}, provider={config.provider}, "
            f"protocol={config.otlp_protocol}"
        )

        if config.enable_telemetry:
            self._init_telemetry_otlp()

    def _init_telemetry_otlp(self) -> None:
        """Initialize OpenTelemetry tracing and metrics with OTLP exporters."""
        if not self._config or not self._config.enable_telemetry:
            logger.info("Telemetry is disabled by configuration")
            return

        if not OPENTELEMETRY_AVAILABLE:
            logger.warning(
                "OpenTelemetry dependencies not available. Telemetry initialization skipped. "
                "Install with: pip install nexent[performance]"
            )
            return

        try:
            # Setup resource with service name.
            resource_attributes = {
                "service.name": self._config.service_name,
                "service.version": "1.0.0",
                "service.instance.id": "nexent-instance-1",
                "telemetry.provider": self._config.provider,
            }
            if self._config.project_name:
                resource_attributes["project.name"] = self._config.project_name
            resource = Resource.create(resource_attributes)

            # Initialize TracerProvider with OTLP exporter
            self._tracer_provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(self._tracer_provider)

            if self._config.export_traces:
                # Choose exporter based on protocol
                if self._config.otlp_protocol == "grpc":
                    span_exporter = OTLPSpanExporterGRPC(
                        endpoint=self._config.get_trace_endpoint(),
                        headers=self._config.otlp_headers
                    )
                else:
                    span_exporter = OTLPSpanExporterHTTP(
                        endpoint=self._config.get_trace_endpoint(),
                        headers=self._config.otlp_headers
                    )

                # BatchSpanProcessor for efficient export
                span_processor = BatchSpanProcessor(
                    span_exporter,
                    max_queue_size=512,
                    schedule_delay_millis=1000,  # 1 second
                    max_export_batch_size=512
                )
                self._tracer_provider.add_span_processor(span_processor)

            metric_readers = []
            if self._config.export_metrics:
                # Initialize MeterProvider with OTLP exporter
                if self._config.otlp_protocol == "grpc":
                    metric_exporter = OTLPMetricExporterGRPC(
                        endpoint=self._config.get_metric_endpoint(),
                        headers=self._config.otlp_headers
                    )
                else:
                    metric_exporter = OTLPMetricExporterHTTP(
                        endpoint=self._config.get_metric_endpoint(),
                        headers=self._config.otlp_headers
                    )

                # PeriodicExportingMetricReader for batch export
                metric_readers.append(PeriodicExportingMetricReader(
                    exporter=metric_exporter,
                    export_interval_millis=60000  # 60 seconds
                ))

            self._meter_provider = MeterProvider(
                resource=resource,
                metric_readers=metric_readers
            )
            metrics.set_meter_provider(self._meter_provider)

            # Get tracer and meter instances
            self._tracer = trace.get_tracer(self._config.service_name)
            self._meter = metrics.get_meter(self._config.service_name)

            # Create LLM-specific metrics (OpenInference semantic conventions)
            self._llm_request_duration = self._meter.create_histogram(
                name="llm.request.duration",
                description="Duration of LLM requests in seconds",
                unit="s"
            )

            self._llm_token_generation_rate = self._meter.create_histogram(
                name="llm.token.generation_rate",
                description="Token generation rate (tokens per second)",
                unit="tokens/s"
            )

            self._llm_ttft_duration = self._meter.create_histogram(
                name="llm.time_to_first_token",
                description="Time to first token (TTFT) in seconds",
                unit="s"
            )

            self._llm_token_count_prompt = self._meter.create_counter(
                name="llm.token_count.prompt",
                description="Number of prompt/input tokens",
                unit="tokens"
            )

            self._llm_token_count_completion = self._meter.create_counter(
                name="llm.token_count.completion",
                description="Number of completion/output tokens",
                unit="tokens"
            )

            self._llm_error_count = self._meter.create_counter(
                name="llm.error.count",
                description="Number of LLM errors",
                unit="errors"
            )

            # Create Agent-specific metrics (OpenInference semantic conventions)
            self._agent_step_count = self._meter.create_counter(
                name="agent.step.count",
                description="Number of agent execution steps",
                unit="steps"
            )

            self._agent_error_count = self._meter.create_counter(
                name="agent.error.count",
                description="Number of agent execution errors",
                unit="errors"
            )

            # Auto-instrument outbound HTTP calls only when explicitly enabled.
            # AI observability UIs otherwise get noisy generic HTTP spans.
            if self._config.instrument_requests:
                RequestsInstrumentor().instrument()

            logger.info(
                f"OTLP telemetry initialized successfully for service: {self._config.service_name}, "
                f"provider: {self._config.provider}, trace_endpoint: {self._config.get_trace_endpoint()}, "
                f"metric_endpoint: {self._config.get_metric_endpoint()}, protocol: {self._config.otlp_protocol}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize OTLP telemetry: {str(e)}")
            # Do not raise - allow application to continue without monitoring

    @property
    def is_enabled(self) -> bool:
        """Check if monitoring is enabled."""
        return (self._config is not None and
                self._config.enable_telemetry and
                OPENTELEMETRY_AVAILABLE)

    @property
    def tracer(self):
        """Get the tracer instance."""
        return self._tracer

    def setup_fastapi_app(self, app) -> bool:
        """Setup monitoring for a FastAPI application."""
        try:
            if self.is_enabled and app and OPENTELEMETRY_AVAILABLE and self._config:
                instrument_kwargs: Dict[str, Any] = {}
                excluded_urls = _build_fastapi_excluded_urls(
                    self._config.fastapi_included_urls,
                    self._config.fastapi_excluded_urls,
                )
                if excluded_urls:
                    instrument_kwargs["excluded_urls"] = excluded_urls

                signature = inspect.signature(FastAPIInstrumentor.instrument_app)
                if "exclude_spans" in signature.parameters:
                    instrument_kwargs["exclude_spans"] = self._config.fastapi_exclude_spans

                FastAPIInstrumentor.instrument_app(app, **instrument_kwargs)
                logger.info(
                    "FastAPI application monitoring initialized successfully"
                )
                return True
            elif not OPENTELEMETRY_AVAILABLE:
                logger.warning(
                    "OpenTelemetry not available. FastAPI monitoring skipped. "
                    "Install with: pip install nexent[performance]"
                )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize FastAPI monitoring: {e}")
            return False

    @staticmethod
    def _infer_openinference_span_kind(operation_name: str) -> str:
        """Infer OpenInference span kind for Nexent service operations."""
        if operation_name in AGENT_OPERATION_NAMES:
            return OPENINFERENCE_SPAN_KIND_AGENT
        return OPENINFERENCE_SPAN_KIND_CHAIN

    @staticmethod
    def _to_openinference_json_value(value: Any) -> str:
        """Convert a value to the JSON-string form expected by OpenInference."""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _to_langfuse_attribute_value(value: Any) -> Any:
        """Convert metadata values to Langfuse filterable attribute values."""
        if isinstance(value, (str, int, float, bool)):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    def build_openinference_attributes(
        self,
        span_kind: str,
        input_value: Any = None,
        output_value: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        session_id: Optional[Any] = None,
        user_id: Optional[Any] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build Phoenix/OpenInference attributes for a custom span."""
        attrs: Dict[str, Any] = {
            OPENINFERENCE_SPAN_KIND: span_kind,
        }
        if input_value is not None:
            input_preview = self._trace_payload_preview(input_value)
            if input_preview != "":
                attrs[OPENINFERENCE_INPUT_VALUE] = input_preview
            attrs.update(self._trace_payload_attributes("input", input_value))
        if output_value is not None:
            output_preview = self._trace_payload_preview(output_value)
            if output_preview != "":
                attrs[OPENINFERENCE_OUTPUT_VALUE] = output_preview
            attrs.update(self._trace_payload_attributes("output", output_value))
        if metadata is not None:
            attrs[OPENINFERENCE_METADATA] = self._to_openinference_json_value(
                metadata)
        if tags is not None:
            attrs[OPENINFERENCE_TAG_TAGS] = self._to_openinference_json_value(
                tags)
        if session_id is not None:
            attrs[OPENINFERENCE_SESSION_ID] = str(session_id)
        if user_id is not None:
            attrs[OPENINFERENCE_USER_ID] = str(user_id)
        if attributes:
            attrs.update(attributes)
        return attrs

    def build_agent_run_attributes(
        self,
        metadata: Optional[AgentRunMetadata | Dict[str, Any]] = None,
        span_kind: str = OPENINFERENCE_SPAN_KIND_AGENT,
        include_query: bool = True,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build SDK-owned Agent observability attributes for any span."""
        agent_metadata = _coerce_agent_run_metadata(metadata)
        plain_attrs: Dict[str, Any] = {
            "tenant.id": agent_metadata.tenant_id,
            "agent.id": agent_metadata.agent_id,
            "agent.name": agent_metadata.agent_name,
            "conversation.id": agent_metadata.conversation_id,
            "agent.debug": agent_metadata.is_debug,
            "agent.language": agent_metadata.language,
            "agent.memory.enabled": agent_metadata.memory_enabled,
            "agent.history.count": agent_metadata.history_count,
            "agent.minio_files.count": agent_metadata.minio_files_count,
            "llm.model_name": agent_metadata.model_name,
        }
        plain_attrs = {
            key: value for key, value in plain_attrs.items() if value is not None
        }
        if attributes:
            plain_attrs.update(attributes)

        return self.build_openinference_attributes(
            span_kind=span_kind,
            input_value=agent_metadata.query if include_query else None,
            metadata=agent_metadata.metadata(),
            tags=agent_metadata.tags(),
            session_id=agent_metadata.conversation_id,
            user_id=agent_metadata.user_id,
            attributes=plain_attrs,
        )

    def bind_agent_context(
        self,
        metadata: AgentRunMetadata | Dict[str, Any],
    ) -> AgentRunMetadata:
        """Bind Agent metadata once at the application boundary."""
        return set_agent_monitoring_context(metadata)

    @contextmanager
    def start_agent_run(
        self,
        metadata: Optional[AgentRunMetadata | Dict[str, Any]] = None,
        operation_name: str = "agent.run",
    ) -> Iterator[Optional[Any]]:
        """Create the SDK-owned top-level Agent span."""
        agent_metadata = _coerce_agent_run_metadata(metadata)
        with agent_monitoring_context(agent_metadata):
            if _monitoring_agent_run_active.get():
                yield self.get_current_span()
                return

            active_token = _monitoring_agent_run_active.set(True)
            attributes = self.build_agent_run_attributes(
                agent_metadata,
                span_kind=OPENINFERENCE_SPAN_KIND_AGENT,
                include_query=True,
            )
            try:
                with self.trace_operation(
                    operation_name,
                    OPENINFERENCE_SPAN_KIND_AGENT,
                    **attributes,
                ) as span:
                    self.add_span_event(f"{operation_name}.started")
                    try:
                        yield span
                        self.add_span_event(f"{operation_name}.completed")
                    except Exception as error:
                        self.add_span_event(f"{operation_name}.error", {
                            "error.type": type(error).__name__,
                            "error.message": str(error),
                        })
                        raise
            finally:
                _monitoring_agent_run_active.reset(active_token)

    @contextmanager
    def with_agent_monitoring(
        self,
        metadata: Optional[AgentRunMetadata | Dict[str, Any]] = None,
        operation_name: str = "agent.run",
    ) -> Iterator[Optional[Any]]:
        """Alias for the SDK-owned top-level Agent span."""
        with self.start_agent_run(metadata, operation_name) as span:
            yield span

    @contextmanager
    def trace_agent_step(
        self,
        operation_name: str,
        metadata: Optional[AgentRunMetadata | Dict[str, Any]] = None,
        step_type: str = "chain",
        **attributes: Any,
    ) -> Iterator[Optional[Any]]:
        """Trace an Agent lifecycle step without requiring business decorators."""
        agent_metadata = _coerce_agent_run_metadata(metadata)
        step_attrs = self.build_agent_run_attributes(
            agent_metadata,
            span_kind=OPENINFERENCE_SPAN_KIND_CHAIN,
            include_query=False,
            attributes={
                "agent.step.name": operation_name,
                "agent.step.type": step_type,
                **attributes,
            },
        )
        with self.trace_operation(
            operation_name,
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **step_attrs,
        ) as span:
            yield span

    @contextmanager
    def trace_operation(
        self,
        operation_name: str,
        span_kind: str = OPENINFERENCE_SPAN_KIND_CHAIN,
        **attributes: Any
    ) -> Iterator[Optional[Any]]:
        """Trace a non-LLM operation using OpenInference span kind semantics."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE or not self._tracer:
            yield None
            return

        span_attrs = {
            OPENINFERENCE_SPAN_KIND: span_kind,
        }
        span_attrs.update(attributes)

        with self._tracer.start_as_current_span(
            operation_name,
            attributes=span_attrs
        ) as span:
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                raise

    def set_openinference_output(
        self,
        output_value: Any,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Attach OpenInference output fields to the current span."""
        attrs = self.build_openinference_attributes(
            span_kind="",
            output_value=output_value,
            metadata=metadata,
            tags=tags,
        )
        attrs.pop(OPENINFERENCE_SPAN_KIND, None)
        self.set_span_attributes(**attrs)

    def set_openinference_agent_context(
        self,
        agent_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        query: Optional[str] = None,
        is_debug: Optional[bool] = None,
        memory_enabled: Optional[bool] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        span_kind: Optional[str] = OPENINFERENCE_SPAN_KIND_AGENT,
    ) -> None:
        """Attach Phoenix/OpenInference agent dimensions to the current span."""
        metadata = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "is_debug": is_debug,
            "memory_enabled": memory_enabled,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        metadata = {k: v for k, v in metadata.items() if v is not None}

        tags = ["nexent", "agent"]
        if agent_id is not None:
            tags.append(f"agent_id:{agent_id}")
        if tenant_id:
            tags.append(f"tenant_id:{tenant_id}")
        if is_debug is True:
            tags.append("debug")
        if memory_enabled is True:
            tags.append("memory_enabled")
        elif memory_enabled is False:
            tags.append("memory_disabled")

        attrs: Dict[str, Any] = {
            OPENINFERENCE_METADATA: json.dumps(metadata, ensure_ascii=False),
            OPENINFERENCE_TAG_TAGS: json.dumps(tags, ensure_ascii=False),
        }
        if span_kind:
            attrs[OPENINFERENCE_SPAN_KIND] = span_kind
        if query is not None:
            query_preview = self._trace_payload_preview(query)
            if query_preview != "":
                attrs[OPENINFERENCE_INPUT_VALUE] = query_preview
            attrs.update(self._trace_payload_attributes("input", query))
        if conversation_id is not None:
            attrs[OPENINFERENCE_SESSION_ID] = str(conversation_id)
            attrs["conversation.id"] = conversation_id
        if user_id:
            attrs[OPENINFERENCE_USER_ID] = str(user_id)
        if tenant_id:
            attrs["tenant.id"] = str(tenant_id)
        if agent_id is not None:
            attrs["agent.id"] = agent_id
        if agent_name:
            attrs["agent.name"] = agent_name

        self.set_span_attributes(**attrs)

    def apply_openinference_context_attributes(
        self,
        span_kind: Optional[str] = None,
    ) -> None:
        """Attach request-scoped OpenInference context to the current span."""
        agent_metadata = get_agent_monitoring_context()
        if agent_metadata is not None:
            attrs = self.build_agent_run_attributes(
                agent_metadata,
                span_kind=span_kind or OPENINFERENCE_SPAN_KIND_CHAIN,
                include_query=span_kind == OPENINFERENCE_SPAN_KIND_AGENT,
            )
            self.set_span_attributes(**attrs)
            return

        context = get_monitoring_context()
        agent_id = context.get("agent_id")
        conversation_id = context.get("conversation_id")
        user_id = context.get("user_id")
        tenant_id = context.get("tenant_id")
        if not any([agent_id is not None, conversation_id is not None, user_id, tenant_id]):
            return

        metadata = {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}

        tags = ["nexent"]
        if span_kind == OPENINFERENCE_SPAN_KIND_AGENT:
            tags.append("agent")
        if agent_id is not None:
            tags.append(f"agent_id:{agent_id}")
        if tenant_id:
            tags.append(f"tenant_id:{tenant_id}")

        attrs: Dict[str, Any] = {
            OPENINFERENCE_METADATA: json.dumps(metadata, ensure_ascii=False),
            OPENINFERENCE_TAG_TAGS: json.dumps(tags, ensure_ascii=False),
        }
        if span_kind:
            attrs[OPENINFERENCE_SPAN_KIND] = span_kind
        if conversation_id is not None:
            attrs[OPENINFERENCE_SESSION_ID] = str(conversation_id)
            attrs["conversation.id"] = conversation_id
        if user_id:
            attrs[OPENINFERENCE_USER_ID] = str(user_id)
        if tenant_id:
            attrs["tenant.id"] = str(tenant_id)
        if agent_id is not None:
            attrs["agent.id"] = agent_id

        self.set_span_attributes(**attrs)

    @contextmanager
    def trace_llm_request(self, operation_name: str, model_name: str, **attributes: Any) -> Iterator[Optional[Any]]:
        """
        Context manager for tracing LLM requests with comprehensive metrics.
        Uses OpenInference semantic conventions for attribute naming.
        """
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE or not self._tracer:
            yield None
            return

        # OpenInference semantic attributes
        openinference_attrs = {
            OPENINFERENCE_SPAN_KIND: attributes.pop(
                OPENINFERENCE_SPAN_KIND,
                OPENINFERENCE_SPAN_KIND_LLM,
            ),
            "llm.model_name": model_name,
            "llm.operation.name": operation_name,
            "gen_ai.request.model": model_name,
        }
        agent_metadata = get_agent_monitoring_context()
        if agent_metadata is not None:
            openinference_attrs.update(self.build_agent_run_attributes(
                agent_metadata,
                span_kind=OPENINFERENCE_SPAN_KIND_LLM,
                include_query=False,
            ))
        input_value = attributes.pop(OPENINFERENCE_INPUT_VALUE, None)
        output_value = attributes.pop(OPENINFERENCE_OUTPUT_VALUE, None)
        if input_value is not None:
            input_preview = self._trace_payload_preview(input_value)
            if input_preview != "":
                openinference_attrs[OPENINFERENCE_INPUT_VALUE] = input_preview
            openinference_attrs.update(
                self._trace_payload_attributes("input", input_value)
            )
        if output_value is not None:
            output_preview = self._trace_payload_preview(output_value)
            if output_preview != "":
                openinference_attrs[OPENINFERENCE_OUTPUT_VALUE] = output_preview
            openinference_attrs.update(
                self._trace_payload_attributes("output", output_value)
            )

        # Add user-provided attributes
        openinference_attrs.update(attributes)
        openinference_attrs[OPENINFERENCE_SPAN_KIND] = OPENINFERENCE_SPAN_KIND_LLM
        openinference_attrs["llm.model_name"] = model_name
        openinference_attrs["llm.operation.name"] = operation_name
        openinference_attrs["gen_ai.request.model"] = model_name

        with self._tracer.start_as_current_span(
            operation_name,
            attributes=openinference_attrs
        ) as span:
            start_time = time.time()
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                if self._llm_error_count:
                    self._llm_error_count.add(
                        1, {"llm.model_name": model_name, "llm.operation.name": operation_name}
                    )
                raise
            finally:
                duration = time.time() - start_time
                if self._llm_request_duration:
                    self._llm_request_duration.record(
                        duration, {"llm.model_name": model_name, "llm.operation.name": operation_name}
                    )

    def _trace_payload_config(self) -> tuple[str, int, int]:
        config = self._config
        if config is None:
            return (
                DEFAULT_TRACE_CONTENT_MODE,
                DEFAULT_TRACE_MAX_CHARS,
                DEFAULT_TRACE_MAX_ITEMS,
            )
        return (
            config.trace_content_mode,
            config.trace_max_chars,
            config.trace_max_items,
        )

    def _limited_payload(self, value: Any, max_items: int) -> Any:
        if max_items <= 0:
            if isinstance(value, dict):
                return {}
            if isinstance(value, (list, tuple, set)):
                return []
            return value

        if isinstance(value, dict):
            return {
                key: value[key]
                for key in list(value.keys())[:max_items]
            }
        if isinstance(value, (list, tuple)):
            return list(value[:max_items])
        if isinstance(value, set):
            return list(value)[:max_items]
        return value

    def _trace_payload_summary(self, value: Any) -> Dict[str, Any]:
        """Create a bounded trace-safe payload summary."""
        mode, max_chars, max_items = self._trace_payload_config()
        payload_type = type(value).__name__
        item_count: Optional[int] = None
        keys: List[str] = []

        if isinstance(value, dict):
            item_count = len(value)
            keys = [str(key) for key in list(value.keys())[:max_items]]
        elif isinstance(value, (list, tuple, set)):
            item_count = len(value)
        elif isinstance(value, str):
            item_count = 1

        full_value = self._to_openinference_json_value(value)
        full_size = len(full_value)
        truncated = False

        if mode == "metrics":
            preview = ""
            truncated = full_size > 0
        else:
            preview_value = value if mode == "full" else self._limited_payload(value, max_items)
            preview = self._to_openinference_json_value(preview_value)
            if mode != "full" and item_count is not None and item_count > max_items:
                truncated = True
            if max_chars and len(preview) > max_chars:
                preview = preview[:max_chars] + "...[truncated]"
                truncated = True
            elif mode != "full" and preview != full_value:
                truncated = True

        return {
            "preview": preview,
            "type": payload_type,
            "size_chars": full_size,
            "item_count": item_count,
            "truncated": truncated,
            "keys": keys,
        }

    def _trace_payload_attributes(self, prefix: str, value: Any) -> Dict[str, Any]:
        summary = self._trace_payload_summary(value)
        attrs: Dict[str, Any] = {
            f"{prefix}.type": summary["type"],
            f"{prefix}.size_chars": summary["size_chars"],
            f"{prefix}.truncated": summary["truncated"],
        }
        if summary["preview"] != "":
            attrs[f"{prefix}.preview"] = summary["preview"]
        if summary["item_count"] is not None:
            attrs[f"{prefix}.item_count"] = summary["item_count"]
        if summary["keys"]:
            attrs[f"{prefix}.keys"] = json.dumps(
                summary["keys"],
                ensure_ascii=False,
            )
        return attrs

    def _trace_payload_preview(self, value: Any) -> str:
        return str(self._trace_payload_summary(value)["preview"])

    @staticmethod
    def _coerce_results_payload(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return value
        return value

    def _retrieval_result_attributes(self, value: Any) -> Dict[str, Any]:
        payload = self._coerce_results_payload(value)
        results: Optional[List[Any]] = None
        if isinstance(payload, list):
            results = payload
        elif isinstance(payload, dict):
            for key in ("results", "documents", "items"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    results = candidate
                    break

        if results is None:
            return {}

        attrs: Dict[str, Any] = {
            "retrieval.results.count": len(results),
        }
        scores: List[float] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            score = item.get("score", item.get("relevance_score"))
            if isinstance(score, (int, float)):
                scores.append(float(score))
        if scores:
            attrs["retrieval.top_score"] = max(scores)
        return attrs

    def record_agent_step_metrics(
        self,
        metric: Dict[str, Any],
        token_threshold: Optional[int] = None,
    ) -> None:
        """Record context/compression metrics for one Agent step on the current span."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        compression = metric.get("compression", {}) or {}
        memory_state = metric.get("memory_state", {}) or {}
        attrs = {
            "agent.step.number": metric.get("step_number", 0),
            "llm.token_count.prompt": metric.get("main_llm", {}).get("input_tokens", 0),
            "llm.token_count.completion": metric.get("main_llm", {}).get("output_tokens", 0),
            "context.tokens.estimated_input": memory_state.get("estimated_input_tokens", 0),
            "context.tokens.estimated_output": memory_state.get("estimated_output_tokens", 0),
            "context.tokens.uncompressed_estimated": metric.get("uncompressed_mem_est_input", 0),
            "context.compression.calls": compression.get("calls", 0),
            "context.compression.input_tokens": compression.get("input_tokens", 0),
            "context.compression.output_tokens": compression.get("output_tokens", 0),
            "context.compression.cache_hits": compression.get("cache_hits", 0),
            "context.compression.ratio": metric.get("compression_ratio", 0.0),
            "context.compression.cache_hit": metric.get("cache_hit", False),
        }
        if token_threshold is not None:
            attrs["context.token_threshold"] = token_threshold
        cache_types = metric.get("cache_types") or compression.get("cache_types") or []
        if cache_types:
            attrs["context.compression.cache_types"] = json.dumps(
                cache_types,
                ensure_ascii=False,
            )
        self.add_span_event("agent.step.metrics", attrs)

    def set_agent_context_metrics(self, metrics: List[Dict[str, Any]]) -> None:
        """Attach aggregate context/compression metrics to the current Agent span."""
        if not metrics:
            return

        estimated_inputs = [
            (metric.get("memory_state") or {}).get("estimated_input_tokens", 0)
            for metric in metrics
        ]
        compression_ratios = [
            metric.get("compression_ratio", 0.0)
            for metric in metrics
        ]
        compression_calls = sum(
            (metric.get("compression") or {}).get("calls", 0)
            for metric in metrics
        )
        compression_cache_hits = sum(
            (metric.get("compression") or {}).get("cache_hits", 0)
            for metric in metrics
        )
        attrs = {
            "agent.steps.count": len(metrics),
            "context.tokens.max_estimated_input": max(estimated_inputs or [0]),
            "context.compression.avg_ratio": (
                round(sum(compression_ratios) / len(compression_ratios), 2)
                if compression_ratios
                else 0.0
            ),
            "context.compression.calls.total": compression_calls,
            "context.compression.cache_hits.total": compression_cache_hits,
        }
        self.set_span_attributes(**attrs)

    @contextmanager
    def trace_tool_call(
        self,
        tool_name: str,
        agent_name: str,
        tool_input: Optional[Dict] = None,
        **attributes: Any
    ) -> Iterator[Optional[Any]]:
        """
        Context manager for tracing Agent tool calls.
        Uses OpenInference semantic conventions for attribute naming.

        Args:
            tool_name: Name of the tool being called
            agent_name: Name of the agent making the call
            tool_input: Input parameters for the tool (will be JSON serialized)
            **attributes: Additional attributes to add to the span
        """
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE or not self._tracer:
            yield None
            return

        # OpenInference semantic attributes for tool call
        openinference_attrs = {
            OPENINFERENCE_SPAN_KIND: attributes.pop(
                OPENINFERENCE_SPAN_KIND,
                OPENINFERENCE_SPAN_KIND_TOOL,
            ),
            "agent.name": agent_name,
            "agent.step.name": tool_name,
            "agent.step.type": "tool_call",
            "agent.tool.name": tool_name,
            "tool.name": tool_name,
        }
        agent_metadata = get_agent_monitoring_context()
        if agent_metadata is not None:
            openinference_attrs.update(self.build_agent_run_attributes(
                agent_metadata,
                span_kind=OPENINFERENCE_SPAN_KIND_TOOL,
                include_query=False,
            ))
            openinference_attrs.update({
                OPENINFERENCE_SPAN_KIND: OPENINFERENCE_SPAN_KIND_TOOL,
                "agent.name": agent_name,
                "agent.step.name": tool_name,
                "agent.step.type": "tool_call",
                "agent.tool.name": tool_name,
                "tool.name": tool_name,
            })

        # Add tool input as JSON string
        if tool_input is not None:
            tool_input_preview = self._trace_payload_preview(tool_input)
            openinference_attrs["agent.tool.input"] = tool_input_preview
            openinference_attrs["tool.parameters"] = tool_input_preview
            openinference_attrs[OPENINFERENCE_INPUT_VALUE] = tool_input_preview
            openinference_attrs.update(
                self._trace_payload_attributes("agent.tool.input", tool_input)
            )

        openinference_attrs.update(attributes)

        span_name = f"agent.tool.{tool_name}"

        with self._tracer.start_as_current_span(
            span_name,
            attributes=openinference_attrs
        ) as span:
            start_time = time.time()
            success = True
            try:
                yield span
            except Exception as e:
                success = False
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                span.set_attribute("agent.tool.success", False)
                if self._agent_error_count:
                    self._agent_error_count.add(
                        1, {"agent.name": agent_name, "error.type": type(e).__name__, "agent.tool.name": tool_name}
                    )
                raise
            finally:
                duration = time.time() - start_time
                duration_ms = duration * 1000
                span.set_attribute("agent.tool.duration_ms", duration_ms)
                if success:
                    span.set_attribute("agent.tool.success", True)
                if self._agent_step_count:
                    self._agent_step_count.add(
                        1, {"agent.name": agent_name, "agent.step.type": "tool_call", "agent.tool.name": tool_name}
                    )

    @contextmanager
    def trace_retriever_call(
        self,
        retriever_name: str,
        agent_name: Optional[str] = None,
        retrieval_input: Optional[Dict] = None,
        **attributes: Any,
    ) -> Iterator[Optional[Any]]:
        """Trace SDK-owned memory/retriever calls with OpenInference semantics."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE or not self._tracer:
            yield None
            return

        openinference_attrs = {
            OPENINFERENCE_SPAN_KIND: OPENINFERENCE_SPAN_KIND_RETRIEVER,
            "retriever.name": retriever_name,
            "agent.step.name": retriever_name,
            "agent.step.type": "retriever",
        }
        if agent_name:
            openinference_attrs["agent.name"] = agent_name

        agent_metadata = get_agent_monitoring_context()
        if agent_metadata is not None:
            openinference_attrs.update(self.build_agent_run_attributes(
                agent_metadata,
                span_kind=OPENINFERENCE_SPAN_KIND_RETRIEVER,
                include_query=False,
            ))
            openinference_attrs.update({
                OPENINFERENCE_SPAN_KIND: OPENINFERENCE_SPAN_KIND_RETRIEVER,
                "retriever.name": retriever_name,
                "agent.step.name": retriever_name,
                "agent.step.type": "retriever",
            })
            if agent_name:
                openinference_attrs["agent.name"] = agent_name

        if retrieval_input is not None:
            retrieval_input_json = self._trace_payload_preview(retrieval_input)
            openinference_attrs["retriever.input"] = retrieval_input_json
            openinference_attrs[OPENINFERENCE_INPUT_VALUE] = retrieval_input_json
            openinference_attrs.update(
                self._trace_payload_attributes("retriever.input", retrieval_input)
            )
            query = retrieval_input.get("query") if isinstance(
                retrieval_input, dict) else None
            if query is not None:
                openinference_attrs["retrieval.query"] = str(query)

        openinference_attrs.update(attributes)

        span_name = f"agent.retriever.{retriever_name}"
        with self._tracer.start_as_current_span(
            span_name,
            attributes=openinference_attrs,
        ) as span:
            start_time = time.time()
            success = True
            try:
                yield span
            except Exception as e:
                success = False
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                span.set_attribute("retriever.success", False)
                if self._agent_error_count:
                    self._agent_error_count.add(
                        1,
                        {
                            "agent.name": agent_name or "",
                            "error.type": type(e).__name__,
                            "retriever.name": retriever_name,
                        },
                    )
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                span.set_attribute("retriever.duration_ms", duration_ms)
                if success:
                    span.set_attribute("retriever.success", True)
                if self._agent_step_count:
                    self._agent_step_count.add(
                        1,
                        {
                            "agent.name": agent_name or "",
                            "agent.step.type": "retriever",
                            "retriever.name": retriever_name,
                        },
                    )

    def set_tool_output(self, output: Any) -> None:
        """
        Set the output of a tool call on the current span.
        Call this within a trace_tool_call context manager.

        Args:
            output: Tool output (will be JSON serialized)
        """
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        span = trace.get_current_span()
        if span and span.is_recording():
            output_value = self._trace_payload_preview(output)
            attrs = {
                "agent.tool.output": output_value,
                OPENINFERENCE_OUTPUT_VALUE: output_value,
                "agent.tool.success": True,
            }
            attrs.update(self._trace_payload_attributes("agent.tool.output", output))
            span.set_attributes(attrs)

    def set_retriever_output(self, output: Any) -> None:
        """Set the output of a retriever call on the current span."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        span = trace.get_current_span()
        if span and span.is_recording():
            output_value = self._trace_payload_preview(output)
            attrs = {
                "retriever.output": output_value,
                OPENINFERENCE_OUTPUT_VALUE: output_value,
                "retriever.success": True,
            }
            attrs.update(self._trace_payload_attributes("retriever.output", output))
            attrs.update(self._retrieval_result_attributes(output))
            span.set_attributes(attrs)

    def get_current_span(self) -> Optional[Any]:
        """Get the current active span."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return None
        return trace.get_current_span()

    def add_span_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        """Add an event to the current span."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        span = trace.get_current_span()
        if span:
            span.add_event(name, attributes or {})

    def set_span_attributes(self, **attributes: Any) -> None:
        """Set attributes on the current span."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        span = trace.get_current_span()
        if span:
            span.set_attributes(attributes)

    def create_token_tracker(self, model_name: str, span: Optional[Any] = None) -> 'LLMTokenTracker':
        """Create a token tracker for LLM calls."""
        return LLMTokenTracker(self, model_name, span)

    def record_llm_metrics(self, metric_type: str, value: float, attributes: Dict[str, Any]) -> None:
        """
        Record LLM-specific metrics using OpenInference semantic conventions.
        """
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        # Ensure attributes use OpenInference naming
        if "model" in attributes and "llm.model_name" not in attributes:
            attributes["llm.model_name"] = attributes["model"]

        if metric_type == "ttft" and self._llm_ttft_duration:
            self._llm_ttft_duration.record(value, attributes)
        elif metric_type == "token_rate" and self._llm_token_generation_rate:
            self._llm_token_generation_rate.record(value, attributes)
        elif metric_type == "tokens_prompt" and self._llm_token_count_prompt:
            self._llm_token_count_prompt.add(value, attributes)
        elif metric_type == "tokens_completion" and self._llm_token_count_completion:
            self._llm_token_count_completion.add(value, attributes)

    def monitor_endpoint(
        self,
        operation_name: Optional[str] = None,
        include_params: bool = True,
        exclude_params: Optional[list] = None
    ) -> Callable[[F], F]:
        """
        Decorator to add monitoring to any endpoint or service function.
        Monitoring is automatically enabled/disabled based on configuration.
        """
        def decorator(func: F) -> F:
            op_name = operation_name or f"{func.__module__}.{func.__name__}"
            exclude_set = set(exclude_params or [])

            def prepare_span(span, kwargs: Dict[str, Any], span_kind: str) -> None:
                if span and include_params:
                    safe_params = {
                        k: v for k, v in kwargs.items()
                        if k not in exclude_set and isinstance(v, (str, int, float, bool))
                    }
                    if safe_params:
                        self.set_span_attributes(**{f"param.{k}": v for k, v in safe_params.items()})
                self.apply_openinference_context_attributes(span_kind)
                self.add_span_event(f"{op_name}.started")

            def complete_span(start_time: float) -> None:
                duration = time.time() - start_time
                self.add_span_event(f"{op_name}.completed", {"duration": duration})

            def fail_span(start_time: float, error: Exception) -> None:
                duration = time.time() - start_time
                self.add_span_event(f"{op_name}.error", {
                    "error.type": type(error).__name__,
                    "error.message": str(error),
                    "duration": duration
                })

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Always execute monitoring logic - internal methods handle enabled state
                span_kind = self._infer_openinference_span_kind(op_name)
                with self.trace_operation(op_name, span_kind) as span:
                    prepare_span(span, kwargs, span_kind)
                    start_time = time.time()

                    try:
                        result = await func(*args, **kwargs)
                        complete_span(start_time)
                        return result
                    except Exception as e:
                        fail_span(start_time, e)
                        raise

            @functools.wraps(func)
            async def async_generator_wrapper(*args, **kwargs):
                # Keep the span open while the streaming response is consumed.
                span_kind = self._infer_openinference_span_kind(op_name)
                with self.trace_operation(op_name, span_kind) as span:
                    prepare_span(span, kwargs, span_kind)
                    start_time = time.time()

                    try:
                        async for item in func(*args, **kwargs):
                            yield item
                        complete_span(start_time)
                    except Exception as e:
                        fail_span(start_time, e)
                        raise

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Always execute monitoring logic - internal methods handle enabled state
                span_kind = self._infer_openinference_span_kind(op_name)
                with self.trace_operation(op_name, span_kind) as span:
                    prepare_span(span, kwargs, span_kind)
                    start_time = time.time()

                    try:
                        result = func(*args, **kwargs)
                        complete_span(start_time)
                        return result
                    except Exception as e:
                        fail_span(start_time, e)
                        raise

            @functools.wraps(func)
            def generator_wrapper(*args, **kwargs):
                span_kind = self._infer_openinference_span_kind(op_name)
                with self.trace_operation(op_name, span_kind) as span:
                    prepare_span(span, kwargs, span_kind)
                    start_time = time.time()

                    try:
                        for item in func(*args, **kwargs):
                            yield item
                        complete_span(start_time)
                    except Exception as e:
                        fail_span(start_time, e)
                        raise

            # Return appropriate wrapper based on function type
            if inspect.isasyncgenfunction(func):
                return cast(F, async_generator_wrapper)
            if inspect.iscoroutinefunction(func):
                return cast(F, async_wrapper)
            if inspect.isgeneratorfunction(func):
                return cast(F, generator_wrapper)
            return cast(F, sync_wrapper)

        return decorator

    def monitor_llm_call(self, model_name: str, operation: str = "llm_completion"):
        """
        Specialized decorator for LLM calls with token tracking.
        Monitoring is automatically enabled/disabled based on configuration.
        Uses OpenInference semantic conventions for attribute naming.
        """
        def decorator(func: F) -> F:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                self_ref = args[0] if args else None
                actual_model_name = getattr(
                    self_ref, "model_id", None) or model_name
                detected_type = _detect_model_type(
                    self_ref) if self_ref else "llm"
                with self.trace_llm_request(operation, model_name, **kwargs) as span:
                    token_tracker = self.create_token_tracker(model_name, span)
                    token_tracker._display_name = getattr(
                        self_ref, "display_name", None)
                    self.add_span_event("llm_call_started")

                    try:
                        result = await func(*args, **kwargs, _token_tracker=token_tracker)
                        self.add_span_event("llm_call_completed")
                        _enqueue_monitoring_record(
                            token_tracker, actual_model_name, operation, kwargs, model_type=detected_type
                        )
                        return result
                    except Exception as e:
                        self.add_span_event("llm_call_error", {
                            "error.type": type(e).__name__,
                            "error.message": str(e)
                        })
                        _enqueue_monitoring_record(
                            token_tracker, actual_model_name, operation, kwargs, error=e, model_type=detected_type
                        )
                        raise

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                self_ref = args[0] if args else None
                actual_model_name = getattr(
                    self_ref, "model_id", None) or model_name
                detected_type = _detect_model_type(
                    self_ref) if self_ref else "llm"
                with self.trace_llm_request(operation, model_name, **kwargs) as span:
                    token_tracker = self.create_token_tracker(model_name, span)
                    token_tracker._display_name = getattr(
                        self_ref, "display_name", None)
                    self.add_span_event("llm_call_started")

                    try:
                        result = func(*args, **kwargs,
                                      _token_tracker=token_tracker)
                        self.add_span_event("llm_call_completed")
                        _enqueue_monitoring_record(
                            token_tracker, actual_model_name, operation, kwargs, model_type=detected_type
                        )
                        return result
                    except Exception as e:
                        self.add_span_event("llm_call_error", {
                            "error.type": type(e).__name__,
                            "error.message": str(e)
                        })
                        _enqueue_monitoring_record(
                            token_tracker, actual_model_name, operation, kwargs, error=e, model_type=detected_type
                        )
                        raise

            if inspect.iscoroutinefunction(func):
                return cast(F, async_wrapper)
            else:
                return cast(F, sync_wrapper)

        return decorator

class LLMTokenTracker:
    """
    Tracks token generation metrics for streaming LLM responses.
    Uses OpenInference semantic conventions for attribute naming.
    """

    def __init__(self, manager: MonitoringManager, model_name: str, span: Optional[Any] = None):
        self.manager = manager
        self.model_name = model_name
        self.span = span
        self.start_time = time.time()
        self.first_token_time: Optional[float] = None
        self.token_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        # Snapshot context at creation time (caller's async scope) so that
        # downstream code running in a different thread can still access it.
        self._context_snapshot: Dict[str, Any] = get_monitoring_context()

    def record_first_token(self) -> None:
        """Record the time when first token is received."""
        if not getattr(self.manager, "is_enabled", False):
            return

        if self.first_token_time is None:
            self.first_token_time = time.time()
            ttft = self.first_token_time - self.start_time

            if self.span:
                self.span.add_event("first_token_received",
                                    {"llm.time_to_first_token": ttft})

            self.manager.record_llm_metrics(
                "ttft", ttft, {"llm.model_name": self.model_name})

    def record_token(self, token: str) -> None:
        """Record a new token generated."""
        if not getattr(self.manager, "is_enabled", False):
            return

        if self.first_token_time is None:
            self.record_first_token()

        self.token_count += 1

        if self.span:
            self.span.add_event("token_generated", {
                "token_count": self.token_count,
                "token_length": len(token)
            })

    def record_completion(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """Record completion metrics using OpenInference semantic conventions."""
        if not self.manager.is_enabled:
            return

        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        total_duration = time.time() - self.start_time
        generation_rate = 0.0

        # Calculate token generation rate (tokens per second)
        generation_rate = 0
        if total_duration > 0 and self.token_count > 0:
            generation_rate = self.token_count / total_duration
            self.manager.record_llm_metrics("token_rate", generation_rate, {
                "llm.model_name": self.model_name})

        # Record token counts using OpenInference naming
        self.manager.record_llm_metrics("tokens_prompt", input_tokens, {
            "llm.model_name": self.model_name})
        self.manager.record_llm_metrics("tokens_completion", output_tokens, {
            "llm.model_name": self.model_name})

        # Add span attributes using OpenInference naming
        if self.span:
            usage_details = {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            }
            self.span.set_attributes({
                "llm.token_count.prompt": input_tokens,
                "llm.token_count.completion": output_tokens,
                "llm.token_count.total": input_tokens + output_tokens,
                "llm.usage_details": json.dumps(
                    usage_details, ensure_ascii=False),
                "llm.generation_rate": generation_rate,
                "llm.duration.total": total_duration,
                "llm.time_to_first_token": self.first_token_time - self.start_time if self.first_token_time else 0
            })


# ---------------------------------------------------------------------------
#  New standalone utilities and context/models from the djb branch
# ---------------------------------------------------------------------------

def _detect_model_type(model_instance: Any) -> str:
    cls_name = type(model_instance).__name__.lower()
    if "vlm" in cls_name or "vision" in cls_name:
        return "vlm"
    if "embed" in cls_name:
        return "embedding"
    return "llm"


def record_model_call(
    model_type: str,
    model_name: str,
    display_name: Optional[str] = None,
) -> 'RecordModelCallContext':
    """Create a context manager that times a non-LLM model API call and enqueues a monitoring record.

    Usage::

        with record_model_call("embedding", "bge-large-zh", display_name="bge-large-zh") as ctx:
            result = embedding_api_call(...)
        # ctx.error is set if the call raised
    """
    return RecordModelCallContext(model_type, model_name, display_name)


class RecordModelCallContext:
    """Context manager for recording non-LLM model API call metrics."""

    def __init__(self, model_type: str, model_name: str, display_name: Optional[str] = None):
        self.model_type = model_type
        self.model_name = model_name
        self.display_name = display_name
        self.error: Optional[Exception] = None
        self._start_time = 0.0

    def __enter__(self):
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_val is not None:
                self.error = exc_val

            request_duration_ms = int((time.time() - self._start_time) * 1000)

            record = {
                "model_name": self.model_name,
                "operation": f"{self.model_type}_call",
                "request_duration_ms": request_duration_ms,
                "ttft_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "generation_rate": 0.0,
                "is_success": exc_val is None,
                "is_error": exc_val is not None,
                "is_streaming": False,
                "model_type": self.model_type,
            }

            if exc_val is not None:
                record["error_type"] = type(exc_val).__name__
                record["error_message"] = str(exc_val)[:2000]

            ctx = get_monitoring_context()
            snapshot = ctx or {}
            tenant_id = snapshot.get("tenant_id")

            if not tenant_id:
                logger.debug(
                    "Monitoring: skipping %s record for %s - no tenant_id in context",
                    self.model_type,
                    self.model_name,
                )
                return False

            record["tenant_id"] = tenant_id
            user_id = snapshot.get("user_id")
            agent_id = snapshot.get("agent_id")
            conversation_id = snapshot.get("conversation_id")

            if user_id:
                record["user_id"] = user_id
            if agent_id is not None:
                record["agent_id"] = agent_id
            if conversation_id is not None:
                record["conversation_id"] = conversation_id
            if self.display_name:
                record["display_name"] = self.display_name

            buffer = get_monitoring_buffer()
            if buffer and buffer.is_enabled:
                buffer.add_record(record)
        except Exception:
            pass


class _MonitoredStreamIterator:

    def __init__(self, stream, start_time: float, model_name: str, model_type: str):
        self._stream = stream
        self._start_time = start_time
        self._model_name = model_name
        self._model_type = model_type
        self._error: Optional[Exception] = None
        self._first_chunk_time: Optional[float] = None
        self._input_tokens: int = 0
        self._output_tokens: int = 0

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._stream)
            if self._first_chunk_time is None:
                self._first_chunk_time = time.time()
            if hasattr(chunk, "usage") and chunk.usage is not None:
                self._input_tokens = getattr(
                    chunk.usage, "prompt_tokens", 0) or 0
                self._output_tokens = getattr(
                    chunk.usage, "completion_tokens", 0) or 0
            return chunk
        except StopIteration:
            self._finalize()
            raise
        except Exception as exc:
            self._error = exc
            self._finalize()
            raise

    def _finalize(self):
        try:
            request_duration_ms = int((time.time() - self._start_time) * 1000)

            if self._first_chunk_time is not None:
                ttft_ms = int(
                    (self._first_chunk_time - self._start_time) * 1000)
            else:
                ttft_ms = 0

            duration_seconds = request_duration_ms / 1000.0
            if duration_seconds > 0 and self._output_tokens > 0:
                generation_rate = round(
                    self._output_tokens / duration_seconds, 2)
            else:
                generation_rate = 0.0

            _enqueue_client_monitoring_record(
                model_name=self._model_name,
                model_type=self._model_type,
                request_duration_ms=request_duration_ms,
                ttft_ms=ttft_ms,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                total_tokens=self._input_tokens + self._output_tokens,
                generation_rate=generation_rate,
                is_streaming=True,
                error=self._error,
            )
        except Exception:
            pass


class _MonitoredChatCompletions:
    """Wraps openai.ChatCompletions to intercept create() calls for monitoring."""

    def __init__(self, original, model_name: str, model_type: str):
        self._original = original
        self._model_name = model_name
        self._model_type = model_type

    def create(self, **kwargs):
        stream = kwargs.get("stream", False)
        start_time = time.time()
        try:
            response = self._original.create(**kwargs)
        except Exception as exc:
            self._record_non_streaming(start_time, error=exc)
            raise

        if stream:
            return _MonitoredStreamIterator(response, start_time, self._model_name, self._model_type)
        else:
            self._record_non_streaming(start_time, response=response)
            return response

    def _record_non_streaming(self, start_time: float, response=None, error: Optional[Exception] = None):
        try:
            request_duration_ms = int((time.time() - start_time) * 1000)
            input_tokens = 0
            output_tokens = 0
            if response is not None and hasattr(response, "usage") and response.usage:
                input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(
                    response.usage, "completion_tokens", 0) or 0

            _enqueue_client_monitoring_record(
                model_name=self._model_name,
                model_type=self._model_type,
                request_duration_ms=request_duration_ms,
                ttft_ms=0,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                generation_rate=0.0,
                is_streaming=False,
                error=error,
            )
        except Exception as _e:
            logger.warning(
                "Monitoring: failed to record non-streaming call for %s: %s",
                self._model_name, _e,
            )

    def __getattr__(self, name):
        return getattr(self._original, name)


class _MonitoredChat:
    """Proxies chat.completions to return the monitored wrapper."""

    def __init__(self, original_chat, model_name: str, model_type: str):
        self._original_chat = original_chat
        self._model_name = model_name
        self._model_type = model_type
        self._completions = _MonitoredChatCompletions(
            original_chat.completions, model_name, model_type
        )

    @property
    def completions(self):
        return self._completions

    def __getattr__(self, name):
        return getattr(self._original_chat, name)


class _MonitoredClient:
    """Wraps an openai.OpenAI client to inject monitoring at the chat.completions layer."""

    def __init__(self, original_client, model_name: str, model_type: str):
        self._original_client = original_client
        self._model_name = model_name
        self._model_type = model_type
        self._chat = _MonitoredChat(
            original_client.chat, model_name, model_type)

    @property
    def chat(self):
        return self._chat

    def __getattr__(self, name):
        return getattr(self._original_client, name)


def _enqueue_client_monitoring_record(
    model_name: str,
    model_type: str,
    request_duration_ms: int,
    ttft_ms: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    generation_rate: float,
    is_streaming: bool,
    error: Optional[Exception] = None,
) -> None:
    """Enqueue a monitoring record from the client-level interceptor."""
    try:
        buffer = get_monitoring_buffer()
        if buffer is None or not buffer.is_enabled:
            return

        ctx = get_monitoring_context()
        tenant_id = ctx.get("tenant_id")
        if not tenant_id:
            logger.debug(
                "Monitoring: skipping client-level record for %s - no tenant_id",
                model_name,
            )
            return

        operation = _monitoring_operation.get()
        record = {
            "model_name": model_name,
            "operation": operation,
            "request_duration_ms": request_duration_ms,
            "ttft_ms": ttft_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "generation_rate": round(generation_rate, 2),
            "is_success": error is None,
            "is_error": error is not None,
            "is_streaming": is_streaming,
            "model_type": model_type,
        }

        if error is not None:
            record["error_type"] = type(error).__name__
            record["error_message"] = str(error)[:2000]

        record["tenant_id"] = tenant_id
        user_id = ctx.get("user_id")
        agent_id = ctx.get("agent_id")
        conversation_id = ctx.get("conversation_id")
        if user_id:
            record["user_id"] = user_id
        if agent_id is not None:
            record["agent_id"] = agent_id
        if conversation_id is not None:
            record["conversation_id"] = conversation_id

        display_name = _monitoring_display_name.get()
        if display_name:
            record["display_name"] = display_name

        buffer.add_record(record)
    except Exception:
        pass


def _extract_tracker_metrics(tracker):
    """Extract timing and token metrics from an LLMTokenTracker."""
    request_duration_ms = 0
    ttft_ms = 0
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    generation_rate = 0.0

    if tracker is not None:
        request_duration_ms = int(
            (time.time() - tracker.start_time) * 1000)
        if tracker.first_token_time is not None:
            ttft_ms = int((tracker.first_token_time -
                          tracker.start_time) * 1000)
        input_tokens = tracker.input_tokens
        output_tokens = tracker.output_tokens
        total_tokens = input_tokens + output_tokens
        if request_duration_ms > 0 and output_tokens > 0:
            generation_rate = output_tokens / (request_duration_ms / 1000.0)

    return request_duration_ms, ttft_ms, input_tokens, output_tokens, total_tokens, generation_rate


def _build_monitoring_record(tracker, model_name, operation, error, model_type,
                             request_duration_ms, ttft_ms, input_tokens,
                             output_tokens, total_tokens, generation_rate):
    """Build the base monitoring record dict."""
    record = {
        "model_name": model_name,
        "operation": operation,
        "request_duration_ms": request_duration_ms,
        "ttft_ms": ttft_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "generation_rate": round(generation_rate, 2),
        "is_success": error is None,
        "is_error": error is not None,
        "is_streaming": tracker.token_count > 0 if tracker else False,
        "model_type": model_type,
    }
    if error is not None:
        record["error_type"] = type(error).__name__
        record["error_message"] = str(error)[:2000]
    return record


def _resolve_context_field(snapshot, ctx, kwargs, field_name):
    """Resolve a context field with priority: snapshot > live context > kwargs."""
    return snapshot.get(field_name) or ctx.get(field_name) or kwargs.get(field_name)


def _enrich_record_with_context(record, tracker, kwargs):
    """Fill tenant/user/agent/conversation/display_name from context sources."""
    snapshot = getattr(tracker, "_context_snapshot", {}) or {}
    ctx = get_monitoring_context()

    tenant_id = _resolve_context_field(snapshot, ctx, kwargs, "tenant_id")
    if not tenant_id:
        return None

    record["tenant_id"] = tenant_id

    user_id = _resolve_context_field(snapshot, ctx, kwargs, "user_id")
    agent_id = _resolve_context_field(snapshot, ctx, kwargs, "agent_id")
    conversation_id = _resolve_context_field(
        snapshot, ctx, kwargs, "conversation_id")

    if user_id:
        record["user_id"] = user_id
    if agent_id is not None:
        record["agent_id"] = agent_id
    if conversation_id is not None:
        record["conversation_id"] = conversation_id

    display_name = getattr(tracker, "_display_name", None)
    if display_name:
        record["display_name"] = display_name

    return tenant_id


def _enqueue_monitoring_record(
    tracker: Optional[LLMTokenTracker],
    model_name: str,
    operation: str,
    kwargs: dict,
    error: Optional[Exception] = None,
    model_type: str = "llm",
) -> None:
    try:
        buffer = get_monitoring_buffer()
        if buffer is None or not buffer.is_enabled:
            return

        metrics = _extract_tracker_metrics(tracker)
        record = _build_monitoring_record(
            tracker, model_name, operation, error, model_type, *metrics)

        result = _enrich_record_with_context(record, tracker, kwargs)
        if result is None:
            logger.debug(
                "Monitoring: skipping %s record for %s - no tenant_id in context",
                model_type,
                model_name,
            )
            return

        buffer.add_record(record)
    except Exception:
        pass


class MonitoringRecordBuffer:
    """Thread-safe buffer that batches LLM monitoring records and flushes to PostgreSQL.

    Uses collections.deque for non-blocking, lock-free appends. A daemon background
    thread periodically flushes records to the database in batches.

    Degradation: after 3 consecutive DB write failures, stops writing and logs only.
    Automatically retries after 30 seconds.
    """

    def __init__(self):
        self._buffer: deque = deque(maxlen=5000)
        self._enabled: bool = os.getenv(
            "ENABLE_MODEL_MONITORING", "true").lower() == "true"
        self._batch_size: int = int(
            os.getenv("MODEL_MONITORING_BATCH_SIZE", "100"))
        self._flush_interval: int = int(
            os.getenv("MODEL_MONITORING_FLUSH_INTERVAL_SECONDS", "30"))
        self._consecutive_failures: int = 0
        self._max_failures: int = 3
        self._degraded_until: float = 0.0
        self._last_flush_time: float = time.time()
        self._running: bool = False
        self._flush_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        if self._enabled:
            self._start_flush_thread()

    def _start_flush_thread(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._flush_thread = threading.Thread(
                target=self._flush_loop,
                name="monitoring-buffer-flush",
                daemon=True,
            )
            self._flush_thread.start()
            logger.info("Monitoring buffer flush thread started")

    def add_record(self, record: dict) -> None:
        if not self._enabled:
            return
        self._buffer.append(record)

    def _flush_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                buffer_size = len(self._buffer)
                should_flush = buffer_size >= self._batch_size or (
                    buffer_size > 0 and (
                        now - self._last_flush_time) >= self._flush_interval
                )
                if should_flush:
                    self._flush_to_db()
                    self._last_flush_time = now
            except Exception as e:
                logger.error(f"Error in monitoring flush loop: {e}")

            for _ in range(10):
                if not self._running:
                    return
                time.sleep(self._flush_interval / 10)

    def _flush_to_db(self) -> None:
        now = time.time()

        if self._consecutive_failures >= self._max_failures:
            if now < self._degraded_until:
                return
            logger.info(
                "Monitoring buffer: retrying after degradation cooldown")

        batch: List[dict] = []
        while len(batch) < self._batch_size and self._buffer:
            batch.append(self._buffer.popleft())

        if not batch:
            return

        try:
            self._write_batch(batch)
            self._consecutive_failures = 0
            logger.debug(
                f"Monitoring buffer: flushed {len(batch)} records to DB")
        except Exception as e:
            self._consecutive_failures += 1
            logger.error(
                f"Monitoring buffer: DB write failed (attempt {self._consecutive_failures}): {e}")
            for record in reversed(batch):
                self._buffer.appendleft(record)

            if self._consecutive_failures >= self._max_failures:
                self._degraded_until = now + 30
                logger.warning(
                    f"Monitoring buffer: degraded mode for 30s after {self._max_failures} failures")

    def _write_batch(self, batch: List[dict]) -> None:
        try:
            import sys
            import os

            backend_path = os.path.join(os.getcwd(), "backend")
            if os.path.exists(backend_path) and backend_path not in sys.path:
                sys.path.insert(0, backend_path)

            from database.client import get_monitoring_db_session
            from database.db_models import ModelMonitoringRecord
        except ImportError as e:
            logger.debug(
                f"Monitoring buffer: backend database not available: {e}")
            raise RuntimeError("Backend database module not available")

        # Write records individually so that one bad record (e.g. missing
        # tenant_id) does not abort the entire batch.
        succeeded = 0
        failed = 0
        for record in batch:
            try:
                with get_monitoring_db_session() as session:
                    row = ModelMonitoringRecord(**record)
                    session.add(row)
                    session.flush()
                succeeded += 1
            except Exception as rec_err:
                failed += 1
                logger.warning(
                    "Monitoring buffer: skipping record due to error: %s | record=%s",
                    rec_err,
                    {k: v for k, v in record.items() if k in (
                        "model_name", "tenant_id", "model_type")},
                )

        if failed > 0:
            logger.warning(
                "Monitoring buffer: batch write completed with %d succeeded, %d failed",
                succeeded,
                failed,
            )

    def stop(self) -> None:
        self._running = False
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=5)
        logger.info("Monitoring buffer flush thread stopped")

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def is_enabled(self) -> bool:
        return self._enabled


_monitoring_buffer: Optional[MonitoringRecordBuffer] = None


def get_monitoring_buffer() -> Optional[MonitoringRecordBuffer]:
    global _monitoring_buffer
    if _monitoring_buffer is None:
        _monitoring_buffer = MonitoringRecordBuffer()
    return _monitoring_buffer


# Global singleton instance
_monitoring_manager = MonitoringManager()


# ==========================================================================
# Public API Functions - Singleton Access
# ==========================================================================

def get_monitoring_manager() -> MonitoringManager:
    """Get the global monitoring manager singleton instance.

    This is the primary interface for all monitoring operations.
    Use this function to access the monitoring manager and its methods.

    Example:
        monitor = get_monitoring_manager()
        monitor.configure(config)

        @monitor.monitor_endpoint("my_service.my_function")
        async def my_function():
            return {"status": "ok"}
    """
    return _monitoring_manager


# Export monitoring utilities
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
    '_detect_model_type',
    '_MonitoredClient',
    '_MonitoredChatCompletions',
    '_MonitoredStreamIterator',
    '_enqueue_client_monitoring_record',
]
