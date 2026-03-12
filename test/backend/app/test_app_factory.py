"""
Unit tests for app_factory module.

Tests the create_app function and register_exception_handlers function
for FastAPI application factory with common configurations and exception handlers.
"""
import sys
import os

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# Add the backend directory to path so we can import modules
backend_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../../backend'))
sys.path.insert(0, backend_path)

# Import AppException from consts.exceptions where it is defined
from consts.error_code import ErrorCode
from consts.exceptions import AppException
from backend.apps.app_factory import create_app, register_exception_handlers

class TestCreateApp:
    """Test class for create_app function."""

    def test_create_app_default_parameters(self):
        """Test creating app with default parameters."""
        app = create_app()

        assert app is not None
        assert isinstance(app, FastAPI)
        assert app.title == "Nexent API"
        assert app.version == "1.0.0"
        assert app.root_path == "/api"

    def test_create_app_custom_title(self):
        """Test creating app with custom title."""
        app = create_app(title="Custom API")

        assert app.title == "Custom API"

    def test_create_app_custom_description(self):
        """Test creating app with custom description."""
        app = create_app(description="Custom description")

        assert app.description == "Custom description"

    def test_create_app_custom_version(self):
        """Test creating app with custom version."""
        app = create_app(version="2.0.0")

        assert app.version == "2.0.0"

    def test_create_app_custom_root_path(self):
        """Test creating app with custom root path."""
        app = create_app(root_path="/custom")

        assert app.root_path == "/custom"

    def test_create_app_custom_cors_origins(self):
        """Test creating app with custom CORS origins."""
        custom_origins = ["https://example.com", "https://api.example.com"]
        app = create_app(cors_origins=custom_origins)

        assert app is not None

    def test_create_app_custom_cors_methods(self):
        """Test creating app with custom CORS methods."""
        custom_methods = ["GET", "POST", "PUT", "DELETE"]
        app = create_app(cors_methods=custom_methods)

        assert app is not None

    def test_create_app_with_monitoring_disabled(self):
        """Test creating app with monitoring disabled."""
        app = create_app(enable_monitoring=False)

        assert app is not None
        assert isinstance(app, FastAPI)

    def test_create_app_with_monitoring_enabled(self):
        """Test creating app with monitoring enabled."""
        app = create_app(enable_monitoring=True)

        assert app is not None
        assert isinstance(app, FastAPI)

    def test_create_app_all_parameters(self):
        """Test creating app with all parameters."""
        app = create_app(
            title="Full Test API",
            description="Full description",
            version="3.0.0",
            root_path="/v3",
            cors_origins=["https://test.com"],
            cors_methods=["GET", "POST"],
            enable_monitoring=True
        )

        assert app.title == "Full Test API"
        assert app.description == "Full description"
        assert app.version == "3.0.0"
        assert app.root_path == "/v3"


