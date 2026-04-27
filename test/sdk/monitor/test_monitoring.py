"""
Comprehensive unit tests for SDK monitoring module (OTLP-based).

Tests cover:
- MonitoringConfig dataclass (OTLP fields)
- MonitoringManager singleton behavior
- OTLP telemetry initialization
- LLM request tracing with OpenInference semantics
- Agent step and tool tracing
- Token tracking and performance metrics
- Decorator functionality
- Error handling and graceful degradation
"""

from sdk.nexent.monitor.monitoring import (
    MonitoringConfig,
    MonitoringManager,
    LLMTokenTracker,
    get_monitoring_manager,
    is_opentelemetry_available
)
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch


class TestMonitoringConfig:
    """Test MonitoringConfig dataclass with OTLP fields."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MonitoringConfig()

        assert config.enable_telemetry is False
        assert config.service_name == "nexent-backend"
        assert config.otlp_endpoint == "http://localhost:4318"
        assert config.otlp_protocol == "http"
        assert config.otlp_headers == {}
        assert config.telemetry_sample_rate == 1.0
        assert config.llm_slow_request_threshold_seconds == 5.0
        assert config.llm_slow_token_rate_threshold == 10.0

    def test_custom_config(self):
        """Test configuration with custom OTLP values."""
        config = MonitoringConfig(
            enable_telemetry=True,
            service_name="test-service",
            otlp_endpoint="https://phoenix.arize.com/v1",
            otlp_protocol="grpc",
            otlp_headers={"x-api-key": "test-key"},
            telemetry_sample_rate=0.5,
            llm_slow_request_threshold_seconds=10.0,
            llm_slow_token_rate_threshold=20.0
        )

        assert config.enable_telemetry is True
        assert config.service_name == "test-service"
        assert config.otlp_endpoint == "https://phoenix.arize.com/v1"
        assert config.otlp_protocol == "grpc"
        assert config.otlp_headers == {"x-api-key": "test-key"}
        assert config.telemetry_sample_rate == 0.5
        assert config.llm_slow_request_threshold_seconds == 10.0
        assert config.llm_slow_token_rate_threshold == 20.0

    def test_invalid_protocol_defaults_to_http(self):
        """Test that invalid protocol defaults to http."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            config = MonitoringConfig(
                enable_telemetry=True,
                otlp_protocol="invalid"
            )
            assert config.otlp_protocol == "http"


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

    def test_is_enabled_property(self):
        """Test is_enabled property behavior."""
        manager = MonitoringManager()

        assert manager.is_enabled is False

        config_disabled = MonitoringConfig(enable_telemetry=False)
        manager.configure(config_disabled)
        assert manager.is_enabled is False

    @patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', False)
    def test_telemetry_disabled_when_otlp_not_available(self):
        """Test telemetry is disabled when OpenTelemetry not installed."""
        config = MonitoringConfig(enable_telemetry=True)
        assert config.enable_telemetry is False

    @patch('sdk.nexent.monitor.monitoring.trace')
    @patch('sdk.nexent.monitor.monitoring.metrics')
    @patch('sdk.nexent.monitor.monitoring.TracerProvider')
    @patch('sdk.nexent.monitor.monitoring.MeterProvider')
    @patch('sdk.nexent.monitor.monitoring.OTLPSpanExporterHTTP')
    @patch('sdk.nexent.monitor.monitoring.OTLPMetricExporterHTTP')
    @patch('sdk.nexent.monitor.monitoring.BatchSpanProcessor')
    @patch('sdk.nexent.monitor.monitoring.PeriodicExportingMetricReader')
    @patch('sdk.nexent.monitor.monitoring.Resource')
    @patch('sdk.nexent.monitor.monitoring.RequestsInstrumentor')
    def test_init_telemetry_http(self, mock_requests_instr, mock_resource,
                                  mock_periodic_reader, mock_batch_processor,
                                  mock_metric_exporter_http, mock_span_exporter_http,
                                  mock_meter_provider, mock_tracer_provider,
                                  mock_metrics, mock_trace):
        """Test telemetry initialization with HTTP protocol."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(
                enable_telemetry=True,
                service_name="test-service",
                otlp_endpoint="http://localhost:4318",
                otlp_protocol="http"
            )

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

            manager.configure(config)

            mock_resource.create.assert_called()
            mock_tracer_provider.assert_called_once()
            mock_span_exporter_http.assert_called_once()
            mock_batch_processor.assert_called_once()
            mock_requests_instr().instrument.assert_called_once()

    @patch('sdk.nexent.monitor.monitoring.trace')
    @patch('sdk.nexent.monitor.monitoring.metrics')
    @patch('sdk.nexent.monitor.monitoring.TracerProvider')
    @patch('sdk.nexent.monitor.monitoring.MeterProvider')
    @patch('sdk.nexent.monitor.monitoring.OTLPSpanExporterGRPC')
    @patch('sdk.nexent.monitor.monitoring.OTLPMetricExporterGRPC')
    @patch('sdk.nexent.monitor.monitoring.BatchSpanProcessor')
    @patch('sdk.nexent.monitor.monitoring.PeriodicExportingMetricReader')
    @patch('sdk.nexent.monitor.monitoring.Resource')
    def test_init_telemetry_grpc(self, mock_resource, mock_periodic_reader,
                                 mock_batch_processor, mock_metric_exporter_grpc,
                                 mock_span_exporter_grpc, mock_meter_provider,
                                 mock_tracer_provider, mock_metrics, mock_trace):
        """Test telemetry initialization with gRPC protocol."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(
                enable_telemetry=True,
                service_name="test-service",
                otlp_endpoint="http://localhost:4317",
                otlp_protocol="grpc"
            )

            mock_resource_instance = MagicMock()
            mock_resource.create.return_value = mock_resource_instance
            mock_tracer_provider.return_value = MagicMock()
            mock_meter_provider.return_value = MagicMock()
            mock_trace.get_tracer.return_value = MagicMock()
            mock_metrics.get_meter.return_value = MagicMock()

            manager.configure(config)

            mock_span_exporter_grpc.assert_called_once()
            mock_metric_exporter_grpc.assert_called_once()

    def test_init_telemetry_exception_handling(self):
        """Test telemetry initialization handles exceptions gracefully."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)

            with patch('sdk.nexent.monitor.monitoring.Resource.create', side_effect=Exception("Test error")):
                manager.configure(config)

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_llm_request_openinference_attrs(self, mock_trace):
        """Test LLM request tracing uses OpenInference attribute names."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            manager._tracer = MagicMock()

            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

            with manager.trace_llm_request("test_op", "gpt-4", extra="value") as span:
                pass

            call_args = manager._tracer.start_as_current_span.call_args
            attributes = call_args[1]['attributes']

            assert "llm.model_name" in attributes
            assert attributes["llm.model_name"] == "gpt-4"
            assert "llm.operation.name" in attributes
            assert attributes["llm.operation.name"] == "test_op"


