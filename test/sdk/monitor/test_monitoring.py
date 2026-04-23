"""
Comprehensive unit tests for SDK monitoring module.

Tests cover:
- MonitoringConfig dataclass
- MonitoringManager singleton behavior
- Telemetry initialization and configuration
- LLM request tracing and metrics
- Token tracking and performance metrics
- Decorator functionality for endpoint and LLM monitoring
- Error handling and edge cases
"""

from sdk.nexent.monitor.monitoring import (
    MonitoringConfig,
    MonitoringManager,
    LLMTokenTracker,
    get_monitoring_manager,
    _detect_model_type,
    _enqueue_monitoring_record,
    RecordModelCallContext,
    MonitoringRecordBuffer,
    get_monitoring_buffer,
    set_monitoring_context,
    get_monitoring_context,
    _monitoring_buffer,
    _MonitoredClient,
    _MonitoredChatCompletions,
    _MonitoredStreamIterator,
    _monitoring_operation,
    _monitoring_tracker_snapshot,
    _monitoring_display_name,
    set_monitoring_operation,
    _enqueue_client_monitoring_record,
)
import pytest
import asyncio
import time
import sys
import threading
from unittest.mock import Mock, MagicMock, patch, call


class TestMonitoringConfig:
    """Test MonitoringConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MonitoringConfig()

        assert config.enable_telemetry is False
        assert config.service_name == "nexent-sdk"
        assert config.jaeger_endpoint == "http://localhost:14268/api/traces"
        assert config.prometheus_port == 8000
        assert config.telemetry_sample_rate == 1.0
        assert config.llm_slow_request_threshold_seconds == 5.0
        assert config.llm_slow_token_rate_threshold == 10.0

    def test_custom_config(self):
        """Test configuration with custom values."""
        config = MonitoringConfig(
            enable_telemetry=True,
            service_name="test-service",
            jaeger_endpoint="http://test:14268/api/traces",
            prometheus_port=9000,
            telemetry_sample_rate=0.5,
            llm_slow_request_threshold_seconds=10.0,
            llm_slow_token_rate_threshold=20.0
        )

        assert config.enable_telemetry is True
        assert config.service_name == "test-service"
        assert config.jaeger_endpoint == "http://test:14268/api/traces"
        assert config.prometheus_port == 9000
        assert config.telemetry_sample_rate == 0.5
        assert config.llm_slow_request_threshold_seconds == 10.0
        assert config.llm_slow_token_rate_threshold == 20.0


class TestMonitoringManager:
    """Test MonitoringManager singleton and core functionality."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    def test_singleton_behavior(self):
        """Test that MonitoringManager is a proper singleton."""
        manager1 = MonitoringManager()
        manager2 = MonitoringManager()

        assert manager1 is manager2
        assert id(manager1) == id(manager2)

    def test_initialization_only_once(self):
        """Test that initialization only happens once."""
        manager1 = MonitoringManager()
        original_config = manager1._config

        manager2 = MonitoringManager()
        assert manager2._config is original_config

    def test_configure_disabled_telemetry(self):
        """Test configuration with telemetry disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)

        with patch.object(manager, '_init_telemetry') as mock_init:
            manager.configure(config)

            assert manager._config is config
            mock_init.assert_not_called()

    def test_configure_enabled_telemetry(self):
        """Test configuration with telemetry enabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)

        with patch.object(manager, '_init_telemetry') as mock_init:
            manager.configure(config)

            assert manager._config is config
            mock_init.assert_called_once()

    def test_is_enabled_property(self):
        """Test is_enabled property behavior."""
        manager = MonitoringManager()

        # No config set
        assert manager.is_enabled is False

        # Config with telemetry disabled
        config_disabled = MonitoringConfig(enable_telemetry=False)
        manager.configure(config_disabled)
        assert manager.is_enabled is False

        # Config with telemetry enabled
        config_enabled = MonitoringConfig(enable_telemetry=True)
        manager.configure(config_enabled)
        assert manager.is_enabled is True

    @patch('sdk.nexent.monitor.monitoring.trace')
    @patch('sdk.nexent.monitor.monitoring.metrics')
    @patch('sdk.nexent.monitor.monitoring.TracerProvider')
    @patch('sdk.nexent.monitor.monitoring.MeterProvider')
    @patch('sdk.nexent.monitor.monitoring.JaegerExporter')
    @patch('sdk.nexent.monitor.monitoring.BatchSpanProcessor')
    @patch('sdk.nexent.monitor.monitoring.PrometheusMetricReader')
    @patch('sdk.nexent.monitor.monitoring.Resource')
    @patch('sdk.nexent.monitor.monitoring.RequestsInstrumentor')
    def test_init_telemetry_success(self, mock_requests_instr, mock_resource,
                                    mock_prometheus, mock_batch_processor,
                                    mock_jaeger, mock_meter_provider,
                                    mock_tracer_provider, mock_metrics, mock_trace):
        """Test successful telemetry initialization."""
        manager = MonitoringManager()
        config = MonitoringConfig(
            enable_telemetry=True,
            service_name="test-service",
            jaeger_endpoint="http://test:14268/api/traces"
        )

        # Mock return values
        mock_resource_instance = MagicMock()
        mock_resource.create.return_value = mock_resource_instance

        mock_tracer_provider_instance = MagicMock()
        mock_tracer_provider.return_value = mock_tracer_provider_instance

        mock_meter_provider_instance = MagicMock()
        mock_meter_provider.return_value = mock_meter_provider_instance

        mock_tracer = MagicMock()
        mock_trace.get_tracer.return_value = mock_tracer

        mock_meter = MagicMock()
        mock_metrics.get_meter.return_value = mock_meter

        # Configure will call _init_telemetry internally
        manager.configure(config)

        # Verify resource creation (called once during configure)
        mock_resource.create.assert_called_with({
            "service.name": "test-service",
            "service.version": "1.0.0",
            "service.instance.id": "nexent-instance-1"
        })

        # Verify tracer provider setup
        mock_tracer_provider.assert_called_once_with(
            resource=mock_resource_instance)
        mock_trace.set_tracer_provider.assert_called_once_with(
            mock_tracer_provider_instance)

        # Verify metrics setup
        mock_meter_provider.assert_called_once()
        mock_metrics.set_meter_provider.assert_called_once()

        # Verify instrumentation
        mock_requests_instr().instrument.assert_called_once()

    def test_init_telemetry_disabled(self):
        """Test telemetry initialization when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        with patch('sdk.nexent.monitor.monitoring.trace') as mock_trace:
            manager._init_telemetry()
            mock_trace.set_tracer_provider.assert_not_called()

    def test_init_telemetry_no_config(self):
        """Test telemetry initialization with no config."""
        manager = MonitoringManager()

        with patch('sdk.nexent.monitor.monitoring.trace') as mock_trace:
            manager._init_telemetry()
            mock_trace.set_tracer_provider.assert_not_called()

    def test_init_telemetry_exception_handling(self):
        """Test telemetry initialization with exceptions."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        with patch('sdk.nexent.monitor.monitoring.TracerProvider', side_effect=Exception("Test error")):
            with patch('sdk.nexent.monitor.monitoring.logger') as mock_logger:
                manager._init_telemetry()
                mock_logger.error.assert_called_once()

    def test_setup_fastapi_app_enabled(self):
        """Test FastAPI app setup when monitoring is enabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        mock_app = MagicMock()

        with patch('sdk.nexent.monitor.monitoring.FastAPIInstrumentor') as mock_instrumentor:
            result = manager.setup_fastapi_app(mock_app)

            assert result is True
            mock_instrumentor.instrument_app.assert_called_once_with(mock_app)

    def test_setup_fastapi_app_disabled(self):
        """Test FastAPI app setup when monitoring is disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        mock_app = MagicMock()
        result = manager.setup_fastapi_app(mock_app)

        assert result is False

    def test_setup_fastapi_app_no_app(self):
        """Test FastAPI app setup with None app."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        result = manager.setup_fastapi_app(None)
        assert result is False

    def test_setup_fastapi_app_exception(self):
        """Test FastAPI app setup with exception."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        mock_app = MagicMock()

        with patch('sdk.nexent.monitor.monitoring.FastAPIInstrumentor') as mock_instrumentor:
            mock_instrumentor.instrument_app.side_effect = Exception(
                "Test error")

            result = manager.setup_fastapi_app(mock_app)
            assert result is False

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_llm_request_enabled(self, mock_trace):
        """Test LLM request tracing when enabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)
        manager._tracer = MagicMock()

        mock_span = MagicMock()
        manager._tracer.start_as_current_span.return_value.__enter__ = Mock(
            return_value=mock_span)
        manager._tracer.start_as_current_span.return_value.__exit__ = Mock(
            return_value=None)

        with manager.trace_llm_request("test_op", "test_model", param1="value1") as span:
            assert span is mock_span

        manager._tracer.start_as_current_span.assert_called_once_with(
            "test_op",
            attributes={
                "llm.model_name": "test_model",
                "llm.operation": "test_op",
                "param1": "value1"
            }
        )

    def test_trace_llm_request_disabled(self):
        """Test LLM request tracing when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        with manager.trace_llm_request("test_op", "test_model") as span:
            assert span is None

    def test_trace_llm_request_no_tracer(self):
        """Test LLM request tracing when tracer is None."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)
        manager._tracer = None

        with manager.trace_llm_request("test_op", "test_model") as span:
            assert span is None

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_llm_request_with_exception(self, mock_trace):
        """Test LLM request tracing with exception."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)
        manager._tracer = MagicMock()
        manager._llm_error_count = MagicMock()

        mock_span = MagicMock()
        manager._tracer.start_as_current_span.return_value.__enter__ = Mock(
            return_value=mock_span)
        manager._tracer.start_as_current_span.return_value.__exit__ = Mock(
            return_value=None)

        test_error = ValueError("Test error")

        with pytest.raises(ValueError):
            with manager.trace_llm_request("test_op", "test_model") as span:
                raise test_error

        # Verify error handling
        mock_span.set_status.assert_called_once()
        manager._llm_error_count.add.assert_called_once_with(
            1, {"model": "test_model", "operation": "test_op"}
        )

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_get_current_span_enabled(self, mock_trace):
        """Test getting current span when enabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        mock_span = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        result = manager.get_current_span()
        assert result is mock_span
        mock_trace.get_current_span.assert_called_once()

    def test_get_current_span_disabled(self):
        """Test getting current span when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        result = manager.get_current_span()
        assert result is None

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_add_span_event_enabled(self, mock_trace):
        """Test adding span event when enabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        mock_span = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        manager.add_span_event("test_event", {"key": "value"})

        mock_span.add_event.assert_called_once_with(
            "test_event", {"key": "value"})

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_add_span_event_no_attributes(self, mock_trace):
        """Test adding span event without attributes."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        mock_span = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        manager.add_span_event("test_event")

        mock_span.add_event.assert_called_once_with("test_event", {})

    def test_add_span_event_disabled(self):
        """Test adding span event when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        # Should not raise any exception
        manager.add_span_event("test_event", {"key": "value"})

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_add_span_event_no_span(self, mock_trace):
        """Test adding span event when no current span."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        mock_trace.get_current_span.return_value = None

        # Should not raise any exception
        manager.add_span_event("test_event", {"key": "value"})

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_set_span_attributes_enabled(self, mock_trace):
        """Test setting span attributes when enabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        mock_span = MagicMock()
        mock_trace.get_current_span.return_value = mock_span

        manager.set_span_attributes(key1="value1", key2="value2")

        mock_span.set_attributes.assert_called_once_with(
            {"key1": "value1", "key2": "value2"})

    def test_set_span_attributes_disabled(self):
        """Test setting span attributes when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        # Should not raise any exception
        manager.set_span_attributes(key1="value1", key2="value2")

    def test_create_token_tracker(self):
        """Test creating token tracker."""
        manager = MonitoringManager()
        mock_span = MagicMock()

        tracker = manager.create_token_tracker("test_model", mock_span)

        assert isinstance(tracker, LLMTokenTracker)
        assert tracker.manager is manager
        assert tracker.model_name == "test_model"
        assert tracker.span is mock_span

    def test_record_llm_metrics_disabled(self):
        """Test recording LLM metrics when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        # Should not raise any exception
        manager.record_llm_metrics("ttft", 0.5, {"model": "test"})

    def test_record_llm_metrics_ttft(self):
        """Test recording TTFT metrics."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)
        manager._llm_ttft_duration = MagicMock()

        manager.record_llm_metrics("ttft", 0.5, {"model": "test"})

        manager._llm_ttft_duration.record.assert_called_once_with(
            0.5, {"model": "test"})

    def test_record_llm_metrics_token_rate(self):
        """Test recording token rate metrics."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)
        manager._llm_token_generation_rate = MagicMock()

        manager.record_llm_metrics("token_rate", 10.5, {"model": "test"})

        manager._llm_token_generation_rate.record.assert_called_once_with(10.5, {
                                                                          "model": "test"})

    def test_record_llm_metrics_tokens(self):
        """Test recording token count metrics."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)
        manager._llm_total_tokens = MagicMock()

        manager.record_llm_metrics("tokens", 100, {"model": "test"})

        manager._llm_total_tokens.add.assert_called_once_with(
            100, {"model": "test"})

    def test_monitor_endpoint_decorator_async(self):
        """Test monitor_endpoint decorator with async function."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        with patch.object(manager, 'trace_llm_request') as mock_trace:
            mock_context = MagicMock()
            mock_trace.return_value.__enter__ = Mock(return_value=MagicMock())
            mock_trace.return_value.__exit__ = Mock(return_value=None)

            @manager.monitor_endpoint("test_operation")
            async def test_function(param1, param2="default"):
                return {"result": "success"}

            # Test the decorated function
            result = asyncio.run(test_function("value1", param2="value2"))

            assert result == {"result": "success"}

    def test_monitor_endpoint_decorator_sync(self):
        """Test monitor_endpoint decorator with sync function."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        with patch.object(manager, 'trace_llm_request') as mock_trace:
            mock_context = MagicMock()
            mock_trace.return_value.__enter__ = Mock(return_value=MagicMock())
            mock_trace.return_value.__exit__ = Mock(return_value=None)

            @manager.monitor_endpoint("test_operation")
            def test_function(param1, param2="default"):
                return {"result": "success"}

            # Test the decorated function
            result = test_function("value1", param2="value2")

            assert result == {"result": "success"}

    def test_monitor_endpoint_decorator_with_exception(self):
        """Test monitor_endpoint decorator with exception."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        with patch.object(manager, 'trace_llm_request') as mock_trace:
            mock_context = MagicMock()
            mock_trace.return_value.__enter__ = Mock(return_value=MagicMock())
            mock_trace.return_value.__exit__ = Mock(return_value=None)

            @manager.monitor_endpoint("test_operation")
            def test_function():
                raise ValueError("Test error")

            # Test that exception is re-raised
            with pytest.raises(ValueError, match="Test error"):
                test_function()

    def test_monitor_endpoint_exclude_params(self):
        """Test monitor_endpoint decorator with excluded parameters."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        with patch.object(manager, 'trace_llm_request') as mock_trace, \
                patch.object(manager, 'set_span_attributes') as mock_set_attrs:

            mock_span = MagicMock()
            mock_trace.return_value.__enter__ = Mock(return_value=mock_span)
            mock_trace.return_value.__exit__ = Mock(return_value=None)

            @manager.monitor_endpoint("test_operation", exclude_params=["password"])
            def test_function(username, password, debug=True):
                return {"result": "success"}

            test_function(username="user1", password="secret123", debug=False)

            # Verify that password was excluded and other params included
            mock_set_attrs.assert_called()
            call_args = mock_set_attrs.call_args[1]
            assert "param.username" in call_args
            assert call_args["param.username"] == "user1"
            assert "param.debug" in call_args
            assert call_args["param.debug"] is False
            assert "param.password" not in call_args

    def test_monitor_llm_call_decorator_sync(self):
        """Test monitor_llm_call decorator with sync function."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        with patch.object(manager, 'trace_llm_request') as mock_trace, \
                patch.object(manager, 'create_token_tracker') as mock_create_tracker:

            mock_span = MagicMock()
            mock_trace.return_value.__enter__ = Mock(return_value=mock_span)
            mock_trace.return_value.__exit__ = Mock(return_value=None)

            mock_tracker = MagicMock()
            mock_create_tracker.return_value = mock_tracker

            @manager.monitor_llm_call("test_model", "completion")
            def test_llm_function(**kwargs):
                # Verify token tracker is passed
                assert "_token_tracker" in kwargs
                assert kwargs["_token_tracker"] is mock_tracker
                return {"result": "success"}

            result = test_llm_function()
            assert result == {"result": "success"}

    def test_monitor_llm_call_decorator_async(self):
        """Test monitor_llm_call decorator with async function."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        with patch.object(manager, 'trace_llm_request') as mock_trace, \
                patch.object(manager, 'create_token_tracker') as mock_create_tracker:

            mock_span = MagicMock()
            mock_trace.return_value.__enter__ = Mock(return_value=mock_span)
            mock_trace.return_value.__exit__ = Mock(return_value=None)

            mock_tracker = MagicMock()
            mock_create_tracker.return_value = mock_tracker

            @manager.monitor_llm_call("test_model", "completion")
            async def test_llm_function(**kwargs):
                # Verify token tracker is passed
                assert "_token_tracker" in kwargs
                assert kwargs["_token_tracker"] is mock_tracker
                return {"result": "success"}

            result = asyncio.run(test_llm_function())
            assert result == {"result": "success"}