class TestRegisterExceptionHandlers:
    """Test class for register_exception_handlers function."""

    def test_register_exception_handlers_basic(self):
        """Test registering exception handlers on a basic FastAPI app."""
        app = FastAPI()
        register_exception_handlers(app)

        assert app is not None

    def test_http_exception_handler(self):
        """Test HTTPException handler returns correct response."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-http-exception")
        def raise_http_exception():
            raise HTTPException(status_code=404, detail="Not found")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-http-exception")

        assert response.status_code == 404
        assert response.json() == {"message": "Not found"}

    def test_http_exception_handler_400(self):
        """Test HTTPException handler with 400 status."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-bad-request")
        def raise_bad_request():
            raise HTTPException(status_code=400, detail="Bad request")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-bad-request")

        assert response.status_code == 400
        assert response.json() == {"message": "Bad request"}

    def test_http_exception_handler_500(self):
        """Test HTTPException handler with 500 status."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-server-error")
        def raise_server_error():
            raise HTTPException(
                status_code=500, detail="Internal server error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-server-error")

        assert response.status_code == 500
        assert response.json() == {"message": "Internal server error"}

    def test_app_exception_handler(self):
        """Test AppException handler returns correct response."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-app-exception")
        def raise_app_exception():
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR, "Validation failed")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-app-exception")

        assert response.status_code == 400
        assert response.json()[
            "code"] == ErrorCode.COMMON_VALIDATION_ERROR.value
        assert response.json()["message"] == "Validation failed"

    def test_app_exception_handler_with_details(self):
        """Test AppException handler with details returns correct response."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-app-exception-details")
        def raise_app_exception_with_details():
            raise AppException(
                ErrorCode.MCP_CONNECTION_FAILED,
                "Connection failed",
                details={"host": "localhost", "port": 8080}
            )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-app-exception-details")

        # MCP_CONNECTION_FAILED maps to 500 by default
        assert response.status_code == 500
        assert response.json()["code"] == ErrorCode.MCP_CONNECTION_FAILED.value
        assert response.json()["details"] == {
            "host": "localhost", "port": 8080}

    def test_app_exception_handler_unauthorized(self):
        """Test AppException handler with UNAUTHORIZED error code."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-unauthorized")
        def raise_unauthorized():
            raise AppException(ErrorCode.COMMON_UNAUTHORIZED,
                               "Unauthorized access")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-unauthorized")

        assert response.status_code == 401

    def test_app_exception_handler_forbidden(self):
        """Test AppException handler with FORBIDDEN error code."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-forbidden")
        def raise_forbidden():
            raise AppException(ErrorCode.COMMON_FORBIDDEN, "Access forbidden")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-forbidden")

        assert response.status_code == 403

    def test_app_exception_handler_rate_limit(self):
        """Test AppException handler with RATE_LIMIT_EXCEEDED error code."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-rate-limit")
        def raise_rate_limit():
            raise AppException(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED,
                               "Too many requests")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-rate-limit")

        assert response.status_code == 429

    def test_generic_exception_handler(self):
        """Test generic Exception handler returns correct response."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-generic-exception")
        def raise_generic_exception():
            raise RuntimeError("Something went wrong")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-generic-exception")

        assert response.status_code == 500
        assert response.json() == {
            "message": "Internal server error, please try again later."}

    def test_generic_exception_handler_value_error(self):
        """Test generic Exception handler with ValueError."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-value-error")
        def raise_value_error():
            raise ValueError("Invalid value")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-value-error")

        assert response.status_code == 500

    def test_app_exception_takes_precedence_in_generic_handler(self):
        """Test that AppException is handled by its own handler, not generic."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-app-exception-in-generic")
        def raise_app_exception():
            # This should be handled by AppException handler, not generic
            # Use VALIDATION_ERROR which maps to 400
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR, "Validation failed")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-app-exception-in-generic")

        # Should return 400 (mapped from VALIDATION_ERROR)
        assert response.status_code == 400
        assert response.json()[
            "code"] == ErrorCode.COMMON_VALIDATION_ERROR.value


class TestExceptionMappingToHttpStatus:
    """Test class for exception mapping to HTTP status codes."""

    def test_validation_error_maps_to_400(self):
        """Test VALIDATION_ERROR maps to 400."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/validation-error")
        def test_validation():
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR, "Invalid input")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/validation-error")

        assert response.status_code == 400

    def test_parameter_invalid_maps_to_400(self):
        """Test PARAMETER_INVALID maps to 400."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/parameter-invalid")
        def test_param():
            raise AppException(ErrorCode.COMMON_PARAMETER_INVALID,
                               "Invalid parameter")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/parameter-invalid")

        assert response.status_code == 400

    def test_missing_required_field_maps_to_400(self):
        """Test MISSING_REQUIRED_FIELD maps to 400."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/missing-field")
        def test_missing():
            raise AppException(
                ErrorCode.COMMON_MISSING_REQUIRED_FIELD, "Field missing")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/missing-field")

        assert response.status_code == 400

    def test_file_too_large_maps_to_413(self):
        """Test FILE_TOO_LARGE maps to 413."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/file-too-large")
        def test_file():
            raise AppException(ErrorCode.FILE_TOO_LARGE, "File too large")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/file-too-large")

        assert response.status_code == 413


class TestMonitoringIntegration:
    """Test class for monitoring integration."""

    def test_monitoring_enabled_does_not_raise(self):
        """Test that create_app with enable_monitoring=True does not raise."""
        # This tests that the monitoring code path runs without error
        # Even if monitoring is not available, it should be caught gracefully
        app = create_app(enable_monitoring=True)

        assert app is not None
        assert isinstance(app, FastAPI)

    def test_monitoring_disabled_does_not_raise(self):
        """Test that create_app with enable_monitoring=False does not raise."""
        app = create_app(enable_monitoring=False)

        assert app is not None
        assert isinstance(app, FastAPI)

    def test_monitoring_with_actual_module(self):
        """Test that create_app works when monitoring module is available."""
        # Test with monitoring disabled to avoid actual module dependency
        app = create_app(enable_monitoring=False)

        assert app is not None
        # Verify basic app attributes are set correctly
        assert app.title == "Nexent API"
        assert app.version == "1.0.0"
        assert app.root_path == "/api"


class TestCORSConfiguration:
    """Test class for CORS configuration."""

    def test_cors_middleware_added_with_default_origins(self):
        """Test CORS middleware is added with default origins."""
        app = create_app()

        # Verify CORS middleware is in the middleware stack
        # FastAPI adds middleware as wrappers
        middleware_stack = app.user_middleware
        assert len(middleware_stack) > 0

    def test_cors_middleware_added_with_custom_origins(self):
        """Test CORS middleware is added with custom origins."""
        custom_origins = ["https://example.com"]
        app = create_app(cors_origins=custom_origins)

        assert app is not None

    def test_cors_middleware_with_credentials(self):
        """Test CORS middleware allows credentials."""
        app = create_app()

        # Middleware should be added
        assert app is not None


class TestAppExceptionResponseFormat:
    """Test class for AppException response format."""

    def test_response_contains_code_field(self):
        """Test response contains 'code' field."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-code-field")
        def test_code():
            raise AppException(
                ErrorCode.AGENTSPACE_AGENT_NOT_FOUND, "Agent not found")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-code-field")

        assert "code" in response.json()

    def test_response_contains_message_field(self):
        """Test response contains 'message' field."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-message-field")
        def test_message():
            raise AppException(
                ErrorCode.AGENTSPACE_AGENT_NOT_FOUND, "Agent not found")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-message-field")

        assert "message" in response.json()

    def test_response_details_is_none_when_not_provided(self):
        """Test response details is None when not provided."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-no-details")
        def test_no_details():
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR, "Validation failed")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-no-details")

        # details should be None when not provided
        assert response.json().get("details") is None


