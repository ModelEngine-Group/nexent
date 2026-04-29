"""
Nexent LLM Performance Monitoring System

A comprehensive monitoring solution specifically designed for LLM applications.
Provides distributed tracing, token-level performance monitoring, and seamless
integration with OpenTelemetry OTLP protocol for AI observability platforms
like Arize Phoenix, Langfuse, and others.

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
import time
import functools
import json
import inspect
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, Optional, Callable, TypeVar, cast, Iterator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])

DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"
TRACE_PATH = "/v1/traces"
METRIC_PATH = "/v1/metrics"
SUPPORTED_PROVIDERS = {"otlp", "phoenix", "langfuse", "jaeger", "custom"}


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


def _compact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values from a configuration dictionary."""
    return {key: value for key, value in data.items() if value not in (None, "")}


def _load_mapping_file(path: str) -> Dict[str, Any]:
    """Load a JSON or YAML mapping from disk."""
    if not path:
        return {}

    config_path = Path(path)
    if not config_path.exists():
        logger.warning(f"Monitoring config file does not exist: {path}")
        return {}

    raw_text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        loaded = json.loads(raw_text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required to read YAML monitoring config files."
            ) from exc
        loaded = yaml.safe_load(raw_text)

    if not loaded:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("Monitoring config file must contain a mapping object.")
    return loaded


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