class TestAgentStepTracing:
    """Test Agent step tracing functionality."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_agent_step_tool_call(self, mock_trace):
        """Test tracing agent tool call step."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            manager._tracer = MagicMock()

            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

            with manager.trace_agent_step("web_search", "test_agent", "tool_call") as span:
                pass

            call_args = manager._tracer.start_as_current_span.call_args
            attributes = call_args[1]['attributes']

            assert "agent.name" in attributes
            assert attributes["agent.name"] == "test_agent"
            assert "agent.step.name" in attributes
            assert attributes["agent.step.name"] == "web_search"
            assert "agent.step.type" in attributes
            assert attributes["agent.step.type"] == "tool_call"

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_agent_step_reasoning(self, mock_trace):
        """Test tracing agent reasoning step."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            manager._tracer = MagicMock()

            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

            with manager.trace_agent_step("analyze_query", "test_agent", "reasoning") as span:
                pass

            call_args = manager._tracer.start_as_current_span.call_args
            attributes = call_args[1]['attributes']

            assert attributes["agent.step.type"] == "reasoning"

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_agent_step_action_selection(self, mock_trace):
        """Test tracing agent action selection step."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            manager._tracer = MagicMock()

            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

            with manager.trace_agent_step("decide_next", "test_agent", "action_selection") as span:
                pass

            call_args = manager._tracer.start_as_current_span.call_args
            attributes = call_args[1]['attributes']

            assert attributes["agent.step.type"] == "action_selection"

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_tool_call_with_input_output(self, mock_trace):
        """Test tracing tool call with input and output."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            manager._tracer = MagicMock()

            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

            tool_input = {"query": "test search", "limit": 10}

            with manager.trace_tool_call("web_search", "test_agent", tool_input) as span:
                manager.set_tool_output({"results": ["item1", "item2"]})

            call_args = manager._tracer.start_as_current_span.call_args
            attributes = call_args[1]['attributes']

            assert "agent.tool.name" in attributes
            assert attributes["agent.tool.name"] == "web_search"
            assert "agent.tool.input" in attributes
            assert "query" in attributes["agent.tool.input"]

            mock_span.set_attribute.assert_called()

    def test_trace_agent_step_disabled(self):
        """Test agent step tracing when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        with manager.trace_agent_step("test_step", "test_agent", "tool_call") as span:
            assert span is None

    def test_trace_tool_call_disabled(self):
        """Test tool call tracing when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        with manager.trace_tool_call("test_tool", "test_agent", {"input": "data"}) as span:
            assert span is None


class TestAgentMetrics:
    """Test Agent metrics functionality."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    def test_record_agent_metrics_duration(self):
        """Test recording agent execution duration."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            manager._agent_execution_duration = MagicMock()

            manager.record_agent_metrics("duration", 1.5, {"agent.name": "test"})

            manager._agent_execution_duration.record.assert_called_once()


class TestLLMTokenTracker:
    """Test LLMTokenTracker with OpenInference semantics."""

    def setup_method(self):
        """Set up test fixtures."""
        self.manager = MagicMock()
        self.span = MagicMock()
        self.model_name = "gpt-4"

    def test_record_completion_openinference_attrs(self):
        """Test completion uses OpenInference attribute names."""
        self.manager.is_enabled = True

        with patch('time.time', side_effect=[123.456, 123.956, 125.456]):
            tracker = LLMTokenTracker(self.manager, self.model_name, self.span)
            tracker.record_first_token()
            tracker.token_count = 10

            tracker.record_completion(input_tokens=20, output_tokens=30)

            expected_attrs = {
                "llm.token_count.prompt": 20,
                "llm.token_count.completion": 30,
                "llm.token_count.total": 50,
                "llm.generation_rate": 5.0,
                "llm.duration.total": 2.0,
                "llm.time_to_first_token": 0.5
            }
            self.span.set_attributes.assert_called_once_with(expected_attrs)

    def test_record_metrics_openinference_labels(self):
        """Test metrics recording uses OpenInference labels."""
        self.manager.is_enabled = True

        tracker = LLMTokenTracker(self.manager, self.model_name, self.span)

        with patch('time.time', side_effect=[123.456, 124.456]):
            tracker.record_completion(input_tokens=10, output_tokens=5)

            self.manager.record_llm_metrics.assert_any_call(
                "tokens_prompt", 10, {"llm.model_name": self.model_name}
            )
            self.manager.record_llm_metrics.assert_any_call(
                "tokens_completion", 5, {"llm.model_name": self.model_name}
            )


class TestDecorators:
    """Test monitoring decorators."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    def test_monitor_endpoint_decorator_sync(self):
        """Test monitor_endpoint decorator with sync function."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        @manager.monitor_endpoint("test_operation")
        def test_function(param1, param2="default"):
            return {"result": "success"}

        result = test_function("value1", param2="value2")
        assert result == {"result": "success"}

    def test_monitor_endpoint_decorator_async(self):
        """Test monitor_endpoint decorator with async function."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        @manager.monitor_endpoint("test_operation")
        async def test_function(param1, param2="default"):
            return {"result": "success"}

        result = asyncio.run(test_function("value1", param2="value2"))
        assert result == {"result": "success"}

    def test_monitor_llm_call_decorator(self):
        """Test monitor_llm_call decorator."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        @manager.monitor_llm_call("gpt-4", "completion")
        def test_llm_function(**kwargs):
            return {"result": "llm_success"}

        result = test_llm_function()
        assert result == {"result": "llm_success"}

    def test_monitor_agent_execution_decorator(self):
        """Test monitor_agent_execution decorator."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        @manager.monitor_agent_execution("test_agent")
        def test_agent_function():
            return {"result": "agent_success"}

        result = test_agent_function()
        assert result == {"result": "agent_success"}