class TestLLMTokenTracker:
    """Test LLMTokenTracker functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = MagicMock()
        self.span = MagicMock()
        self.model_name = "test_model"

    def test_initialization(self):
        """Test LLMTokenTracker initialization."""
        with patch('time.time', return_value=123.456):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)

            assert tracker.manager is self.manager
            assert tracker.model_name == self.model_name
            assert tracker.span is self.span
            assert tracker.start_time == 123.456
            assert tracker.first_token_time is None
            assert tracker.token_count == 0
            assert tracker.input_tokens == 0
            assert tracker.output_tokens == 0

    def test_record_first_token_enabled(self):
        """Test recording first token when monitoring is enabled."""
        self.manager.is_enabled = True

        # 0.5 second difference
        with patch('time.time', side_effect=[123.456, 123.956]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
            tracker.record_first_token()

            assert tracker.first_token_time == 123.956

            # Verify span event
            self.span.add_event.assert_called_once_with(
                "first_token_received", {"ttft_seconds": 0.5}
            )

            # Verify metrics recording
            self.manager.record_llm_metrics.assert_called_once_with(
                "ttft", 0.5, {"model": self.model_name}
            )

    def test_record_first_token_disabled(self):
        """Test recording first token when monitoring is disabled."""
        self.manager.is_enabled = False

        tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
        tracker.record_first_token()

        assert tracker.first_token_time is None
        self.span.add_event.assert_not_called()
        self.manager.record_llm_metrics.assert_not_called()

    def test_record_first_token_multiple_calls(self):
        """Test that first token is only recorded once."""
        self.manager.is_enabled = True

        with patch('time.time', side_effect=[123.456, 123.956, 124.456]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)

            # First call should record
            tracker.record_first_token()
            first_time = tracker.first_token_time

            # Second call should not change the time
            tracker.record_first_token()

            assert tracker.first_token_time == first_time
            assert self.span.add_event.call_count == 1

    def test_record_token_enabled(self):
        """Test recording token when monitoring is enabled."""
        self.manager.is_enabled = True

        with patch('time.time', side_effect=[123.456, 123.956]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
            tracker.record_token("test_token")

            assert tracker.token_count == 1
            assert tracker.first_token_time == 123.956  # Should auto-record first token

            # Verify span event
            self.span.add_event.assert_called_with(
                "token_generated", {
                    "token_count": 1,
                    "token_length": len("test_token")
                }
            )

    def test_record_token_disabled(self):
        """Test recording token when monitoring is disabled."""
        self.manager.is_enabled = False

        tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
        tracker.record_token("test_token")

        assert tracker.token_count == 0
        assert tracker.first_token_time is None
        self.span.add_event.assert_not_called()

    def test_record_token_multiple_tokens(self):
        """Test recording multiple tokens."""
        self.manager.is_enabled = True

        with patch('time.time', side_effect=[123.456, 123.956, 124.056, 124.156]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)

            tracker.record_token("token1")
            tracker.record_token("token2")
            tracker.record_token("token3")

            assert tracker.token_count == 3
            # First token time should not change after initial recording
            assert tracker.first_token_time == 123.956

    def test_record_completion_enabled(self):
        """Test recording completion metrics when monitoring is enabled."""
        self.manager.is_enabled = True

        # 2.5 second total
        with patch('time.time', side_effect=[123.456, 123.956, 125.956]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
            tracker.record_first_token()  # Set first token time (creates duration of 0.5s)
            tracker.token_count = 5  # Simulate 5 tokens generated

            tracker.record_completion(input_tokens=10, output_tokens=15)

            assert tracker.input_tokens == 10
            assert tracker.output_tokens == 15

            # Verify metrics recording - the actual rate calculation: 5 tokens / 2.5 seconds = 2.0 tokens/sec
            expected_rate = 2.0  # 5 tokens / 2.5 seconds
            self.manager.record_llm_metrics.assert_any_call(
                "token_rate", expected_rate, {"model": self.model_name}
            )
            self.manager.record_llm_metrics.assert_any_call(
                "tokens", 10, {"model": self.model_name, "type": "input"}
            )
            self.manager.record_llm_metrics.assert_any_call(
                "tokens", 15, {"model": self.model_name, "type": "output"}
            )

    def test_record_completion_disabled(self):
        """Test recording completion metrics when monitoring is disabled."""
        self.manager.is_enabled = False

        tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
        tracker.record_completion(input_tokens=10, output_tokens=15)

        self.manager.record_llm_metrics.assert_not_called()

    def test_record_completion_span_attributes(self):
        """Test that completion sets span attributes correctly."""
        self.manager.is_enabled = True

        # 2 second total
        with patch('time.time', side_effect=[123.456, 123.956, 125.456]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
            tracker.record_first_token()
            tracker.token_count = 10

            tracker.record_completion(input_tokens=20, output_tokens=30)

            # Verify span attributes
            expected_attrs = {
                "llm.input_tokens": 20,
                "llm.output_tokens": 30,
                "llm.total_tokens": 50,
                "llm.generation_rate": 5.0,  # 10 tokens / 2 seconds
                "llm.total_duration": 2.0,
                "llm.ttft": 0.5  # first_token_time - start_time
            }
            self.span.set_attributes.assert_called_once_with(expected_attrs)

    def test_record_completion_zero_duration(self):
        """Test recording completion with zero duration."""
        self.manager.is_enabled = True

        with patch('time.time', return_value=123.456):  # Same time for all calls
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
            tracker.token_count = 5

            tracker.record_completion(input_tokens=10, output_tokens=15)

            # Should handle zero duration gracefully
            assert tracker.input_tokens == 10
            assert tracker.output_tokens == 15

    def test_record_completion_no_tokens(self):
        """Test recording completion with no tokens generated."""
        self.manager.is_enabled = True

        # 1 second total
        with patch('time.time', side_effect=[123.456, 124.456]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
            # Don't set token_count (remains 0)

            tracker.record_completion(input_tokens=10, output_tokens=15)

            # Should handle zero tokens gracefully
            assert tracker.input_tokens == 10
            assert tracker.output_tokens == 15


class TestGlobalFunctions:
    """Test global functions."""

    def test_get_monitoring_manager_singleton(self):
        """Test that get_monitoring_manager returns the same instance."""
        # Reset singleton
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

        manager1 = get_monitoring_manager()
        manager2 = get_monitoring_manager()

        assert manager1 is manager2
        assert isinstance(manager1, MonitoringManager)


class TestIntegrationScenarios:
    """Test integration scenarios and edge cases."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    def test_full_monitoring_lifecycle(self):
        """Test complete monitoring lifecycle from config to metrics."""
        manager = get_monitoring_manager()
        config = MonitoringConfig(
            enable_telemetry=True, service_name="test-service")

        with patch.object(manager, '_init_telemetry'):
            manager.configure(config)

            # Test that all methods work with enabled monitoring
            assert manager.is_enabled is True

            tracker = manager.create_token_tracker("test_model")
            assert isinstance(tracker, LLMTokenTracker)

            # Test decorators work
            @manager.monitor_endpoint("test_op")
            def test_func():
                return "success"

            result = test_func()
            assert result == "success"

    def test_monitoring_disabled_lifecycle(self):
        """Test monitoring lifecycle when disabled."""
        manager = get_monitoring_manager()
        config = MonitoringConfig(enable_telemetry=False)

        manager.configure(config)

        # All methods should work without errors when disabled
        assert manager.is_enabled is False

        manager.add_span_event("test_event")
        manager.set_span_attributes(key="value")
        manager.record_llm_metrics("ttft", 0.5, {})

        # Decorators should still work
        @manager.monitor_endpoint("test_op")
        def test_func():
            return "success"

        result = test_func()
        assert result == "success"

    def test_concurrent_access(self):
        """Test concurrent access to singleton."""
        import threading

        managers = []

        def create_manager():
            managers.append(get_monitoring_manager())

        threads = [threading.Thread(target=create_manager) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All managers should be the same instance
        assert len(set(id(m) for m in managers)) == 1

    def test_error_resilience(self):
        """Test that monitoring errors don't break application flow."""
        manager = get_monitoring_manager()
        config = MonitoringConfig(enable_telemetry=True)
        manager.configure(config)

        # Test that when monitoring is disabled, methods handle gracefully
        manager._config.enable_telemetry = False

        # These should not raise exceptions when disabled
        manager.add_span_event("test_event")
        manager.set_span_attributes(key="value")
        manager.record_llm_metrics("ttft", 0.5, {})

        # Re-enable for decorator test
        manager._config.enable_telemetry = True

        # Test decorator with mocked internal error handling
        with patch.object(manager, 'trace_llm_request') as mock_trace:
            # Mock context manager that handles errors gracefully
            mock_context = MagicMock()
            mock_context.__enter__ = Mock(return_value=None)
            mock_context.__exit__ = Mock(return_value=None)
            mock_trace.return_value = mock_context

            @manager.monitor_endpoint("test_op")
            def test_func():
                return "success"

            # Function should work normally
            result = test_func()
            assert result == "success"

# ---------------------------------------------------------------------------
# Fixture: reset the module-level _monitoring_buffer singleton before each
# test so that state never leaks between test classes.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_monitoring_buffer():
    """Reset the global _monitoring_buffer singleton before each test."""
    import sdk.nexent.monitor.monitoring as _mod

    original = _mod._monitoring_buffer
    _mod._monitoring_buffer = None
    yield
    # Stop any running flush thread to avoid leaked threads
    buf = _mod._monitoring_buffer
    if buf is not None and hasattr(buf, "stop"):
        buf.stop()
    _mod._monitoring_buffer = original


# =========================================================================
# TestDetectModelType  (Task 1.1)
# =========================================================================
class TestDetectModelType:
    """Verify _detect_model_type infers model type from class name."""

    def test_vlm_class_name(self):
        """Class name containing 'vlm' returns 'vlm'."""

        class OpenAIVLModel:
            pass

        assert _detect_model_type(OpenAIVLModel()) == "vlm"

    def test_llm_class_name(self):
        """Class name 'OpenAIModel' returns 'llm'."""

        class OpenAIModel:
            pass

        assert _detect_model_type(OpenAIModel()) == "llm"

    def test_embedding_class_name(self):
        """Class names containing 'embed' return 'embedding'."""

        class OpenAICompatibleEmbedding:
            pass

        class JinaEmbedding:
            pass

        assert _detect_model_type(OpenAICompatibleEmbedding()) == "embedding"
        assert _detect_model_type(JinaEmbedding()) == "embedding"

    def test_unknown_class_name_defaults_to_llm(self):
        """Unknown class names default to 'llm'."""

        class SomeRandomModel:
            pass

        assert _detect_model_type(SomeRandomModel()) == "llm"


# =========================================================================
# TestWriteBatchIsolation  (Tasks 2.1 + 2.2)
# =========================================================================
class TestWriteBatchIsolation:
    """Verify _write_batch isolates individual record failures."""

    def _make_buffer(self):
        """Create a MonitoringRecordBuffer with flush thread disabled."""
        with patch.dict("os.environ", {"ENABLE_MODEL_MONITORING": "false"}):
            buf = MonitoringRecordBuffer()
        buf._enabled = True
        return buf

    def _setup_db_mocks(self):
        """Inject mock database modules into sys.modules for lazy imports."""
        mock_db_models = MagicMock()
        mock_db_client = MagicMock()
        sys.modules["database"] = MagicMock()
        sys.modules["database.db_models"] = mock_db_models
        sys.modules["database.client"] = mock_db_client
        return (
            mock_db_client.get_monitoring_db_session,
            mock_db_models.ModelMonitoringRecord,
        )

    def test_mixed_valid_and_invalid_records(self):
        """Valid records succeed; invalid ones are skipped silently."""
        mock_session_fn, _ = self._setup_db_mocks()
        call_count = {"n": 0}

        def _session_ctx():
            class _Ctx:
                def __enter__(self_inner):
                    call_count["n"] += 1
                    if call_count["n"] == 2:
                        raise RuntimeError("DB error on second record")
                    return MagicMock()

                def __exit__(self_inner, *args):
                    pass  # Intentionally empty: no cleanup needed for mock context

            return _Ctx()

        mock_session_fn.side_effect = _session_ctx
        buf = self._make_buffer()

        batch = [
            {"model_name": "m1", "tenant_id": "t1"},
            {"model_name": "m2", "tenant_id": "t2"},
            {"model_name": "m3", "tenant_id": "t3"},
        ]
        buf._write_batch(batch)

    def test_all_valid_records(self):
        """All valid records are written successfully."""
        mock_session_fn, _ = self._setup_db_mocks()
        mock_session = MagicMock()
        mock_session_fn.return_value.__enter__ = Mock(
            return_value=mock_session)
        mock_session_fn.return_value.__exit__ = Mock(return_value=None)

        buf = self._make_buffer()
        batch = [{"model_name": f"m{i}"} for i in range(3)]
        buf._write_batch(batch)

        assert mock_session.add.call_count == 3

    def test_all_invalid_records(self):
        """When every record fails, _write_batch still does not raise."""
        mock_session_fn, _ = self._setup_db_mocks()
        mock_session_fn.return_value.__enter__ = Mock(
            side_effect=RuntimeError("DB down")
        )
        mock_session_fn.return_value.__exit__ = Mock(return_value=None)

        buf = self._make_buffer()
        batch = [{"model_name": f"m{i}"} for i in range(3)]
        buf._write_batch(batch)


# =========================================================================
# TestEnqueueMonitoringRecord  (Tasks 3.1 + 3.2)
# =========================================================================
class TestEnqueueMonitoringRecord:
    """Verify _enqueue_monitoring_record tenant_id checks and snapshot priority."""

    def setup_method(self):
        """Reset monitoring context vars."""
        import sdk.nexent.monitor.monitoring as _mod

        _mod._monitoring_tenant_id.set(None)
        _mod._monitoring_user_id.set(None)
        _mod._monitoring_agent_id.set(None)
        _mod._monitoring_conversation_id.set(None)

    def test_enqueue_with_tenant_id(self):
        """Record is added to buffer when tenant_id is present."""
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        tracker = MagicMock()
        tracker.start_time = time.time()
        tracker.first_token_time = None
        tracker.input_tokens = 10
        tracker.output_tokens = 20
        tracker.token_count = 5
        tracker._context_snapshot = {"tenant_id": "t-123"}

        with patch(
            "sdk.nexent.monitor.monitoring.get_monitoring_buffer",
            return_value=mock_buffer,
        ):
            _enqueue_monitoring_record(tracker, "model-a", "op", {})

        mock_buffer.add_record.assert_called_once()
        record = mock_buffer.add_record.call_args[0][0]
        assert record["tenant_id"] == "t-123"

    def test_enqueue_without_tenant_id_skips(self):
        """Record is NOT added when tenant_id is absent everywhere."""
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        tracker = MagicMock()
        tracker._context_snapshot = {}
        tracker.start_time = time.time()
        tracker.first_token_time = None
        tracker.input_tokens = 0
        tracker.output_tokens = 0
        tracker.token_count = 0

        with (
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_buffer",
                return_value=mock_buffer,
            ),
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_context", return_value={}
            ),
        ):
            _enqueue_monitoring_record(tracker, "model-a", "op", {})

        mock_buffer.add_record.assert_not_called()

    def test_snapshot_priority_over_live_context(self):
        """Tracker snapshot tenant_id takes priority over live context."""
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        tracker = MagicMock()
        tracker.start_time = time.time()
        tracker.first_token_time = None
        tracker.input_tokens = 0
        tracker.output_tokens = 0
        tracker.token_count = 0
        tracker._context_snapshot = {"tenant_id": "from-snapshot"}
        tracker._display_name = None

        live_ctx = {"tenant_id": "from-live"}

        with (
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_buffer",
                return_value=mock_buffer,
            ),
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_context",
                return_value=live_ctx,
            ),
        ):
            _enqueue_monitoring_record(tracker, "model-a", "op", {})

        mock_buffer.add_record.assert_called_once()
        record = mock_buffer.add_record.call_args[0][0]
        assert record["tenant_id"] == "from-snapshot"