def _merge_headers(*header_sets: Any) -> Dict[str, str]:
    """Merge multiple header sources, with later sources taking precedence."""
    merged: Dict[str, str] = {}
    for headers in header_sets:
        merged.update(_parse_headers(headers))
    return merged


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
    to any OpenTelemetry-compatible backend (Arize Phoenix, Langfuse, etc).
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
    use_platform_sdk: bool = False
    project_name: Optional[str] = None
    telemetry_sample_rate: float = 1.0
    llm_slow_request_threshold_seconds: float = 5.0
    llm_slow_token_rate_threshold: float = 10.0

    @classmethod
    def from_file(cls, config_file: str, overrides: Optional[Dict[str, Any]] = None) -> "MonitoringConfig":
        """
        Build monitoring config from JSON/YAML and optional overrides.

        Supported shape:

        monitoring:
          enable_telemetry: true
          service_name: nexent-backend
          exporter:
            provider: langfuse
            protocol: http
            endpoint: https://cloud.langfuse.com/api/public/otel
            traces_endpoint: https://cloud.langfuse.com/api/public/otel/v1/traces
            headers:
              Authorization: Basic xxx
            export_metrics: false
        """
        loaded = _load_mapping_file(config_file)
        data = loaded.get("monitoring", loaded)
        if not isinstance(data, dict):
            raise ValueError("The monitoring config section must be a mapping object.")

        exporter = data.get("exporter", {})
        if exporter is None:
            exporter = {}
        if not isinstance(exporter, dict):
            raise ValueError("The monitoring exporter section must be a mapping object.")

        headers = _merge_headers(data.get("otlp_headers"), data.get("headers"), exporter.get("headers"))
        config_data = _compact_dict({
            "enable_telemetry": data.get("enable_telemetry"),
            "service_name": data.get("service_name"),
            "provider": exporter.get("provider", data.get("provider")),
            "otlp_endpoint": exporter.get("endpoint", data.get("otlp_endpoint")),
            "otlp_traces_endpoint": exporter.get("traces_endpoint", data.get("otlp_traces_endpoint")),
            "otlp_metrics_endpoint": exporter.get("metrics_endpoint", data.get("otlp_metrics_endpoint")),
            "otlp_protocol": exporter.get("protocol", data.get("otlp_protocol")),
            "otlp_headers": headers,
            "export_traces": exporter.get("export_traces", data.get("export_traces")),
            "export_metrics": exporter.get("export_metrics", data.get("export_metrics")),
            "use_platform_sdk": exporter.get("use_platform_sdk", data.get("use_platform_sdk")),
            "project_name": exporter.get("project_name", data.get("project_name")),
            "telemetry_sample_rate": data.get("telemetry_sample_rate"),
            "llm_slow_request_threshold_seconds": data.get("llm_slow_request_threshold_seconds"),
            "llm_slow_token_rate_threshold": data.get("llm_slow_token_rate_threshold"),
        })

        if overrides:
            merged_headers = _merge_headers(config_data.get("otlp_headers"), overrides.get("otlp_headers"))
            config_data.update(_compact_dict(overrides))
            if merged_headers:
                config_data["otlp_headers"] = merged_headers

        return cls(**config_data)

    def __post_init__(self):
        """Validate configuration and adjust based on OpenTelemetry availability."""
        self.provider = (self.provider or "otlp").strip().lower()
        if self.provider not in SUPPORTED_PROVIDERS:
            logger.warning(
                f"Unknown monitoring provider '{self.provider}'. Using 'custom'."
            )
            self.provider = "custom"

        self.enable_telemetry = _as_bool(self.enable_telemetry)
        self.export_traces = _as_bool(self.export_traces, True)
        self.export_metrics = _as_bool(self.export_metrics, True)
        self.use_platform_sdk = _as_bool(self.use_platform_sdk)
        self.telemetry_sample_rate = _as_float(self.telemetry_sample_rate, 1.0)
        self.llm_slow_request_threshold_seconds = _as_float(
            self.llm_slow_request_threshold_seconds, 5.0)
        self.llm_slow_token_rate_threshold = _as_float(
            self.llm_slow_token_rate_threshold, 10.0)
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

        if self.provider in {"phoenix", "langfuse"} and self.otlp_protocol == "grpc":
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
        self._agent_execution_duration: Optional[Any] = None
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
            # Setup resource with service name
            resource = Resource.create({
                "service.name": self._config.service_name,
                "service.version": "1.0.0",
                "service.instance.id": "nexent-instance-1",
                "telemetry.provider": self._config.provider,
            })

            platform_tracer_provider = None
            if self._config.use_platform_sdk and self._config.export_traces:
                platform_tracer_provider = self._initialize_platform_sdk()

            # Initialize TracerProvider with OTLP exporter
            self._tracer_provider = platform_tracer_provider or TracerProvider(resource=resource)
            if platform_tracer_provider is None:
                trace.set_tracer_provider(self._tracer_provider)

            if self._config.export_traces and platform_tracer_provider is None:
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
            elif self._config.export_traces:
                logger.info(
                    "Using platform SDK tracer provider; skipping explicit OTLP span exporter"
                )

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

            self._agent_execution_duration = self._meter.create_histogram(
                name="agent.execution.duration",
                description="Duration of agent execution in seconds",
                unit="s"
            )

            self._agent_error_count = self._meter.create_counter(
                name="agent.error.count",
                description="Number of agent execution errors",
                unit="errors"
            )

            # Auto-instrument other libraries
            RequestsInstrumentor().instrument()

            logger.info(
                f"OTLP telemetry initialized successfully for service: {self._config.service_name}, "
                f"provider: {self._config.provider}, trace_endpoint: {self._config.get_trace_endpoint()}, "
                f"metric_endpoint: {self._config.get_metric_endpoint()}, protocol: {self._config.otlp_protocol}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize OTLP telemetry: {str(e)}")
            # Do not raise - allow application to continue without monitoring

    def _initialize_platform_sdk(self) -> Optional[Any]:
        """Optionally initialize provider SDKs that wrap OpenTelemetry."""
        if not self._config:
            return None

        if self._config.provider == "phoenix":
            try:
                from phoenix.otel import register

                kwargs = {
                    "project_name": self._config.project_name or self._config.service_name,
                    "endpoint": self._config.otlp_endpoint,
                    "protocol": "http/protobuf" if self._config.otlp_protocol == "http" else "grpc",
                    "headers": self._config.otlp_headers,
                    "auto_instrument": False,
                }
                tracer_provider = register(**kwargs)
                logger.info("Phoenix SDK initialized for OpenTelemetry tracing")
                return tracer_provider
            except Exception as exc:
                logger.warning(f"Phoenix SDK initialization skipped: {exc}")
        elif self._config.provider == "langfuse":
            try:
                from langfuse import get_client

                client = get_client()
                if hasattr(client, "auth_check"):
                    client.auth_check()
                logger.info("Langfuse SDK client initialized")
            except Exception as exc:
                logger.warning(f"Langfuse SDK initialization skipped: {exc}")
        return None

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
            if self.is_enabled and app and OPENTELEMETRY_AVAILABLE:
                FastAPIInstrumentor.instrument_app(app)
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
            "llm.model_name": model_name,
            "llm.operation.name": operation_name,
        }
        # Add user-provided attributes
        openinference_attrs.update(attributes)

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

    @contextmanager
    def trace_agent_step(
        self,
        step_name: str,
        agent_name: str,
        step_type: str,
        **attributes: Any
    ) -> Iterator[Optional[Any]]:
        """
        Context manager for tracing Agent execution steps.
        Uses OpenInference semantic conventions for attribute naming.

        Args:
            step_name: Name of the step (e.g., "web_search", "reasoning_step_1")
            agent_name: Name of the agent
            step_type: Type of step - "tool_call", "reasoning", or "action_selection"
            **attributes: Additional attributes to add to the span
        """
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE or not self._tracer:
            yield None
            return

        # OpenInference semantic attributes for agent
        openinference_attrs = {
            "agent.name": agent_name,
            "agent.step.name": step_name,
            "agent.step.type": step_type,
        }
        openinference_attrs.update(attributes)

        span_name = f"agent.{step_name}"

        with self._tracer.start_as_current_span(
            span_name,
            attributes=openinference_attrs
        ) as span:
            start_time = time.time()
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                if self._agent_error_count:
                    self._agent_error_count.add(
                        1, {"agent.name": agent_name, "error.type": type(e).__name__}
                    )
                raise
            finally:
                duration = time.time() - start_time
                if self._agent_step_count:
                    self._agent_step_count.add(
                        1, {"agent.name": agent_name, "agent.step.type": step_type}
                    )

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
            "agent.name": agent_name,
            "agent.step.name": tool_name,
            "agent.step.type": "tool_call",
            "agent.tool.name": tool_name,
        }

        # Add tool input as JSON string
        if tool_input:
            try:
                openinference_attrs["agent.tool.input"] = json.dumps(tool_input, ensure_ascii=False)
            except (TypeError, ValueError):
                openinference_attrs["agent.tool.input"] = str(tool_input)

        openinference_attrs.update(attributes)

        span_name = f"agent.tool.{tool_name}"

        with self._tracer.start_as_current_span(
            span_name,
            attributes=openinference_attrs
        ) as span:
            start_time = time.time()
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.set_attribute("error.type", type(e).__name__)
                span.set_attribute("error.message", str(e))
                if self._agent_error_count:
                    self._agent_error_count.add(
                        1, {"agent.name": agent_name, "error.type": type(e).__name__, "agent.tool.name": tool_name}
                    )
                raise
            finally:
                duration = time.time() - start_time
                duration_ms = duration * 1000
                span.set_attribute("agent.tool.duration_ms", duration_ms)
                if self._agent_step_count:
                    self._agent_step_count.add(
                        1, {"agent.name": agent_name, "agent.step.type": "tool_call", "agent.tool.name": tool_name}
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
            try:
                if isinstance(output, str):
                    span.set_attribute("agent.tool.output", output)
                else:
                    span.set_attribute("agent.tool.output", json.dumps(output, ensure_ascii=False))
            except (TypeError, ValueError):
                span.set_attribute("agent.tool.output", str(output))

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

    def record_agent_metrics(self, metric_type: str, value: float, attributes: Dict[str, Any]) -> None:
        """
        Record Agent-specific metrics using OpenInference semantic conventions.
        """
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        if metric_type == "duration" and self._agent_execution_duration:
            self._agent_execution_duration.record(value, attributes)

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

            def prepare_span(span, kwargs: Dict[str, Any]) -> None:
                if span and include_params:
                    safe_params = {
                        k: v for k, v in kwargs.items()
                        if k not in exclude_set and isinstance(v, (str, int, float, bool))
                    }
                    if safe_params:
                        self.set_span_attributes(**{f"param.{k}": v for k, v in safe_params.items()})
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
                with self.trace_llm_request(op_name, "nexent-service") as span:
                    prepare_span(span, kwargs)
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
                with self.trace_llm_request(op_name, "nexent-service") as span:
                    prepare_span(span, kwargs)
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
                with self.trace_llm_request(op_name, "nexent-service") as span:
                    prepare_span(span, kwargs)
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
                with self.trace_llm_request(op_name, "nexent-service") as span:
                    prepare_span(span, kwargs)
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
                # Always execute monitoring logic - internal methods handle enabled state
                with self.trace_llm_request(operation, model_name, **kwargs) as span:
                    token_tracker = self.create_token_tracker(
                        model_name, span) if span else None
                    self.add_span_event("llm_call_started")

                    try:
                        result = await func(*args, **kwargs, _token_tracker=token_tracker)
                        self.add_span_event("llm_call_completed")
                        return result
                    except Exception as e:
                        self.add_span_event("llm_call_error", {
                            "error.type": type(e).__name__,
                            "error.message": str(e)
                        })
                        raise

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Always execute monitoring logic - internal methods handle enabled state
                with self.trace_llm_request(operation, model_name, **kwargs) as span:
                    token_tracker = self.create_token_tracker(
                        model_name, span) if span else None
                    self.add_span_event("llm_call_started")

                    try:
                        result = func(*args, **kwargs,
                                      _token_tracker=token_tracker)
                        self.add_span_event("llm_call_completed")
                        return result
                    except Exception as e:
                        self.add_span_event("llm_call_error", {
                            "error.type": type(e).__name__,
                            "error.message": str(e)
                        })
                        raise

            if inspect.iscoroutinefunction(func):
                return cast(F, async_wrapper)
            else:
                return cast(F, sync_wrapper)

        return decorator

    def monitor_agent_execution(self, agent_name: str):
        """
        Decorator to add monitoring to Agent execution.
        Tracks overall execution duration and error count.

        Args:
            agent_name: Name of the agent being monitored
        """
        def decorator(func: F) -> F:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                status = "success"

                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    status = "error"
                    if self._agent_error_count:
                        self._agent_error_count.add(
                            1, {"agent.name": agent_name, "error.type": type(e).__name__}
                        )
                    raise
                finally:
                    duration = time.time() - start_time
                    if self._agent_execution_duration:
                        self._agent_execution_duration.record(
                            duration, {"agent.name": agent_name, "agent.status": status}
                        )

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                status = "success"

                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    status = "error"
                    if self._agent_error_count:
                        self._agent_error_count.add(
                            1, {"agent.name": agent_name, "error.type": type(e).__name__}
                        )
                    raise
                finally:
                    duration = time.time() - start_time
                    if self._agent_execution_duration:
                        self._agent_execution_duration.record(
                            duration, {"agent.name": agent_name, "agent.status": status}
                        )

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

    def record_first_token(self) -> None:
        """Record the time when first token is received."""
        if not self.manager.is_enabled:
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
        if not self.manager.is_enabled:
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
            self.span.set_attributes({
                "llm.token_count.prompt": input_tokens,
                "llm.token_count.completion": output_tokens,
                "llm.token_count.total": input_tokens + output_tokens,
                "llm.generation_rate": generation_rate,
                "llm.duration.total": total_duration,
                "llm.time_to_first_token": self.first_token_time - self.start_time if self.first_token_time else 0
            })


# Global singleton instance
_monitoring_manager = MonitoringManager()


# ============================================================================
# Public API Functions - Singleton Access
# ============================================================================

def get_monitoring_manager() -> MonitoringManager:
    """
    Get the global monitoring manager singleton instance.

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
    'LLMTokenTracker',
    'get_monitoring_manager',
    'is_opentelemetry_available',
]
