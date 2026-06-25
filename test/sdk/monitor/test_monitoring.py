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
    AgentRunMetadata,
    LLMTokenTracker,
    get_monitoring_manager,
    is_opentelemetry_available,
    _detect_model_type,
    _enqueue_monitoring_record,
    RecordModelCallContext,
    MonitoringRecordBuffer,
    get_monitoring_buffer,
    set_monitoring_context,
    get_monitoring_context,
    get_agent_monitoring_context,
    agent_monitoring_context,
    _monitoring_buffer,
    _MonitoredClient,
    _MonitoredChatCompletions,
    _MonitoredStreamIterator,
    _monitoring_operation,
    _monitoring_display_name,
    set_monitoring_operation,
    _enqueue_client_monitoring_record,
    _build_fastapi_excluded_urls,
    OPENINFERENCE_SPAN_KIND,
    OPENINFERENCE_SPAN_KIND_AGENT,
    OPENINFERENCE_SPAN_KIND_CHAIN,
    OPENINFERENCE_SPAN_KIND_LLM,
    OPENINFERENCE_SPAN_KIND_TOOL,
    OPENINFERENCE_SPAN_KIND_RETRIEVER,
    OPENINFERENCE_SESSION_ID,
    OPENINFERENCE_USER_ID,
    OPENINFERENCE_METADATA,
    OPENINFERENCE_TAG_TAGS,
    OPENINFERENCE_INPUT_VALUE,
    OPENINFERENCE_OUTPUT_VALUE,
)
import pytest
import asyncio
import json
import time
import sys
import threading
from unittest.mock import Mock, MagicMock, patch, call