# =========================================================================
# TestRecordModelCallContext  (Task 4.1)
# =========================================================================
class TestRecordModelCallContext:
    """Verify RecordModelCallContext handles tenant_id and exceptions correctly."""

    def setup_method(self):
        """Reset monitoring context vars."""
        import sdk.nexent.monitor.monitoring as _mod

        _mod._monitoring_tenant_id.set(None)
        _mod._monitoring_user_id.set(None)
        _mod._monitoring_agent_id.set(None)
        _mod._monitoring_conversation_id.set(None)

    def test_normal_flow_with_tenant_id(self):
        """Record is enqueued when tenant_id is present."""
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with (
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_buffer",
                return_value=mock_buffer,
            ),
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_context",
                return_value={
                    "tenant_id": "t-1",
                    "user_id": None,
                    "agent_id": None,
                    "conversation_id": None,
                },
            ),
        ):
            with RecordModelCallContext("embedding", "bge-model") as _:
                pass  # no exception

        mock_buffer.add_record.assert_called_once()
        record = mock_buffer.add_record.call_args[0][0]
        assert record["tenant_id"] == "t-1"
        assert record["is_success"] is True

    def test_no_tenant_id_does_not_raise(self):
        """Missing tenant_id causes graceful skip, no exception."""
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with (
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_buffer",
                return_value=mock_buffer,
            ),
            patch(
                "sdk.nexent.monitor.monitoring.get_monitoring_context",
                return_value={
                    "tenant_id": None,
                    "user_id": None,
                    "agent_id": None,
                    "conversation_id": None,
                },
            ),
        ):
            # Must NOT raise
            with RecordModelCallContext("embedding", "bge-model") as _:
                ...

        mock_buffer.add_record.assert_not_called()

    def test_exception_not_suppressed(self):
        """Exceptions inside the with-block propagate normally."""
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with pytest.raises(ValueError, match="boom"):
            with (
                patch(
                    "sdk.nexent.monitor.monitoring.get_monitoring_buffer",
                    return_value=mock_buffer,
                ),
                patch(
                    "sdk.nexent.monitor.monitoring.get_monitoring_context",
                    return_value={
                        "tenant_id": "t-1",
                        "user_id": None,
                        "agent_id": None,
                        "conversation_id": None,
                    },
                ),
            ):
                with RecordModelCallContext("embedding", "bge-model"):
                    raise ValueError("boom")


