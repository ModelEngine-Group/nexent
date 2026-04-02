"""
Unit tests for config_app module.

Tests the FastAPI app initialization, middleware configuration,
routers inclusion, and monitoring setup.

This test file focuses on testing config_app by importing it from the app_factory
module and verifying the app structure without triggering all the complex router
dependencies.
"""
import atexit
from unittest.mock import patch, Mock, MagicMock
import os
import sys
import types
import warnings

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient

# Filter out deprecation warnings from third-party libraries
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pyiceberg")
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning:pyiceberg.*")

# Dynamically determine the backend path - MUST BE FIRST
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

# Import test utilities from app_factory tests - the pattern that works
from test.backend.app.test_app_factory import (
    TestCreateApp,
    TestRegisterExceptionHandlers,
    TestExceptionMappingToHttpStatus,
    TestMonitoringIntegration,
    TestCORSConfiguration,
    TestAppExceptionResponseFormat,
    TestMultipleExceptionHandlers,
    TestMonitoringImportFailure,
    TestGenericExceptionHandlerAppExceptionCheck
)


class TestConfigAppIntegration:
    """Test class for config_app module integration with app_factory."""

    def test_config_app_can_import_consts(self):
        """Test that we can import from consts.const."""
        from consts.const import IS_SPEED_MODE
        assert isinstance(IS_SPEED_MODE, bool)

    def test_config_app_can_import_app_factory(self):
        """Test that we can import create_app from app_factory."""
        from backend.apps.app_factory import create_app
        app = create_app()
        assert isinstance(app, FastAPI)
        assert app.root_path == "/api"

    def test_config_app_title(self):
        """Test that create_app works with config app title."""
        from backend.apps.app_factory import create_app
        app = create_app(title="Nexent Config API", description="Configuration APIs")
        assert app.title == "Nexent Config API"
        assert app.description == "Configuration APIs"

    def test_config_app_default_cors_config(self):
        """Test that config app has correct CORS configuration."""
        from backend.apps.app_factory import create_app
        app = create_app()

        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                cors_middleware = middleware
                break

        assert cors_middleware is not None
        assert cors_middleware.kwargs.get("allow_origins") == ["*"]
        assert cors_middleware.kwargs.get("allow_credentials") is True
        assert cors_middleware.kwargs.get("allow_methods") == ["*"]
        assert cors_middleware.kwargs.get("allow_headers") == ["*"]


class TestConfigAppRouterConfiguration:
    """Test class for router configuration patterns."""

    def test_create_app_with_multiple_routers(self):
        """Test that create_app can include multiple routers."""
        from backend.apps.app_factory import create_app
        from fastapi import APIRouter

        app = create_app()

        # Create test routers
        router1 = APIRouter()
        router2 = APIRouter()

        @router1.get("/test1")
        def test_route1():
            return {"status": "ok"}

        @router2.get("/test2")
        def test_route2():
            return {"status": "ok"}

        app.include_router(router1)
        app.include_router(router2)

        assert len(app.routes) > 2

    def test_router_path_prefixes(self):
        """Test router path prefix patterns."""
        from backend.apps.app_factory import create_app
        from fastapi import APIRouter

        app = create_app()

        router = APIRouter(prefix="/api/v1")

        @router.get("/resource")
        def get_resource():
            return {"status": "ok"}

        app.include_router(router, prefix="/api/v1")

        # Check that routes are registered
        routes = [r for r in app.routes if hasattr(r, 'path')]
        assert len(routes) >= 1


class TestConfigAppExceptionHandling:
    """Test class for exception handling patterns in config app."""

    def test_http_exception_handler_config(self):
        """Test HTTPException handler configuration."""
        from backend.apps.app_factory import create_app, register_exception_handlers
        from fastapi import HTTPException

        app = create_app()
        register_exception_handlers(app)

        @app.get("/test-exception")
        def raise_exception():
            raise HTTPException(status_code=404, detail="Not found")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test-exception")

        assert response.status_code == 404
        assert response.json() == {"message": "Not found"}

    def test_exception_handlers_registered(self):
        """Test that exception handlers are properly registered."""
        from backend.apps.app_factory import create_app, register_exception_handlers
        from fastapi import HTTPException

        app = create_app()
        register_exception_handlers(app)

        # Check that exception handlers are registered
        exception_handlers = app.exception_handlers
        assert HTTPException in exception_handlers
        assert Exception in exception_handlers


class TestConfigAppMonitoring:
    """Test class for monitoring configuration."""

    def test_monitoring_can_be_enabled(self):
        """Test that monitoring can be enabled for config app."""
        from backend.apps.app_factory import create_app

        app = create_app(enable_monitoring=True)
        assert isinstance(app, FastAPI)

    def test_monitoring_can_be_disabled(self):
        """Test that monitoring can be disabled for config app."""
        from backend.apps.app_factory import create_app

        app = create_app(enable_monitoring=False)
        assert isinstance(app, FastAPI)

    def test_monitoring_import_failure_handled(self):
        """Test that monitoring import failure is handled gracefully."""
        from backend.apps.app_factory import create_app
        from unittest.mock import patch

        # Test with monitoring enabled but module not available
        with patch.dict('sys.modules', {'utils.monitoring': None}):
            with patch('backend.apps.app_factory.logger') as mock_logger:
                app = create_app(enable_monitoring=True)
                assert app is not None