class TestGlobalFunctions:
    """Test global functions."""

    def test_get_monitoring_manager_singleton(self):
        """Test get_monitoring_manager returns singleton."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

        manager1 = get_monitoring_manager()
        manager2 = get_monitoring_manager()

        assert manager1 is manager2
        assert isinstance(manager1, MonitoringManager)

    def test_is_opentelemetry_available(self):
        """Test is_opentelemetry_available function."""
        result = is_opentelemetry_available()
        assert isinstance(result, bool)


class TestProtocolSwitching:
    """Test HTTP/gRPC protocol switching."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    @patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True)
    @patch('sdk.nexent.monitor.monitoring.OTLPSpanExporterHTTP')
    def test_http_protocol_uses_http_exporter(self, mock_http_exporter):
        """Test that http protocol uses HTTP exporter."""
        manager = MonitoringManager()
        config = MonitoringConfig(
            enable_telemetry=True,
            otlp_endpoint="http://localhost:4318",
            otlp_protocol="http"
        )

        with patch('sdk.nexent.monitor.monitoring.TracerProvider'), \
             patch('sdk.nexent.monitor.monitoring.Resource.create'), \
             patch('sdk.nexent.monitor.monitoring.trace'), \
             patch('sdk.nexent.monitor.monitoring.metrics'), \
             patch('sdk.nexent.monitor.monitoring.MeterProvider'), \
             patch('sdk.nexent.monitor.monitoring.BatchSpanProcessor'), \
             patch('sdk.nexent.monitor.monitoring.RequestsInstrumentor'):

            manager.configure(config)

            mock_http_exporter.assert_called_once()

    @patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True)
    @patch('sdk.nexent.monitor.monitoring.OTLPSpanExporterGRPC')
    def test_grpc_protocol_uses_grpc_exporter(self, mock_grpc_exporter):
        """Test that grpc protocol uses gRPC exporter."""
        manager = MonitoringManager()
        config = MonitoringConfig(
            enable_telemetry=True,
            otlp_endpoint="http://localhost:4317",
            otlp_protocol="grpc"
        )

        with patch('sdk.nexent.monitor.monitoring.TracerProvider'), \
             patch('sdk.nexent.monitor.monitoring.Resource.create'), \
             patch('sdk.nexent.monitor.monitoring.trace'), \
             patch('sdk.nexent.monitor.monitoring.metrics'), \
             patch('sdk.nexent.monitor.monitoring.MeterProvider'), \
             patch('sdk.nexent.monitor.monitoring.BatchSpanProcessor'), \
             patch('sdk.nexent.monitor.monitoring.RequestsInstrumentor'):

            manager.configure(config)

            mock_grpc_exporter.assert_called_once()


class TestErrorHandling:
    """Test error handling and graceful degradation."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    def test_methods_work_when_disabled(self):
        """Test all methods work gracefully when monitoring is disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        manager.add_span_event("test_event")
        manager.set_span_attributes(key="value")
        manager.record_llm_metrics("ttft", 0.5, {})
        manager.record_agent_metrics("duration", 1.0, {})

        with manager.trace_llm_request("test", "model") as span:
            assert span is None

        with manager.trace_agent_step("step", "agent", "tool_call") as span:
            assert span is None

        with manager.trace_tool_call("tool", "agent", {"input": "data"}) as span:
            assert span is None

    def test_decorators_propagate_exceptions(self):
        """Test decorators properly propagate exceptions."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        @manager.monitor_endpoint("test")
        def error_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            error_func()

    def test_exporter_error_does_not_crash(self):
        """Test exporter errors don't crash application."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()

            with patch('sdk.nexent.monitor.monitoring.Resource.create', side_effect=Exception("Export error")):
                config = MonitoringConfig(enable_telemetry=True)
                manager.configure(config)

                assert manager._tracer is None