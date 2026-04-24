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

import logging
import os
import threading
import time
import functools
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Callable, TypeVar, cast, Iterator
from dataclasses import dataclass

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

# Operation tag to identify which business scenario triggered the model call.
# Set at the service/call-site layer; read by the client-level monitoring wrapper.
_monitoring_operation: ContextVar[str] = ContextVar(
    "_monitoring_operation", default="unknown")

# Tracker snapshot populated by LLMTokenTracker in __call__ for streaming calls.
# The client-level wrapper reads this after stream consumption to get TTFT/token data.
_monitoring_tracker_snapshot: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "_monitoring_tracker_snapshot", default=None
)

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
        return self._config is not None and self._config.enable_telemetry and OPENTELEMETRY_AVAILABLE

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
        """Specialized decorator for LLM calls with token tracking."""

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
                            "error_type": type(e).__name__,
                            "error_message": str(e)
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
                            "error_type": type(e).__name__,
                            "error_message": str(e)
                        })
                        _enqueue_monitoring_record(
                            token_tracker, actual_model_name, operation, kwargs, error=e, model_type=detected_type
                        )
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
                                    {"ttft_seconds": ttft})

            if self.manager.is_enabled:
                self.manager.record_llm_metrics(
                    "ttft", ttft, {"model": self.model_name})

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
        """Record completion metrics."""
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        total_duration = time.time() - self.start_time
        generation_rate = 0.0

        if self.manager.is_enabled:
            if total_duration > 0 and self.token_count > 0:
                generation_rate = self.token_count / total_duration
                self.manager.record_llm_metrics("token_rate", generation_rate, {
                                                "model": self.model_name})
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