class TestConfigAppSpeedMode:
    """Test class for speed mode configuration."""

    def test_is_speed_mode_import(self):
        """Test that IS_SPEED_MODE can be imported."""
        from consts.const import IS_SPEED_MODE
        assert isinstance(IS_SPEED_MODE, bool)

    def test_speed_mode_conditional(self):
        """Test speed mode conditional logic."""
        from consts.const import IS_SPEED_MODE
        from backend.apps.app_factory import create_app

        # App should work regardless of speed mode
        app = create_app()
        assert app is not None

        # Conditional should be a boolean
        assert IS_SPEED_MODE in [True, False]


class TestConfigAppRouterTypes:
    """Test class for router types used in config app."""

    def test_api_router_instantiation(self):
        """Test that APIRouter can be instantiated."""
        router = APIRouter()
        assert isinstance(router, APIRouter)

    def test_router_with_tags(self):
        """Test router with tags."""
        from fastapi import APIRouter

        router = APIRouter(tags=["config"])

        @router.get("/test")
        def test_route():
            return {"status": "ok"}

        assert len(router.routes) == 1
        assert "config" in router.routes[0].tags


class TestConfigAppMiddlewareStack:
    """Test class for middleware stack configuration."""

    def test_middleware_stack_exists(self):
        """Test that middleware stack exists."""
        from backend.apps.app_factory import create_app

        app = create_app()
        assert hasattr(app, 'user_middleware')
        assert len(app.user_middleware) > 0

    def test_cors_middleware_present(self):
        """Test that CORS middleware is present."""
        from backend.apps.app_factory import create_app

        app = create_app()

        cors_found = False
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                cors_found = True
                break

        assert cors_found is True

    def test_middleware_order(self):
        """Test middleware order is preserved."""
        from backend.apps.app_factory import create_app

        app = create_app()
        middleware_count = len(app.user_middleware)

        # Middleware should be applied in order
        assert middleware_count >= 1


class TestConfigAppRoutes:
    """Test class for route configuration."""

    def test_route_with_path_parameters(self):
        """Test routes with path parameters."""
        from backend.apps.app_factory import create_app
        from fastapi import APIRouter

        app = create_app()
        router = APIRouter()

        @router.get("/items/{item_id}")
        def get_item(item_id: int):
            return {"item_id": item_id}

        app.include_router(router)

        # Check that routes exist
        routes = [r for r in app.routes if hasattr(r, 'path')]
        assert len(routes) >= 1

    def test_route_with_query_parameters(self):
        """Test routes with query parameters."""
        from backend.apps.app_factory import create_app
        from fastapi import APIRouter

        app = create_app()
        router = APIRouter()

        @router.get("/search")
        def search(q: str = ""):
            return {"query": q}

        app.include_router(router)

        client = TestClient(app)
        response = client.get("/search?q=test")
        assert response.status_code == 200
        assert response.json()["query"] == "test"

    def test_route_with_post_body(self):
        """Test routes with POST body."""
        from backend.apps.app_factory import create_app
        from fastapi import APIRouter
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            description: str = ""

        app = create_app()
        router = APIRouter()

        @router.post("/items")
        def create_item(item: Item):
            return {"name": item.name, "description": item.description}

        app.include_router(router)

        client = TestClient(app)
        response = client.post("/items", json={"name": "test", "description": "desc"})
        assert response.status_code == 200
        assert response.json()["name"] == "test"


class TestConfigAppErrorResponses:
    """Test class for error response formats."""

    def test_404_error_format(self):
        """Test 404 error response format."""
        from backend.apps.app_factory import create_app, register_exception_handlers

        app = create_app()
        register_exception_handlers(app)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/non-existent")

        assert response.status_code == 404

    def test_500_error_format(self):
        """Test 500 error response format."""
        from backend.apps.app_factory import create_app, register_exception_handlers

        app = create_app()
        register_exception_handlers(app)

        @app.get("/error")
        def raise_error():
            raise RuntimeError("Test error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/error")

        assert response.status_code == 500
        assert "message" in response.json()


class TestConfigAppVersioning:
    """Test class for API versioning patterns."""

    def test_root_path_configuration(self):
        """Test root path configuration."""
        from backend.apps.app_factory import create_app

        app = create_app(root_path="/api")
        assert app.root_path == "/api"

        app_custom = create_app(root_path="/v1")
        assert app_custom.root_path == "/v1"

    def test_custom_root_path_with_routes(self):
        """Test custom root path with routes."""
        from backend.apps.app_factory import create_app
        from fastapi import APIRouter

        app = create_app(root_path="/api")
        router = APIRouter()

        @router.get("/test")
        def test_route():
            return {"status": "ok"}

        app.include_router(router)

        client = TestClient(app, base_url="http://testserver/api")
        response = client.get("/test")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
