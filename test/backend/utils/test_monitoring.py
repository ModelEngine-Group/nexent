"""
Unit tests for backend monitoring utilities (OTLP-based).

Tests the actual functionality and integration of the OTLP monitoring system.
"""

import pytest
from unittest.mock import MagicMock
from backend.utils.monitoring import monitoring_manager


class TestMonitoringUtilsModule:
    """Test backend monitoring utilities module functionality."""

    def test_monitoring_manager_exists(self):
        """Test that monitoring_manager is properly exported."""
        assert monitoring_manager is not None
        assert hasattr(monitoring_manager, 'configure')
        assert hasattr(monitoring_manager, 'monitor_endpoint')
        assert hasattr(monitoring_manager, 'monitor_llm_call')
        assert hasattr(monitoring_manager, 'trace_tool_call')

    def test_monitoring_manager_methods_callable(self):
        """Test that monitoring manager methods are callable."""
        monitoring_manager.add_span_event("test_event")
        monitoring_manager.set_span_attributes(key="value")
        monitoring_manager.record_llm_metrics("ttft", 0.5, {})

        is_enabled = monitoring_manager.is_enabled
        assert isinstance(is_enabled, bool)

    def test_monitoring_manager_decorators(self):
        """Test that monitoring decorators work."""
        @monitoring_manager.monitor_endpoint("test_operation")
        def test_function():
            return {"result": "success"}

        result = test_function()
        assert result == {"result": "success"}

    def test_monitoring_manager_llm_decorator(self):
        """Test that LLM monitoring decorator works."""
        @monitoring_manager.monitor_llm_call("test_model")
        def test_llm_function(**kwargs):
            return {"result": "llm_success"}

        result = test_llm_function()
        assert result == {"result": "llm_success"}

    def test_tool_call_tracing(self):
        """Test tool call tracing context manager."""
        tool_input = {"query": "test"}

        with monitoring_manager.trace_tool_call("web_search", "test_agent", tool_input) as span:
            monitoring_manager.set_tool_output({"results": []})

    def test_monitoring_manager_context_manager(self):
        """Test that monitoring context manager works."""
        with monitoring_manager.trace_llm_request("test_op", "test_model") as span:
            pass

    def test_token_tracker_creation(self):
        """Test that token tracker can be created."""
        tracker = monitoring_manager.create_token_tracker("test_model")
        assert tracker is not None

        tracker.record_first_token()
        tracker.record_token("test_token")
        tracker.record_completion(input_tokens=10, output_tokens=15)

    def test_fastapi_app_setup(self):
        """Test FastAPI app setup functionality."""
        mock_app = MagicMock()

        result = monitoring_manager.setup_fastapi_app(mock_app)
        assert isinstance(result, bool)

        result = monitoring_manager.setup_fastapi_app(None)
        assert result is False

    def test_otlp_configuration(self):
        """Test OTLP configuration methods."""
        from sdk.nexent.monitor.monitoring import MonitoringConfig

        config = MonitoringConfig(
            enable_telemetry=False,
            service_name="test-service",
            otlp_endpoint="http://localhost:4318",
            otlp_protocol="http",
            otlp_headers={}
        )

        monitoring_manager.configure(config)

    def test_grpc_protocol_config(self):
        """Test gRPC protocol configuration."""
        from sdk.nexent.monitor.monitoring import MonitoringConfig

        config = MonitoringConfig(
            enable_telemetry=False,
            service_name="test-service",
            otlp_endpoint="http://localhost:4317",
            otlp_protocol="grpc"
        )

        monitoring_manager.configure(config)

    def test_error_resilience(self):
        """Test that monitoring handles errors gracefully."""
        try:
            monitoring_manager.add_span_event("test_event", {"key": "value"})
            monitoring_manager.set_span_attributes(test_attr="test_value")
            monitoring_manager.record_llm_metrics("token_rate", 10.0, {"llm.model_name": "test"})
        except Exception as e:
            pytest.fail(f"Monitoring methods should handle errors gracefully: {e}")

    def test_complex_decorator_scenario(self):
        """Test complex decorator usage scenarios."""
        @monitoring_manager.monitor_endpoint("complex_operation", exclude_params=["password"])
        async def async_function(username, password, debug=False):
            return {"username": username, "debug": debug}

        @monitoring_manager.monitor_endpoint("sync_operation")
        def sync_function(data):
            return {"processed": data}

        import asyncio
        result1 = asyncio.run(async_function("user1", "secret", debug=True))
        assert result1["username"] == "user1"
        assert result1["debug"] is True

        result2 = sync_function("test_data")
        assert result2["processed"] == "test_data"

    def test_monitoring_with_exceptions(self):
        """Test monitoring behavior when decorated functions raise exceptions."""
        @monitoring_manager.monitor_endpoint("error_operation")
        def error_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            error_function()

    def test_module_attributes(self):
        """Test that the module has correct attributes."""
        import backend.utils.monitoring as monitoring_module

        assert hasattr(monitoring_module, 'monitoring_manager')
        assert hasattr(monitoring_module, '__all__')
        assert 'monitoring_manager' in monitoring_module.__all__

    def test_singleton_behavior(self):
        """Test that monitoring manager maintains singleton behavior."""
        from backend.utils.monitoring import monitoring_manager as manager1
        from backend.utils.monitoring import monitoring_manager as manager2

        assert manager1 is manager2

    def test_concurrent_usage(self):
        """Test concurrent usage of monitoring manager."""
        import threading

        results = []

        def worker():
            try:
                monitoring_manager.add_span_event("concurrent_test")
                monitoring_manager.set_span_attributes(worker_id=threading.current_thread().ident)
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")

        threads = [threading.Thread(target=worker) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        assert all(r == "success" for r in results)

    def test_decorator_parameter_filtering(self):
        """Test that parameter filtering works in decorators."""
        @monitoring_manager.monitor_endpoint("param_filter_test", exclude_params=["secret"])
        def function_with_secrets(public_data, secret, debug=True):
            return {"public": public_data, "debug": debug}

        result = function_with_secrets("visible", "hidden", debug=False)
        assert result["public"] == "visible"
        assert result["debug"] is False

    def test_llm_decorator_with_token_tracker(self):
        """Test LLM decorator properly handles token tracker parameter."""
        @monitoring_manager.monitor_llm_call("gpt-4")
        def mock_llm_call(**kwargs):
            assert "_token_tracker" in kwargs
            token_tracker = kwargs["_token_tracker"]

            if token_tracker:
                token_tracker.record_first_token()
                token_tracker.record_token("test")
                token_tracker.record_completion(10, 5)

            return "LLM response"

        result = mock_llm_call()
        assert result == "LLM response"

    def test_get_current_span(self):
        """Test getting current span functionality."""
        span = monitoring_manager.get_current_span()

    def test_get_tracer(self):
        """Test getting tracer property."""
        tracer = monitoring_manager.tracer
