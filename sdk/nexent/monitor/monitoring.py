"""
Nexent LLM Performance Monitoring System

A comprehensive monitoring solution specifically designed for LLM applications.
Provides distributed tracing, token-level performance monitoring, and seamless 
integration with OpenTelemetry, Jaeger, Prometheus, and Grafana.

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
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.resources import Resource
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    # Define placeholder objects to avoid NameError when OpenTelemetry is not available
    Status = None
    StatusCode = None
    PrometheusMetricReader = None
    MeterProvider = None
    BatchSpanProcessor = None
    TracerProvider = None
    RequestsInstrumentor = None
    FastAPIInstrumentor = None
    JaegerExporter = None
    Resource = None
    # Create a mock trace module with a get_current_span function that returns None
    class _MockTraceModule:
        @staticmethod
        def get_current_span():
            return None
        @staticmethod
        def get_tracer(*args, **kwargs):
            return None
        @staticmethod
        def set_tracer_provider(*args, **kwargs):
            pass
    trace = _MockTraceModule()
    # Create a mock metrics module
    class _MockMetricsModule:
        @staticmethod
        def get_meter(*args, **kwargs):
            return None
        @staticmethod
        def set_meter_provider(*args, **kwargs):
            pass
    metrics = _MockMetricsModule()
import logging
import time
import functools
from contextlib import contextmanager
from typing import Any, Dict, Optional, Callable, TypeVar, cast, Iterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


def is_opentelemetry_available() -> bool:
    """Check if OpenTelemetry dependencies are available."""
    return OPENTELEMETRY_AVAILABLE

@dataclass
class MonitoringConfig:
    """Configuration for monitoring system."""
    enable_telemetry: bool = False
    service_name: str = "nexent-sdk"
    jaeger_endpoint: str = "http://localhost:14268/api/traces"
    prometheus_port: int = 8000
    telemetry_sample_rate: float = 1.0
    llm_slow_request_threshold_seconds: float = 5.0
    llm_slow_token_rate_threshold: float = 10.0
    
    def __post_init__(self):
        """Validate configuration and adjust based on OpenTelemetry availability."""
        if self.enable_telemetry and not OPENTELEMETRY_AVAILABLE:
            logger.warning(
                "OpenTelemetry dependencies not available. Disabling telemetry. "
                "Install with: pip install nexent[performance]"
            )
            self.enable_telemetry = False


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

        # LLM-specific metrics
        self._llm_request_duration: Optional[Any] = None
        self._llm_token_generation_rate: Optional[Any] = None
        self._llm_ttft_duration: Optional[Any] = None
        self._llm_total_tokens: Optional[Any] = None
        self._llm_error_count: Optional[Any] = None

        self._initialized = True
        logger.info("MonitoringManager singleton created")

    def configure(self, config: MonitoringConfig) -> None:
        """Configure the monitoring system."""
        self._config = config
        logger.info(
            f"Monitoring configured: enabled={config.enable_telemetry}, service={config.service_name}")

        if config.enable_telemetry:
            self._init_telemetry()

    def _init_telemetry(self) -> None:
        """Initialize OpenTelemetry tracing and metrics."""
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
            # Setup tracing with proper service name resource
            resource = Resource.create({
                "service.name": self._config.service_name,
                "service.version": "1.0.0",
                "service.instance.id": "nexent-instance-1"
            })
            self._tracer_provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(self._tracer_provider)

            # Jaeger exporter
            jaeger_exporter = JaegerExporter(
                agent_host_name="localhost",
                agent_port=14268,
                collector_endpoint=self._config.jaeger_endpoint,
            )

            span_processor = BatchSpanProcessor(jaeger_exporter)
            self._tracer_provider.add_span_processor(span_processor)

            # Setup metrics with Prometheus exporter
            prometheus_reader = PrometheusMetricReader()
            self._meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[prometheus_reader])
            metrics.set_meter_provider(self._meter_provider)

            # Get tracer and meter instances
            self._tracer = trace.get_tracer(self._config.service_name)
            self._meter = metrics.get_meter(self._config.service_name)

            # Create LLM-specific metrics
            self._llm_request_duration = self._meter.create_histogram(
                name="llm_request_duration_seconds",
                description="Duration of LLM requests in seconds",
                unit="s"
            )

            self._llm_token_generation_rate = self._meter.create_histogram(
                name="llm_token_generation_rate",
                description="Token generation rate (tokens per second)",
                unit="tokens/s"
            )

            self._llm_ttft_duration = self._meter.create_histogram(
                name="llm_time_to_first_token_seconds",
                description="Time to first token (TTFT) in seconds",
                unit="s"
            )

            self._llm_total_tokens = self._meter.create_counter(
                name="llm_total_tokens",
                description="Total tokens processed",
                unit="tokens"
            )

            self._llm_error_count = self._meter.create_counter(
                name="llm_error_count",
                description="Number of LLM errors",
                unit="errors"
            )

            # Auto-instrument other libraries
            RequestsInstrumentor().instrument()

            logger.info(
                f"Telemetry initialized successfully for service: {self._config.service_name}")

        except Exception as e:
            logger.error(f"Failed to initialize telemetry: {str(e)}")

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
                    "FastAPI application monitoring initialized successfully")
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
        """Context manager for tracing LLM requests with comprehensive metrics."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE or not self._tracer:
            yield None
            return

        with self._tracer.start_as_current_span(
            operation_name,
            attributes={
                "llm.model_name": model_name,
                "llm.operation": operation_name,
                **attributes
            }
        ) as span:
            start_time = time.time()
            try:
                yield span
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                if self._llm_error_count:
                    self._llm_error_count.add(
                        1, {"model": model_name, "operation": operation_name})
                raise
            finally:
                duration = time.time() - start_time
                if self._llm_request_duration:
                    self._llm_request_duration.record(
                        duration, {"model": model_name, "operation": operation_name})

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
        """Record LLM-specific metrics."""
        if not self.is_enabled or not OPENTELEMETRY_AVAILABLE:
            return

        if metric_type == "ttft" and self._llm_ttft_duration:
            self._llm_ttft_duration.record(value, attributes)
        elif metric_type == "token_rate" and self._llm_token_generation_rate:
            self._llm_token_generation_rate.record(value, attributes)
        elif metric_type == "tokens" and self._llm_total_tokens:
            self._llm_total_tokens.add(value, attributes)

    def monitor_endpoint(self, operation_name: Optional[str] = None, include_params: bool = True, exclude_params: Optional[list] = None) -> Callable[[F], F]:
        """
        Decorator to add monitoring to any endpoint or service function.
        Monitoring is automatically enabled/disabled based on configuration.
        """
        def decorator(func: F) -> F:
            op_name = operation_name or f"{func.__module__}.{func.__name__}"
            exclude_set = set(exclude_params or [])

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Always execute monitoring logic - internal methods handle enabled state
                with self.trace_llm_request(op_name, "nexent-service") as span:
                    if span and include_params:
                        safe_params = {
                            k: v for k, v in kwargs.items()
                            if k not in exclude_set and isinstance(v, (str, int, float, bool))
                        }
                        if safe_params:
                            self.set_span_attributes(
                                **{f"param.{k}": v for k, v in safe_params.items()})

                    self.add_span_event(f"{op_name}.started")
                    start_time = time.time()

                    try:
                        result = await func(*args, **kwargs)
                        duration = time.time() - start_time
                        self.add_span_event(
                            f"{op_name}.completed", {"duration": duration})
                        return result
                    except Exception as e:
                        duration = time.time() - start_time
                        self.add_span_event(f"{op_name}.error", {
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "duration": duration
                        })
                        raise

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Always execute monitoring logic - internal methods handle enabled state
                with self.trace_llm_request(op_name, "nexent-service") as span:
                    if span and include_params:
                        safe_params = {
                            k: v for k, v in kwargs.items()
                            if k not in exclude_set and isinstance(v, (str, int, float, bool))
                        }
                        if safe_params:
                            self.set_span_attributes(
                                **{f"param.{k}": v for k, v in safe_params.items()})

                    self.add_span_event(f"{op_name}.started")
                    start_time = time.time()

                    try:
                        result = func(*args, **kwargs)
                        duration = time.time() - start_time
                        self.add_span_event(
                            f"{op_name}.completed", {"duration": duration})
                        return result
                    except Exception as e:
                        duration = time.time() - start_time
                        self.add_span_event(f"{op_name}.error", {
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "duration": duration
                        })
                        raise

            # Return appropriate wrapper based on function type
            if hasattr(func, '__code__') and func.__code__.co_flags & 0x80:
                return cast(F, async_wrapper)
            else:
                return cast(F, sync_wrapper)

        return decorator

    def monitor_llm_call(self, model_name: str, operation: str = "llm_completion"):
        """
        Specialized decorator for LLM calls with token tracking.
        Monitoring is automatically enabled/disabled based on configuration.
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
                            "error_type": type(e).__name__,
                            "error_message": str(e)
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
                            "error_type": type(e).__name__,
                            "error_message": str(e)
                        })
                        raise

            if hasattr(func, '__code__') and func.__code__.co_flags & 0x80:
                return cast(F, async_wrapper)
            else:
                return cast(F, sync_wrapper)

        return decorator


class LLMTokenTracker:
    """Tracks token generation metrics for streaming LLM responses."""

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
                                    {"ttft_seconds": ttft})

            self.manager.record_llm_metrics(
                "ttft", ttft, {"model": self.model_name})

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
        """Record completion metrics."""
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
                                            "model": self.model_name})

        # Record total tokens
        self.manager.record_llm_metrics("tokens", input_tokens, {
                                        "model": self.model_name, "type": "input"})
        self.manager.record_llm_metrics("tokens", output_tokens, {
                                        "model": self.model_name, "type": "output"})

        # Add span attributes
        if self.span:
            self.span.set_attributes({
                "llm.input_tokens": input_tokens,
                "llm.output_tokens": output_tokens,
                "llm.total_tokens": input_tokens + output_tokens,
                "llm.generation_rate": generation_rate,
                "llm.total_duration": total_duration,
                "llm.ttft": self.first_token_time - self.start_time if self.first_token_time else 0
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