# =========================================================================
# TestBufferDegradation  (Tasks 5.1 + 5.2)
# =========================================================================
class TestBufferDegradation:
    """Verify MonitoringRecordBuffer degradation and recovery."""

    def _make_buffer(self):
        """Create a buffer with flush thread disabled."""
        with patch.dict("os.environ", {"ENABLE_MODEL_MONITORING": "false"}):
            buf = MonitoringRecordBuffer()
        buf._enabled = True
        return buf

    def test_consecutive_failures_trigger_degradation(self):
        """After 3 consecutive failures, buffer enters degraded mode."""
        buf = self._make_buffer()
        buf._max_failures = 3

        with patch.object(buf, "_write_batch", side_effect=RuntimeError("DB down")):
            buf._buffer.append({"model_name": "m1"})
            buf._flush_to_db()
            buf._buffer.append({"model_name": "m2"})
            buf._flush_to_db()
            buf._buffer.append({"model_name": "m3"})
            buf._flush_to_db()

        assert buf._consecutive_failures == 3
        assert buf._degraded_until > 0

        buf._buffer.append({"model_name": "m4"})
        with patch.object(buf, "_write_batch") as mock_write:
            buf._flush_to_db()
            mock_write.assert_not_called()

    def test_degradation_recovery(self):
        """After cooldown expires, buffer retries writing."""
        buf = self._make_buffer()
        buf._max_failures = 3
        buf._consecutive_failures = 3
        buf._degraded_until = time.time() - 1

        buf._buffer.append({"model_name": "m1"})

        with patch.object(buf, "_write_batch") as mock_write:
            buf._flush_to_db()
            mock_write.assert_called_once()

        assert buf._consecutive_failures == 0