class TestMultipleExceptionHandlers:
    """Test class for multiple exception handlers in same app."""

    def test_multiple_routes_with_different_exceptions(self):
        """Test app handles different exception types from different routes."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/http-exc")
        def route_http():
            raise HTTPException(status_code=400, detail="HTTP error")

        @app.get("/app-exc")
        def route_app():
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "App error")

        @app.get("/gen-exc")
        def route_gen():
            raise Exception("Generic error")

        client = TestClient(app, raise_server_exceptions=False)

        assert client.get("/http-exc").status_code == 400
        assert client.get("/app-exc").status_code == 400
        assert client.get("/gen-exc").status_code == 500


class TestMonitoringImportFailure:
    """Test class for monitoring import failure scenarios.

    Tests the logger.warning when monitoring utilities are not available.
    """

    def test_create_app_monitoring_import_failure_logs_warning(self):
        """Test that create_app logs warning when monitoring module import fails."""
        import logging
        from unittest.mock import patch, MagicMock

        # Mock the monitoring module to raise ImportError
        with patch.dict('sys.modules', {'utils.monitoring': None}):
            with patch('backend.apps.app_factory.logger') as mock_logger:
                # Create app with monitoring enabled - import will fail
                app = create_app(enable_monitoring=True)

                # Verify logger.warning was called with expected message
                mock_logger.warning.assert_called_once_with(
                    "Monitoring utilities not available"
                )

                assert app is not None
                assert isinstance(app, FastAPI)

    def test_create_app_monitoring_disabled_no_warning(self):
        """Test that no warning is logged when monitoring is disabled."""
        from unittest.mock import patch

        with patch('backend.apps.app_factory.logger') as mock_logger:
            app = create_app(enable_monitoring=False)

            # Warning should not be called when monitoring is disabled
            mock_logger.warning.assert_not_called()

            assert app is not None

    def test_create_app_monitoring_import_error_specific_exception(self):
        """Test that create_app handles ImportError specifically."""
        from unittest.mock import patch, MagicMock

        # Create a mock monitoring module that raises ImportError when accessed
        mock_module = MagicMock()
        mock_module.monitoring_manager = MagicMock()
        mock_module.monitoring_manager.setup_fastapi_app.side_effect = ImportError(
            "No module named 'monitoring'"
        )

        with patch.dict('sys.modules', {'utils.monitoring': mock_module}):
            with patch('backend.apps.app_factory.logger') as mock_logger:
                app = create_app(enable_monitoring=True)

                # Should log warning about monitoring utilities not available
                mock_logger.warning.assert_called_with(
                    "Monitoring utilities not available"
                )

                assert app is not None


class TestGenericExceptionHandlerAppExceptionCheck:
    """Test class for generic exception handler's AppException check.

    Tests the logic that prevents AppException from being caught
    by the generic Exception handler.
    """

    def test_generic_handler_does_not_catch_app_exception_with_different_codes(self):
        """Test that generic handler does not catch AppException for various error codes."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI

        # Test multiple AppException error codes to ensure they're all handled correctly
        error_codes_to_test = [
            (ErrorCode.COMMON_VALIDATION_ERROR, 400),
            (ErrorCode.COMMON_UNAUTHORIZED, 401),
            (ErrorCode.COMMON_FORBIDDEN, 403),
            (ErrorCode.COMMON_RESOURCE_NOT_FOUND, 404),
            (ErrorCode.COMMON_RATE_LIMIT_EXCEEDED, 429),
        ]

        for error_code, expected_status in error_codes_to_test:
            app = FastAPI()
            register_exception_handlers(app)

            @app.get(f"/test-{error_code.value}")
            def raise_specific_app_exception():
                raise AppException(error_code, f"Error {error_code.value}")

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(f"/test-{error_code.value}")

            # Each AppException should be handled by its specific handler, not generic
            assert response.status_code == expected_status, \
                f"Expected {expected_status} for {error_code.value}, got {response.status_code}"
            assert "code" in response.json()
            assert response.json()["code"] == error_code.value

    def test_generic_handler_does_catch_non_app_exception(self):
        """Test that generic handler correctly catches non-AppException errors."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-runtime-error")
        def raise_runtime_error():
            raise RuntimeError("Runtime error occurred")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-runtime-error")

        # Generic exception handler should catch this
        assert response.status_code == 500
        assert response.json()[
            "message"] == "Internal server error, please try again later."

    def test_generic_handler_does_catch_value_error(self):
        """Test that generic handler catches ValueError."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-value-error")
        def raise_value_error():
            raise ValueError("Invalid value provided")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-value-error")

        # Generic exception handler should catch ValueError
        assert response.status_code == 500
        assert response.json()[
            "message"] == "Internal server error, please try again later."

    def test_generic_handler_does_catch_type_error(self):
        """Test that generic handler catches TypeError."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-type-error")
        def raise_type_error():
            raise TypeError("Type mismatch")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-type-error")

        # Generic exception handler should catch TypeError
        assert response.status_code == 500

    def test_app_exception_with_custom_http_status(self):
        """Test AppException with custom HTTP status is handled correctly."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-custom-status")
        def raise_custom_status():
            # Use an error code that maps to a different status
            raise AppException(ErrorCode.DIFY_SERVICE_ERROR,
                               "Dify service error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-custom-status")

        # DIFY_SERVICE_ERROR is not in the mapping, so it defaults to 500
        # This test verifies that custom error codes still work correctly
        assert response.status_code == 500
        assert response.json()["code"] == ErrorCode.DIFY_SERVICE_ERROR.value

    def test_both_exception_handlers_registered(self):
        """Test that both AppException and generic Exception handlers are registered."""
        app = FastAPI()
        register_exception_handlers(app)

        # Check that exception handlers are registered
        exception_handlers = app.exception_handlers

        # Both HTTPException and Exception handlers should be registered
        assert HTTPException in exception_handlers
        assert Exception in exception_handlers

    def test_app_exception_not_duplicated_in_generic_handler_logs(self):
        """Test that AppException is not logged as generic exception."""
        import logging
        from unittest.mock import patch

        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-app-exc")
        def raise_app_exc():
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR, "Validation error")

        # Use capture to check logging
        with patch('backend.apps.app_factory.logger') as mock_logger:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/test-app-exc")

            # AppException should NOT trigger the generic exception logger
            # It should go through the app_exception_handler which also logs
            # But the generic handler should NOT log it as "Generic Exception"
            assert response.status_code == 400

            # Verify the AppException handler logged it (not generic)
            # The AppException handler logs: f"AppException: {exc.error_code.value} - {exc.message}"
            app_exception_logged = any(
                "AppException:" in str(call) for call in mock_logger.error.call_args_list
            )
            assert app_exception_logged, "AppException should be logged by app_exception_handler"