class TestMonitoringConfig:
    """Test MonitoringConfig dataclass with OTLP fields."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MonitoringConfig()

        assert config.enable_telemetry is False
        assert config.service_name == "nexent-backend"
        assert config.provider == "otlp"
        assert config.otlp_endpoint == "http://localhost:4318"
        assert config.get_trace_endpoint() == "http://localhost:4318/v1/traces"
        assert config.get_metric_endpoint() == "http://localhost:4318/v1/metrics"
        assert config.otlp_protocol == "http"
        assert config.otlp_headers == {}
        assert config.export_traces is True
        assert config.export_metrics is True
        assert config.instrument_requests is False
        assert config.fastapi_included_urls == ""
        assert config.fastapi_excluded_urls == ""
        assert config.fastapi_exclude_spans == ["receive", "send"]
        assert config.telemetry_sample_rate == 1.0
        assert config.trace_content_mode == "summary"
        assert config.trace_max_chars == 4000
        assert config.trace_max_items == 20

    def test_custom_config(self):
        """Test configuration with custom OTLP values."""
        config = MonitoringConfig(
            enable_telemetry=True,
            service_name="test-service",
            provider="phoenix",
            otlp_endpoint="https://app.phoenix.arize.com",
            otlp_protocol="grpc",
            otlp_headers={"Authorization": "Bearer test-key"},
            export_metrics=False,
            instrument_requests=True,
            fastapi_included_urls="/agent/run",
            fastapi_excluded_urls="/agent/run",
            fastapi_exclude_spans="send",
            project_name="nexent-test",
            telemetry_sample_rate=0.5,
            trace_content_mode="metrics",
            trace_max_chars="256",
            trace_max_items="5",
        )

        assert config.enable_telemetry is True
        assert config.service_name == "test-service"
        assert config.provider == "phoenix"
        assert config.otlp_endpoint == "https://app.phoenix.arize.com"
        assert config.otlp_protocol == "http"
        assert config.otlp_headers == {"Authorization": "Bearer test-key"}
        assert config.export_metrics is False
        assert config.instrument_requests is True
        assert config.fastapi_included_urls == "/agent/run"
        assert config.fastapi_excluded_urls == "/agent/run"
        assert config.fastapi_exclude_spans == ["send"]
        assert config.project_name == "nexent-test"
        assert config.telemetry_sample_rate == 0.5
        assert config.trace_content_mode == "metrics"
        assert config.trace_max_chars == 256
        assert config.trace_max_items == 5

    def test_invalid_trace_content_mode_defaults_to_summary(self):
        """Invalid trace payload mode falls back to safe summary mode."""
        config = MonitoringConfig(trace_content_mode="invalid")

        assert config.trace_content_mode == "summary"

    def test_invalid_protocol_defaults_to_http(self):
        """Test that invalid protocol defaults to http."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            config = MonitoringConfig(
                enable_telemetry=True,
                otlp_protocol="invalid"
            )
            assert config.otlp_protocol == "http"

    def test_langsmith_provider_is_supported(self):
        """Test LangSmith is a supported OTLP provider profile."""
        config = MonitoringConfig(provider="langsmith")

        assert config.provider == "langsmith"

    def test_zipkin_provider_is_supported(self):
        """Test Zipkin is a supported OTLP provider profile."""
        config = MonitoringConfig(provider="zipkin")

        assert config.provider == "zipkin"

    def test_langsmith_grpc_protocol_defaults_to_http(self):
        """LangSmith OTLP profile uses HTTP trace ingestion."""
        config = MonitoringConfig(provider="langsmith", otlp_protocol="grpc")

        assert config.otlp_protocol == "http"

    def test_signal_endpoint_derivation_from_base_endpoint(self):
        """Test HTTP endpoints are derived from a base OTLP endpoint."""
        config = MonitoringConfig(
            otlp_endpoint="https://cloud.langfuse.com/api/public/otel"
        )

        assert config.get_trace_endpoint() == "https://cloud.langfuse.com/api/public/otel/v1/traces"
        assert config.get_metric_endpoint() == "https://cloud.langfuse.com/api/public/otel/v1/metrics"

    def test_signal_endpoint_derivation_from_existing_signal_endpoint(self):
        """Test signal endpoints are not duplicated when already provided."""
        config = MonitoringConfig(
            otlp_endpoint="https://collector.example.com/v1/traces"
        )

        assert config.get_trace_endpoint() == "https://collector.example.com/v1/traces"
        assert config.get_metric_endpoint() == "https://collector.example.com/v1/metrics"

    def test_fastapi_excluded_urls_excluded_only(self):
        assert _build_fastapi_excluded_urls("", "/health,/metrics") == "/health,/metrics"

    def test_fastapi_excluded_urls_included_and_excluded(self):
        excluded_urls = _build_fastapi_excluded_urls(
            "/agent/run,/conversation",
            "/health",
        )

        assert excluded_urls == (
            "/health,^(?!.*(?:(?:/agent/run)|(?:/conversation))).*$"
        )

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
            mock_requests_instr().instrument.assert_not_called()

    @patch('sdk.nexent.monitor.monitoring.trace')
    @patch('sdk.nexent.monitor.monitoring.metrics')
    @patch('sdk.nexent.monitor.monitoring.TracerProvider')
    @patch('sdk.nexent.monitor.monitoring.MeterProvider')
    @patch('sdk.nexent.monitor.monitoring.OTLPSpanExporterHTTP')
    @patch('sdk.nexent.monitor.monitoring.BatchSpanProcessor')
    @patch('sdk.nexent.monitor.monitoring.Resource')
    @patch('sdk.nexent.monitor.monitoring.RequestsInstrumentor')
    def test_init_telemetry_requests_instrumentation_opt_in(
        self,
        mock_requests_instr,
        mock_resource,
        mock_batch_processor,
        mock_span_exporter_http,
        mock_meter_provider,
        mock_tracer_provider,
        mock_metrics,
        mock_trace,
    ):
        """Test requests auto instrumentation is opt-in."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(
                enable_telemetry=True,
                instrument_requests=True,
                export_metrics=False,
            )

            mock_resource.create.return_value = MagicMock()
            mock_tracer_provider.return_value = MagicMock()
            mock_meter_provider.return_value = MagicMock()
            mock_trace.get_tracer.return_value = MagicMock()
            mock_metrics.get_meter.return_value = MagicMock()

            manager.configure(config)

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

    def test_setup_fastapi_app_excludes_streaming_internal_spans(self):
        """Test FastAPI instrumentation suppresses noisy ASGI send/receive spans."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            manager.configure(MonitoringConfig(
                enable_telemetry=True,
                fastapi_included_urls="/agent/run",
                fastapi_excluded_urls="/health",
                fastapi_exclude_spans=["receive", "send"],
            ))
            app = MagicMock()
            calls = {}

            def fake_instrument_app(app_arg, excluded_urls=None, exclude_spans=None):
                calls["app"] = app_arg
                calls["excluded_urls"] = excluded_urls
                calls["exclude_spans"] = exclude_spans

            with patch(
                'sdk.nexent.monitor.monitoring.FastAPIInstrumentor.instrument_app',
                new=fake_instrument_app,
            ):
                result = manager.setup_fastapi_app(app)

            assert result is True
            assert calls["app"] is app
            assert calls["excluded_urls"] == (
                "/health,^(?!.*(?:(?:/agent/run))).*$"
            )
            assert calls["exclude_spans"] == ["receive", "send"]

    def test_setup_fastapi_app_uses_excluded_url_filters(self):
        """FastAPI instrumentation is controlled by URL filters."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            manager.configure(MonitoringConfig(
                enable_telemetry=True,
                fastapi_excluded_urls="/health",
            ))
            app = MagicMock()

            with patch(
                'sdk.nexent.monitor.monitoring.FastAPIInstrumentor.instrument_app',
            ) as mock_instrument:
                result = manager.setup_fastapi_app(app)

            assert result is True
            mock_instrument.assert_called_once()

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
            assert attributes[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_LLM

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_llm_request_summarizes_input_payload(self, mock_trace):
        """LLM input.value uses the same bounded payload policy as other spans."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            manager.configure(MonitoringConfig(
                enable_telemetry=True,
                trace_max_items=1,
            ))
            manager._tracer = MagicMock()
            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)

            with manager.trace_llm_request(
                "test_op",
                "gpt-4",
                **{
                    OPENINFERENCE_INPUT_VALUE: [
                        {"role": "system", "content": "secret-system"},
                        {"role": "user", "content": "secret-user"},
                    ]
                },
            ):
                pass

            attributes = manager._tracer.start_as_current_span.call_args.kwargs["attributes"]
            input_preview = json.loads(attributes[OPENINFERENCE_INPUT_VALUE])
            assert input_preview == [{"role": "system", "content": "secret-system"}]
            assert attributes["input.item_count"] == 2
            assert attributes["input.truncated"] is True
            assert "secret-user" not in attributes[OPENINFERENCE_INPUT_VALUE]

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_set_openinference_agent_context_attrs(self, mock_trace):
        """Test Phoenix/OpenInference agent context attributes are added to current span."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)

            mock_span = MagicMock()
            mock_trace.get_current_span.return_value = mock_span

            manager.set_openinference_agent_context(
                agent_id=1,
                conversation_id=2,
                user_id="user-1",
                tenant_id="tenant-1",
                query="hello",
                is_debug=False,
                memory_enabled=True,
            )

            attrs = mock_span.set_attributes.call_args.args[0]
            assert attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_AGENT
            assert attrs[OPENINFERENCE_SESSION_ID] == "2"
            assert attrs[OPENINFERENCE_USER_ID] == "user-1"
            assert attrs[OPENINFERENCE_INPUT_VALUE] == "hello"
            assert "agent_id:1" in json.loads(attrs[OPENINFERENCE_TAG_TAGS])
            metadata = json.loads(attrs[OPENINFERENCE_METADATA])
            assert metadata["agent_id"] == 1
            assert metadata["tenant_id"] == "tenant-1"

            manager.set_openinference_agent_context(
                agent_id=1,
                conversation_id=2,
                user_id="user-1",
                tenant_id="tenant-1",
                span_kind=OPENINFERENCE_SPAN_KIND_CHAIN,
            )
            attrs = mock_span.set_attributes.call_args.args[0]
            assert attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_CHAIN

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_set_openinference_output_attrs(self, mock_trace):
        """Test OpenInference output helper writes Phoenix-friendly attributes."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            mock_span = MagicMock()
            mock_trace.get_current_span.return_value = mock_span

            manager.set_openinference_output({"answer": "ok"})
            output_attrs = mock_span.set_attributes.call_args.args[0]
            assert json.loads(output_attrs[OPENINFERENCE_OUTPUT_VALUE]) == {"answer": "ok"}
            assert output_attrs["output.type"] == "dict"
            assert output_attrs["output.item_count"] == 1

    def test_openinference_input_output_respect_metrics_mode(self):
        """Generic OpenInference input/output fields omit payload content in metrics mode."""
        manager = MonitoringManager()
        manager.configure(MonitoringConfig(
            enable_telemetry=False,
            trace_content_mode="metrics",
        ))

        attrs = manager.build_openinference_attributes(
            span_kind=OPENINFERENCE_SPAN_KIND_AGENT,
            input_value={"prompt": "secret"},
            output_value={"answer": "secret"},
        )

        assert OPENINFERENCE_INPUT_VALUE not in attrs
        assert OPENINFERENCE_OUTPUT_VALUE not in attrs
        assert attrs["input.type"] == "dict"
        assert attrs["input.size_chars"] > 0
        assert attrs["output.type"] == "dict"
        assert attrs["output.size_chars"] > 0