# =========================================================================
# TestSetMonitoringOperation  (Task 1.1)
# =========================================================================
class TestSetMonitoringOperation:
    """Verify set_monitoring_operation sets ContextVar correctly."""

    def setup_method(self):
        import sdk.nexent.monitor.monitoring as _mod
        _mod._monitoring_operation.set("unknown")
        _mod._monitoring_display_name.set(None)

    def test_sets_operation_value(self):
        set_monitoring_operation("title_generation")
        assert _monitoring_operation.get() == "title_generation"

    def test_sets_display_name(self):
        set_monitoring_operation("chat_completion", display_name="TestModel")
        assert _monitoring_display_name.get() == "TestModel"

    def test_does_not_overwrite_display_name_when_none(self):
        _monitoring_display_name.set("Existing")
        set_monitoring_operation("chat_completion", display_name=None)
        assert _monitoring_display_name.get() == "Existing"


# =========================================================================
# TestMonitoredClientWrapper  (Tasks 1.2-1.4, 4.1-4.3)
# =========================================================================
class TestMonitoredClientWrapper:
    """Verify _MonitoredClient intercepts chat.completions.create calls."""

    def setup_method(self):
        import sdk.nexent.monitor.monitoring as _mod
        _mod._monitoring_tenant_id.set("t-1")
        _mod._monitoring_user_id.set(None)
        _mod._monitoring_agent_id.set(None)
        _mod._monitoring_conversation_id.set(None)
        _mod._monitoring_operation.set("unknown")
        _mod._monitoring_display_name.set("TestModel")
        _mod._monitoring_tracker_snapshot.set(None)

    def _make_monitored_client(self):
        mock_original = MagicMock()
        return _MonitoredClient(mock_original, "test-model", "llm"), mock_original

    def test_non_streaming_creates_record(self):
        monitored, mock_original = self._make_monitored_client()
        mock_response = MagicMock()
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_original.chat.completions.create.return_value = mock_response

        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=mock_buffer):
            _monitoring_operation.set("title_generation")
            result = monitored.chat.completions.create(
                stream=False, messages=[])

        assert result is mock_response
        mock_buffer.add_record.assert_called_once()
        record = mock_buffer.add_record.call_args[0][0]
        assert record["operation"] == "title_generation"
        assert record["input_tokens"] == 10
        assert record["output_tokens"] == 20
        assert record["is_streaming"] is False
        assert record["is_success"] is True
        assert record["display_name"] == "TestModel"
        assert record["model_type"] == "llm"

    def test_non_streaming_error_creates_error_record(self):
        monitored, mock_original = self._make_monitored_client()
        mock_original.chat.completions.create.side_effect = RuntimeError(
            "API down")

        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with (
            patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer",
                  return_value=mock_buffer),
            pytest.raises(RuntimeError, match="API down"),
        ):
            _monitoring_operation.set("connectivity_check")
            monitored.chat.completions.create(stream=False, messages=[])

        mock_buffer.add_record.assert_called_once()
        record = mock_buffer.add_record.call_args[0][0]
        assert record["is_success"] is False
        assert record["is_error"] is True
        assert record["error_type"] == "RuntimeError"
        assert record["operation"] == "connectivity_check"

    def test_streaming_creates_record_after_consumption(self):
        monitored, mock_original = self._make_monitored_client()
        chunks = [MagicMock(
            choices=[MagicMock(delta=MagicMock(content="hi"))],
            usage=MagicMock(prompt_tokens=5, completion_tokens=3))]
        mock_original.chat.completions.create.return_value = iter(chunks)

        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=mock_buffer):
            set_monitoring_context(tenant_id="test-tenant")
            _monitoring_operation.set("chat_completion")
            result = monitored.chat.completions.create(
                stream=True, messages=[])
            consumed = list(result)

        assert len(consumed) == 1
        mock_buffer.add_record.assert_called_once()
        record = mock_buffer.add_record.call_args[0][0]
        assert record["is_streaming"] is True
        assert record["input_tokens"] == 5
        assert record["output_tokens"] == 3
        assert record["ttft_ms"] >= 0
        assert record["operation"] == "chat_completion"

    def test_passthrough_attributes(self):
        monitored, mock_original = self._make_monitored_client()
        mock_original.models.list.return_value = ["model1"]
        assert monitored.models.list() == ["model1"]

    def test_no_tenant_id_skips_record(self):
        import sdk.nexent.monitor.monitoring as _mod
        _mod._monitoring_tenant_id.set(None)

        monitored, mock_original = self._make_monitored_client()
        mock_response = MagicMock()
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_original.chat.completions.create.return_value = mock_response

        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=mock_buffer):
            monitored.chat.completions.create(stream=False, messages=[])

        mock_buffer.add_record.assert_not_called()

    def test_monitoring_disabled_no_record(self):
        monitored, mock_original = self._make_monitored_client()
        mock_response = MagicMock()
        mock_response.usage = None
        mock_original.chat.completions.create.return_value = mock_response

        mock_buffer = MagicMock()
        mock_buffer.is_enabled = False

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=mock_buffer):
            result = monitored.chat.completions.create(
                stream=False, messages=[])

        assert result is mock_response
        mock_buffer.add_record.assert_not_called()


