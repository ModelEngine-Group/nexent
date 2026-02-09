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
    get_monitoring_manager
)
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch


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