class TestToolCallTracing:
    """Test tool call tracing functionality."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    def test_trace_payload_summary_for_dict_list_and_string(self):
        """Payload summaries include previews and structured metadata."""
        manager = MonitoringManager()
        manager.configure(MonitoringConfig(trace_max_items=1))

        dict_summary = manager._trace_payload_summary({"query": "hello", "limit": 10})
        assert json.loads(dict_summary["preview"]) == {"query": "hello"}
        assert dict_summary["type"] == "dict"
        assert dict_summary["item_count"] == 2
        assert dict_summary["keys"] == ["query"]
        assert dict_summary["truncated"] is True

        list_summary = manager._trace_payload_summary(["a", "b"])
        assert json.loads(list_summary["preview"]) == ["a"]
        assert list_summary["type"] == "list"
        assert list_summary["item_count"] == 2
        assert list_summary["truncated"] is True

        string_summary = manager._trace_payload_summary("hello")
        assert string_summary["preview"] == "hello"
        assert string_summary["type"] == "str"
        assert string_summary["size_chars"] == 5

    def test_trace_payload_summary_truncates_long_preview(self):
        """Long payload previews are bounded by MONITORING_TRACE_MAX_CHARS."""
        manager = MonitoringManager()
        manager.configure(MonitoringConfig(trace_max_chars=8))

        summary = manager._trace_payload_summary({"text": "x" * 100})

        assert summary["truncated"] is True
        assert summary["preview"].endswith("...[truncated]")
        assert summary["size_chars"] > len(summary["preview"])

    def test_trace_payload_metrics_mode_omits_preview(self):
        """Metrics mode records only structure/size metadata."""
        manager = MonitoringManager()
        manager.configure(MonitoringConfig(trace_content_mode="metrics"))

        attrs = manager._trace_payload_attributes("agent.tool.output", {"answer": "ok"})

        assert "agent.tool.output.preview" not in attrs
        assert attrs["agent.tool.output.type"] == "dict"
        assert attrs["agent.tool.output.item_count"] == 1
        assert attrs["agent.tool.output.truncated"] is True

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
            mock_span.is_recording.return_value = True
            mock_trace.get_current_span.return_value = mock_span

            tool_input = {"query": "test search", "limit": 10}

            with manager.trace_tool_call("web_search", "test_agent", tool_input) as span:
                manager.set_tool_output({"results": ["item1", "item2"]})

            call_args = manager._tracer.start_as_current_span.call_args
            attributes = call_args[1]['attributes']

            assert "agent.tool.name" in attributes
            assert attributes["agent.tool.name"] == "web_search"
            assert "agent.tool.input" in attributes
            assert "query" in attributes["agent.tool.input"]
            assert attributes["agent.tool.input.type"] == "dict"
            assert attributes["agent.tool.input.item_count"] == 2
            assert attributes["agent.tool.input.truncated"] is False
            assert json.loads(attributes["agent.tool.input.keys"]) == ["query", "limit"]
            assert attributes[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_TOOL
            assert attributes["tool.name"] == "web_search"
            assert "query" in attributes["tool.parameters"]
            assert "query" in attributes[OPENINFERENCE_INPUT_VALUE]

            output_attrs = mock_span.set_attributes.call_args.args[0]
            assert json.loads(output_attrs[OPENINFERENCE_OUTPUT_VALUE]) == {"results": ["item1", "item2"]}
            assert output_attrs["agent.tool.output.type"] == "dict"
            assert output_attrs["agent.tool.output.item_count"] == 1
            assert output_attrs["agent.tool.success"] is True
            mock_span.set_attribute.assert_any_call("agent.tool.success", True)
            assert any(
                call_args.args[0] == "agent.tool.duration_ms"
                for call_args in mock_span.set_attribute.call_args_list
            )

    def test_trace_tool_call_disabled(self):
        """Test tool call tracing when disabled."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)

        with manager.trace_tool_call("test_tool", "test_agent", {"input": "data"}) as span:
            assert span is None

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_trace_tool_call_exception_marks_failure(self, mock_trace):
        """Tool exceptions record failure and error attributes."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            manager.configure(MonitoringConfig(enable_telemetry=True))
            manager._tracer = MagicMock()

            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)
            mock_span.is_recording.return_value = True
            mock_trace.get_current_span.return_value = mock_span

            with pytest.raises(RuntimeError, match="tool failed"):
                with manager.trace_tool_call("bad_tool", "test_agent", {"input": "data"}):
                    raise RuntimeError("tool failed")

            mock_span.set_attribute.assert_any_call("agent.tool.success", False)
            mock_span.set_attribute.assert_any_call("error.type", "RuntimeError")
            mock_span.set_attribute.assert_any_call("error.message", "tool failed")


class TestAgentObservability:
    """Test SDK-owned Agent observability lifecycle helpers."""

    def setup_method(self):
        """Reset singleton state before each test."""
        MonitoringManager._instance = None
        MonitoringManager._initialized = False

    def _enabled_manager(self):
        manager = MonitoringManager()
        manager.configure(MonitoringConfig(enable_telemetry=True))
        manager._tracer = MagicMock()
        return manager

    @staticmethod
    def _span_context(span):
        ctx = MagicMock()
        ctx.__enter__.return_value = span
        ctx.__exit__.return_value = None
        return ctx

    def test_agent_observability_entrypoint_imports(self):
        """Agent observability APIs are available from the stable SDK entrypoint."""
        from sdk.nexent.monitor.agent_observability import (
            AgentRunMetadata as EntrypointMetadata,
            agent_monitoring_context as entrypoint_context,
            get_monitoring_manager as entrypoint_manager,
        )

        assert EntrypointMetadata is AgentRunMetadata
        assert entrypoint_context is agent_monitoring_context
        assert entrypoint_manager is get_monitoring_manager

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_agent_run_and_step_spans_without_business_decorator(self, mock_trace):
        """Agent lifecycle spans are produced by SDK helpers, not endpoint decorators."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = self._enabled_manager()
            agent_span = MagicMock()
            chain_span = MagicMock()
            manager._tracer.start_as_current_span.side_effect = [
                self._span_context(agent_span),
                self._span_context(chain_span),
            ]

            metadata = AgentRunMetadata(
                tenant_id="tenant-1",
                user_id="user-1",
                agent_id=11,
                conversation_id=22,
                agent_name="assistant",
                query="hello",
                is_debug=False,
                language="zh",
                memory_enabled=True,
            )

            with manager.start_agent_run(metadata):
                assert get_agent_monitoring_context() == metadata
                with manager.trace_agent_step("agent.run.loop", metadata, step_type="agent_loop"):
                    pass

            calls = manager._tracer.start_as_current_span.call_args_list
            assert calls[0].args[0] == "agent.run"
            agent_attrs = calls[0].kwargs["attributes"]
            assert agent_attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_AGENT
            assert agent_attrs[OPENINFERENCE_SESSION_ID] == "22"
            assert agent_attrs[OPENINFERENCE_USER_ID] == "user-1"
            assert agent_attrs[OPENINFERENCE_INPUT_VALUE] == "hello"
            assert agent_attrs["tenant.id"] == "tenant-1"
            assert agent_attrs["agent.id"] == 11

            assert calls[1].args[0] == "agent.run.loop"
            chain_attrs = calls[1].kwargs["attributes"]
            assert chain_attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_CHAIN
            assert chain_attrs["agent.step.type"] == "agent_loop"
            assert chain_attrs["conversation.id"] == 22

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_llm_and_tool_spans_inherit_bound_agent_context(self, mock_trace):
        """LLM and tool spans inherit Agent metadata after a single boundary bind."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = self._enabled_manager()
            llm_span = MagicMock()
            tool_span = MagicMock()
            manager._tracer.start_as_current_span.side_effect = [
                self._span_context(llm_span),
                self._span_context(tool_span),
            ]
            mock_trace.get_current_span.return_value = tool_span
            tool_span.is_recording.return_value = True

            metadata = AgentRunMetadata(
                tenant_id="tenant-2",
                user_id="user-2",
                agent_id=33,
                conversation_id=44,
                agent_name="researcher",
                query="find docs",
            )

            with agent_monitoring_context(metadata):
                with manager.trace_llm_request(
                    "gpt.generate",
                    "gpt-4",
                    **{OPENINFERENCE_INPUT_VALUE: "prompt"},
                ):
                    pass
                with manager.trace_tool_call("web_search", "researcher", {"query": "docs"}):
                    manager.set_tool_output("ok")

            calls = manager._tracer.start_as_current_span.call_args_list
            llm_attrs = calls[0].kwargs["attributes"]
            assert llm_attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_LLM
            assert llm_attrs[OPENINFERENCE_SESSION_ID] == "44"
            assert llm_attrs[OPENINFERENCE_USER_ID] == "user-2"
            assert llm_attrs[OPENINFERENCE_INPUT_VALUE] == "prompt"
            assert llm_attrs["tenant.id"] == "tenant-2"
            assert llm_attrs["agent.id"] == 33

            tool_attrs = calls[1].kwargs["attributes"]
            assert tool_attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_TOOL
            assert tool_attrs[OPENINFERENCE_SESSION_ID] == "44"
            assert tool_attrs[OPENINFERENCE_USER_ID] == "user-2"
            assert tool_attrs["tenant.id"] == "tenant-2"
            assert tool_attrs["agent.tool.name"] == "web_search"
            assert "query" in tool_attrs[OPENINFERENCE_INPUT_VALUE]

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_retriever_span_inherits_bound_agent_context(self, mock_trace):
        """Retriever spans use OpenInference RETRIEVER semantics with Agent metadata."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = self._enabled_manager()
            retriever_span = MagicMock()
            manager._tracer.start_as_current_span.side_effect = [
                self._span_context(retriever_span),
            ]
            mock_trace.get_current_span.return_value = retriever_span
            retriever_span.is_recording.return_value = True

            metadata = AgentRunMetadata(
                tenant_id="tenant-r",
                user_id="user-r",
                agent_id=77,
                conversation_id=88,
                agent_name="researcher",
            )

            with agent_monitoring_context(metadata):
                with manager.trace_retriever_call(
                    "knowledge_base_search",
                    "researcher",
                    {"query": "sdk monitoring"},
                ):
                    manager.set_retriever_output({
                        "documents": [
                            {"id": "doc-1", "score": 0.82},
                            {"id": "doc-2", "score": 0.61},
                        ]
                    })

            attrs = manager._tracer.start_as_current_span.call_args.kwargs["attributes"]
            assert attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_RETRIEVER
            assert attrs[OPENINFERENCE_SESSION_ID] == "88"
            assert attrs[OPENINFERENCE_USER_ID] == "user-r"
            assert attrs["tenant.id"] == "tenant-r"
            assert attrs["retriever.name"] == "knowledge_base_search"
            assert attrs["retrieval.query"] == "sdk monitoring"
            assert "sdk monitoring" in attrs[OPENINFERENCE_INPUT_VALUE]
            assert attrs["retriever.input.type"] == "dict"
            assert attrs["retriever.input.item_count"] == 1

            output_attrs = retriever_span.set_attributes.call_args.args[0]
            assert output_attrs["retriever.success"] is True
            assert output_attrs["retriever.output.type"] == "dict"
            assert output_attrs["retrieval.results.count"] == 2
            assert output_attrs["retrieval.top_score"] == 0.82

    @pytest.mark.asyncio
    async def test_agent_context_survives_delayed_async_stream_iteration(self):
        """StreamingResponse-style delayed async iteration keeps Agent metadata bound."""
        metadata = AgentRunMetadata(
            tenant_id="tenant-stream",
            user_id="user-stream",
            agent_id=55,
            conversation_id=66,
            query="stream query",
        )
        observed_contexts = []

        async def source_stream():
            await asyncio.sleep(0)
            observed_contexts.append(get_agent_monitoring_context())
            yield "data: chunk\n\n"

        async def stream_with_agent_context():
            with agent_monitoring_context(metadata):
                async for item in source_stream():
                    yield item

        chunks = [item async for item in stream_with_agent_context()]

        assert chunks == ["data: chunk\n\n"]
        assert observed_contexts == [metadata]
        assert get_agent_monitoring_context() is None

    def test_agent_observability_disabled_is_noop(self):
        """SDK Agent observability is a no-op when telemetry is disabled."""
        manager = MonitoringManager()
        manager.configure(MonitoringConfig(enable_telemetry=False))

        metadata = AgentRunMetadata(tenant_id="tenant", agent_id=1)
        with manager.start_agent_run(metadata) as span:
            assert span is None
            with manager.trace_agent_step("agent.run.loop", metadata) as step_span:
                assert step_span is None

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_record_agent_step_metrics_adds_context_event(self, mock_trace):
        """Action step metrics are written as context/compression span events."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = self._enabled_manager()
            mock_span = MagicMock()
            mock_trace.get_current_span.return_value = mock_span

            manager.record_agent_step_metrics(
                {
                    "step_number": 2,
                    "main_llm": {"input_tokens": 100, "output_tokens": 12},
                    "compression": {
                        "calls": 1,
                        "input_tokens": 80,
                        "output_tokens": 40,
                        "cache_hits": 1,
                    },
                    "memory_state": {
                        "estimated_input_tokens": 55,
                        "estimated_output_tokens": 8,
                    },
                    "uncompressed_mem_est_input": 110,
                    "compression_ratio": 50.0,
                    "cache_hit": True,
                },
                token_threshold=4096,
            )

            event_name, event_attrs = mock_span.add_event.call_args.args
            assert event_name == "agent.step.metrics"
            assert event_attrs["agent.step.number"] == 2
            assert event_attrs["context.tokens.estimated_input"] == 55
            assert event_attrs["context.tokens.uncompressed_estimated"] == 110
            assert event_attrs["context.compression.calls"] == 1
            assert event_attrs["context.compression.cache_hits"] == 1
            assert event_attrs["context.compression.ratio"] == 50.0
            assert event_attrs["context.token_threshold"] == 4096

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_set_agent_context_metrics_adds_aggregate_attributes(self, mock_trace):
        """Agent run spans receive aggregate context/compression metrics."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = self._enabled_manager()
            mock_span = MagicMock()
            mock_trace.get_current_span.return_value = mock_span

            manager.set_agent_context_metrics([
                {
                    "memory_state": {"estimated_input_tokens": 50},
                    "compression": {"calls": 1, "cache_hits": 0},
                    "compression_ratio": 40.0,
                },
                {
                    "memory_state": {"estimated_input_tokens": 80},
                    "compression": {"calls": 2, "cache_hits": 1},
                    "compression_ratio": 60.0,
                },
            ])

            attrs = mock_span.set_attributes.call_args.args[0]
            assert attrs["agent.steps.count"] == 2
            assert attrs["context.tokens.max_estimated_input"] == 80
            assert attrs["context.compression.avg_ratio"] == 50.0
            assert attrs["context.compression.calls.total"] == 3
            assert attrs["context.compression.cache_hits.total"] == 1


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
                "llm.usage_details": '{"input": 20, "output": 30, "total": 50}',
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

    def test_monitor_endpoint_decorator_async_generator(self):
        """Test monitor_endpoint keeps context while async generators are consumed."""
        manager = MonitoringManager()
        config = MonitoringConfig(enable_telemetry=False)
        manager.configure(config)
        events = []
        original_add_span_event = manager.add_span_event

        def capture_event(name, attributes=None):
            events.append((name, attributes or {}))
            original_add_span_event(name, attributes)

        manager.add_span_event = capture_event

        @manager.monitor_endpoint("stream_operation")
        async def stream_function():
            manager.add_span_event("stream_operation.inside")
            yield "chunk-1"
            manager.add_span_event("stream_operation.after_yield")
            yield "chunk-2"

        async def consume_stream():
            return [item async for item in stream_function()]

        try:
            result = asyncio.run(consume_stream())
        finally:
            manager.add_span_event = original_add_span_event

        assert result == ["chunk-1", "chunk-2"]
        event_names = [name for name, _ in events]
        assert event_names == [
            "stream_operation.started",
            "stream_operation.inside",
            "stream_operation.after_yield",
            "stream_operation.completed",
        ]

    @patch('sdk.nexent.monitor.monitoring.trace')
    def test_monitor_endpoint_uses_openinference_span_kind(self, mock_trace):
        """Test monitor_endpoint creates Phoenix-friendly chain/agent spans."""
        with patch('sdk.nexent.monitor.monitoring.OPENTELEMETRY_AVAILABLE', True):
            manager = MonitoringManager()
            config = MonitoringConfig(enable_telemetry=True)
            manager.configure(config)
            manager._tracer = MagicMock()

            mock_span = MagicMock()
            manager._tracer.start_as_current_span.return_value.__enter__ = Mock(return_value=mock_span)
            manager._tracer.start_as_current_span.return_value.__exit__ = Mock(return_value=None)
            mock_trace.get_current_span.return_value = mock_span

            @manager.monitor_endpoint("agent.run")
            def agent_func():
                return "ok"

            assert agent_func() == "ok"
            attrs = manager._tracer.start_as_current_span.call_args.kwargs["attributes"]
            assert attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_AGENT

            @manager.monitor_endpoint("agent_service.run_agent_stream")
            def chain_func():
                return "ok"

            assert chain_func() == "ok"
            attrs = manager._tracer.start_as_current_span.call_args.kwargs["attributes"]
            assert attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_CHAIN

            @manager.monitor_endpoint("agent_run")
            def internal_agent_func():
                return "ok"

            assert internal_agent_func() == "ok"
            attrs = manager._tracer.start_as_current_span.call_args.kwargs["attributes"]
            assert attrs[OPENINFERENCE_SPAN_KIND] == OPENINFERENCE_SPAN_KIND_CHAIN

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
        manager.record_agent_step_metrics({"step_number": 1})
        manager.set_agent_context_metrics([{"memory_state": {"estimated_input_tokens": 1}}])
        manager.record_llm_metrics("ttft", 0.5, {})

        with manager.trace_llm_request("test", "model") as span:
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