# =========================================================================
# TestEnqueueClientMonitoringRecord  (Task 4.1-4.3)
# =========================================================================
class TestEnqueueClientMonitoringRecord:
    """Verify _enqueue_client_monitoring_record builds correct records."""

    def setup_method(self):
        import sdk.nexent.monitor.monitoring as _mod
        _mod._monitoring_tenant_id.set("t-1")
        _mod._monitoring_user_id.set("u-1")
        _mod._monitoring_agent_id.set(42)
        _mod._monitoring_conversation_id.set(99)
        _mod._monitoring_operation.set("title_generation")
        _mod._monitoring_display_name.set("MyModel")

    def test_full_record_fields(self):
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=mock_buffer):
            _enqueue_client_monitoring_record(
                model_name="test-model",
                model_type="llm",
                request_duration_ms=500,
                ttft_ms=0,
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                generation_rate=0.0,
                is_streaming=False,
            )

        mock_buffer.add_record.assert_called_once()
        record = mock_buffer.add_record.call_args[0][0]
        assert record["model_name"] == "test-model"
        assert record["operation"] == "title_generation"
        assert record["request_duration_ms"] == 500
        assert record["input_tokens"] == 10
        assert record["output_tokens"] == 20
        assert record["total_tokens"] == 30
        assert record["is_streaming"] is False
        assert record["is_success"] is True
        assert record["is_error"] is False
        assert record["model_type"] == "llm"
        assert record["tenant_id"] == "t-1"
        assert record["user_id"] == "u-1"
        assert record["agent_id"] == 42
        assert record["conversation_id"] == 99
        assert record["display_name"] == "MyModel"

    def test_error_record(self):
        mock_buffer = MagicMock()
        mock_buffer.is_enabled = True

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=mock_buffer):
            _enqueue_client_monitoring_record(
                model_name="test-model",
                model_type="vlm",
                request_duration_ms=100,
                ttft_ms=0,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                generation_rate=0.0,
                is_streaming=False,
                error=ConnectionError("timeout"),
            )

        record = mock_buffer.add_record.call_args[0][0]
        assert record["is_success"] is False
        assert record["is_error"] is True
        assert record["error_type"] == "ConnectionError"
        assert record["model_type"] == "vlm"


# =========================================================================
# TestClientLevelIntegrationPaths  (Tasks 5.2-5.6)
# =========================================================================
class TestClientLevelIntegrationPaths:
    """Verify monitoring records are produced through business code paths
    via the client-level _MonitoredClient wrapper."""

    def setup_method(self):
        import sdk.nexent.monitor.monitoring as _mod
        _mod._monitoring_tenant_id.set("t-1")
        _mod._monitoring_user_id.set("u-1")
        _mod._monitoring_agent_id.set(None)
        _mod._monitoring_conversation_id.set(None)
        _mod._monitoring_operation.set("unknown")
        _mod._monitoring_display_name.set(None)
        _mod._monitoring_tracker_snapshot.set(None)

    def _mock_buffer(self):
        buf = MagicMock()
        buf.is_enabled = True
        return buf

    def _fake_response(self, content="hello", input_tokens=5, output_tokens=10):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        resp.choices[0].delta = MagicMock(content=None, reasoning_content=None)
        resp.usage = MagicMock()
        resp.usage.prompt_tokens = input_tokens
        resp.usage.completion_tokens = output_tokens
        return resp

    def _fake_stream_chunks(self, tokens=None, input_tokens=5, output_tokens=10):
        if tokens is None:
            tokens = ["hello", " world"]
        chunks = []
        for t in tokens:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = t
            chunk.choices[0].delta.reasoning_content = None
            chunk.choices[0].delta.role = "assistant"
            chunks.append(chunk)
        last = MagicMock()
        last.choices = [MagicMock()]
        last.choices[0].delta.content = None
        last.choices[0].delta.reasoning_content = None
        last.usage = MagicMock()
        last.usage.prompt_tokens = input_tokens
        last.usage.completion_tokens = output_tokens
        chunks.append(last)
        return chunks

    def test_title_generation_path(self):
        """Task 5.2: call via generate() produces record with operation=title_generation."""
        _monitoring_operation.set("title_generation")
        _monitoring_display_name.set("TestLLM")

        mock_client = MagicMock()
        fake_resp = self._fake_response("New Title")
        mock_client.chat.completions.create.return_value = fake_resp

        monitored = _MonitoredClient(mock_client, "test/repo", "llm")
        buf = self._mock_buffer()

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
            resp = monitored.chat.completions.create(
                stream=False, messages=[{"role": "user", "content": "summarize"}]
            )

        assert resp is fake_resp
        buf.add_record.assert_called_once()
        record = buf.add_record.call_args[0][0]
        assert record["operation"] == "title_generation"
        assert record["display_name"] == "TestLLM"
        assert record["input_tokens"] == 5
        assert record["output_tokens"] == 10
        assert record["is_streaming"] is False

    def test_system_prompt_generation_path(self):
        """Task 5.3: direct client call produces record with operation=system_prompt_generation."""
        _monitoring_operation.set("system_prompt_generation")
        _monitoring_display_name.set("PromptLLM")

        mock_client = MagicMock()
        chunks = self._fake_stream_chunks(["You", " are", " helpful"])
        mock_client.chat.completions.create.return_value = iter(chunks)

        monitored = _MonitoredClient(mock_client, "prompt/model", "llm")
        buf = self._mock_buffer()

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
            _monitoring_tracker_snapshot.set(None)
            stream = monitored.chat.completions.create(
                stream=True, messages=[{"role": "user", "content": "generate"}]
            )
            _ = list(stream)

        buf.add_record.assert_called_once()
        record = buf.add_record.call_args[0][0]
        assert record["operation"] == "system_prompt_generation"
        assert record["display_name"] == "PromptLLM"
        assert record["is_streaming"] is True

    def test_connectivity_check_path(self):
        """Task 5.4: connectivity check produces record with operation=connectivity_check."""
        _monitoring_operation.set("connectivity_check")

        mock_client = MagicMock()
        fake_resp = self._fake_response("Hi", input_tokens=2, output_tokens=1)
        mock_client.chat.completions.create.return_value = fake_resp

        monitored = _MonitoredClient(mock_client, "health/model", "llm")
        buf = self._mock_buffer()

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
            monitored.chat.completions.create(
                stream=False, messages=[{"role": "user", "content": "Hello"}], max_tokens=5
            )

        buf.add_record.assert_called_once()
        record = buf.add_record.call_args[0][0]
        assert record["operation"] == "connectivity_check"
        assert record["is_success"] is True
        assert record["input_tokens"] == 2
        assert record["output_tokens"] == 1
        assert record["is_streaming"] is False

    def test_connectivity_check_vlm_path(self):
        """Task 5.4 variant: VLM connectivity check uses model_type=vlm."""
        _monitoring_operation.set("connectivity_check")

        mock_client = MagicMock()
        fake_resp = self._fake_response("ok", input_tokens=3, output_tokens=1)
        mock_client.chat.completions.create.return_value = fake_resp

        monitored = _MonitoredClient(mock_client, "vlm/model", "vlm")
        buf = self._mock_buffer()

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
            monitored.chat.completions.create(
                stream=False, messages=[{"role": "user", "content": "Hello"}], max_tokens=5
            )

        record = buf.add_record.call_args[0][0]
        assert record["operation"] == "connectivity_check"
        assert record["model_type"] == "vlm"

    def test_chat_completion_exactly_one_record(self):
        """Task 5.5: agent __call__ streaming path produces exactly 1 record."""
        _monitoring_operation.set("chat_completion")
        _monitoring_display_name.set("AgentModel")

        mock_client = MagicMock()
        chunks = self._fake_stream_chunks(
            ["token1", "token2"], input_tokens=100, output_tokens=50)
        mock_client.chat.completions.create.return_value = iter(chunks)

        monitored = _MonitoredClient(mock_client, "agent/model", "llm")
        buf = self._mock_buffer()

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
            set_monitoring_context(tenant_id="test-tenant")
            stream = monitored.chat.completions.create(
                stream=True, messages=[{"role": "user", "content": "Hello"}]
            )
            _ = list(stream)

        assert buf.add_record.call_count == 1
        record = buf.add_record.call_args[0][0]
        assert record["operation"] == "chat_completion"
        assert record["input_tokens"] == 100
        assert record["output_tokens"] == 50
        assert record["ttft_ms"] >= 0
        assert record["generation_rate"] >= 0
        assert record["is_streaming"] is True
        assert record["display_name"] == "AgentModel"

    def test_monitoring_disabled_zero_records(self):
        """Task 5.6: ENABLE_MODEL_MONITORING=false produces zero records."""
        _monitoring_operation.set("chat_completion")

        mock_client = MagicMock()
        fake_resp = self._fake_response("test")
        mock_client.chat.completions.create.return_value = fake_resp

        monitored = _MonitoredClient(mock_client, "test/model", "llm")
        buf = MagicMock()
        buf.is_enabled = False

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
            _ = monitored.chat.completions.create(stream=False, messages=[])

        buf.add_record.assert_not_called()

    def test_monitoring_disabled_streaming_zero_records(self):
        """Task 5.6 variant: streaming also produces zero records when disabled."""
        _monitoring_operation.set("title_generation")

        mock_client = MagicMock()
        chunks = self._fake_stream_chunks(["a", "b"])
        mock_client.chat.completions.create.return_value = iter(chunks)

        monitored = _MonitoredClient(mock_client, "test/model", "llm")
        buf = MagicMock()
        buf.is_enabled = False

        with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
            stream = monitored.chat.completions.create(
                stream=True, messages=[])
            _ = list(stream)

        buf.add_record.assert_not_called()

    def test_no_tenant_id_zero_records_all_paths(self):
        """Task 5.6 variant: no tenant_id means zero records regardless of operation."""
        import sdk.nexent.monitor.monitoring as _mod
        _mod._monitoring_tenant_id.set(None)

        mock_client = MagicMock()
        fake_resp = self._fake_response("test")
        mock_client.chat.completions.create.return_value = fake_resp

        for op in ["chat_completion", "title_generation", "system_prompt_generation", "connectivity_check"]:
            _monitoring_operation.set(op)
            monitored = _MonitoredClient(mock_client, "test/model", "llm")
            buf = self._mock_buffer()

            with patch("sdk.nexent.monitor.monitoring.get_monitoring_buffer", return_value=buf):
                monitored.chat.completions.create(stream=False, messages=[])

            buf.add_record.assert_not_called()
