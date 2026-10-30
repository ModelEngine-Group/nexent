# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Unit tests for config_app module.

Tests the FastAPI app initialization, middleware configuration,
routers inclusion, and monitoring setup.

This test file focuses on testing config_app by importing it from the app_factory
module and verifying the app structure without triggering all the complex router
dependencies.
"""
import asyncio
import atexit
import asyncio
import importlib.util
from unittest.mock import AsyncMock, patch, Mock, MagicMock
import os
from pathlib import Path
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
        """Test that we can import from contracts.constants.environment."""
        from contracts.constants.environment import IS_SPEED_MODE
        assert isinstance(IS_SPEED_MODE, bool)

    def test_config_app_can_import_app_factory(self):
        """Test that we can import create_app from app_factory."""
        from management.utils.app_factory import create_app
        app = create_app()
        assert isinstance(app, FastAPI)
        assert app.root_path == "/api"

    def test_config_app_title(self):
        """Test that create_app works with config app title."""
        from management.utils.app_factory import create_app
        app = create_app(title="Nexent Config API", description="Configuration APIs")
        assert app.title == "Nexent Config API"
        assert app.description == "Configuration APIs"

    def test_config_app_default_cors_config(self):
        """Test that config app has correct CORS configuration."""
        from management.utils.app_factory import create_app
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

    def test_config_app_registers_api_key_routes(self, monkeypatch):
        class RecordingApp:
            def __init__(self, lifespan=None):
                self.included_routers = []
                self.get_routes = []
                self.lifespan = lifespan

            def on_event(self, _event):
                return lambda handler: handler

            def include_router(self, router):
                self.included_routers.append(router)

            def get(self, path, **kwargs):
                def register(handler):
                    self.get_routes.append((path, kwargs, handler))
                    return handler

                return register

        app_factory_module = types.ModuleType("management.utils.app_factory")
        app_factory_module.create_app = (
            lambda **kwargs: RecordingApp(kwargs.get("lifespan"))
        )
        monkeypatch.setitem(sys.modules, "management.utils.app_factory", app_factory_module)

        api_key_router = APIRouter(prefix="/api-keys")

        @api_key_router.get("")
        def list_api_keys():
            return {}

        @api_key_router.post("/refresh")
        def refresh_api_key():
            return {}

        router_modules = {
            "management.api.agent.agent": {"agent_config_router": APIRouter()},
            "management.api.agent.agent_repository": {"agent_repository_router": APIRouter()},
            "management.api.skill.skill_repository": {"skill_repository_router": APIRouter()},
            "management.api.configuration.config_sync": {"router": APIRouter()},
            "management.api.knowledge_base.datamate": {"router": APIRouter()},
            "management.api.knowledge_base.vectordatabase": {"router": APIRouter()},
            "management.api.knowledge_base.dify": {"router": APIRouter()},
            "management.api.knowledge_base.idata": {"router": APIRouter()},
            "management.api.knowledge_base.ragflow": {"router": APIRouter()},
            "management.api.file.file_management": {"file_management_config_router": APIRouter()},
            "management.api.file.image": {"router": APIRouter()},
            "management.api.knowledge_base.knowledge_summary": {"router": APIRouter()},
            "management.api.identity.mock_user_management": {"router": APIRouter()},
            "management.api.model.model_managment": {"router": APIRouter()},
            "management.api.identity.oauth": {"router": APIRouter()},
            "management.api.prompt.prompt": {"router": APIRouter()},
            "management.api.mcp.mcp_management": {"router": APIRouter()},
            "management.api.mcp.remote_mcp": {"router": APIRouter()},
            "management.api.skill.skill": {"router": APIRouter()},
            "management.api.configuration.tenant_config": {"router": APIRouter()},
            "management.api.tool.tool_config": {"router": APIRouter()},
            "management.api.identity.user_management": {"router": APIRouter()},
            "management.api.voice.voice": {"voice_config_router": APIRouter()},
            "management.api.identity.tenant": {"router": APIRouter()},
            "management.api.identity.group": {"router": APIRouter()},
            "management.api.identity.user": {"router": APIRouter()},
            "management.api.identity.api_key": {"router": api_key_router},
            "management.api.identity.invitation": {"router": APIRouter()},
            "management.api.notification.notification": {"router": APIRouter()},
            "management.api.a2a.a2a_client": {"router": APIRouter()},
            "management.api.monitoring.monitoring": {"router": APIRouter()},
            "management.api.a2a.a2a_server": {"router": APIRouter()},
            "management.api.knowledge_base.haotian": {"router": APIRouter()},
            "management.api.knowledge_base.ind_aidp": {"router": APIRouter()},
            "management.api.evaluation.evaluation_set": {"router": APIRouter()},
            "management.api.evaluation.agent_evaluation": {"router": APIRouter()},
            "management.api.evaluation.evaluator": {"router": APIRouter()},
            "management.api.evaluation.evaluation_annotation": {"router": APIRouter()},
            "management.api.identity.cas": {"router": APIRouter()},
            "management.api.memory.memory_config": {"router": APIRouter()},
            "management.api.memory.memory_record": {"router": APIRouter()},
            "management.api.memory.memory_long_term": {"router": APIRouter()},
            "management.api.memory.memory_dreaming": {"router": APIRouter()},
            "management.api.memory.memory_provider": {"router": APIRouter()},
            "management.api.tag.tag_management": {"router": APIRouter()},
            "management.api.knowledge_base.quota": {
                "tenant_quota_router": APIRouter(),
                "platform_quota_router": APIRouter(),
                "personal_quota_router": APIRouter(),
            },
        }
        for module_name, attributes in router_modules.items():
            module = types.ModuleType(module_name)
            for attribute, value in attributes.items():
                setattr(module, attribute, value)
            monkeypatch.setitem(sys.modules, module_name, module)

        retired_router = APIRouter(prefix="/prompt-template")
        retired_module = types.ModuleType("management.api.prompt.prompt_template")
        retired_module.router = retired_router
        monkeypatch.setitem(sys.modules, "management.api.prompt.prompt_template", retired_module)

        const_module = types.ModuleType("contracts.constants.environment")
        const_module.AIDP_API_KEY = ""
        const_module.AIDP_SERVER_URL = ""
        const_module.ENABLE_AIDP_KNOWLEDGE = False
        const_module.ENABLE_AGENT_WORKBENCH = False
        const_module.IS_SPEED_MODE = False
        const_module.RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS = 1
        monkeypatch.setitem(sys.modules, "contracts.constants.environment", const_module)
        manager_state = types.SimpleNamespace(CREATED="created")

        class ManagedTaskSpec:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class ConfigThreadManager:
            def __init__(self):
                self.state = manager_state.CREATED

            def start(self):
                self.state = "running"

            async def run(self, _lane, _spec, fn, *args, **kwargs):
                return fn(*args, **kwargs)

            async def shutdown(self, timeout):
                self.state = "closed"

            def snapshot(self):
                return {"service_name": "config", "active_count": 0}

        concurrency_module = types.ModuleType("nexent.core.concurrency")
        concurrency_module.ManagedTaskSpec = ManagedTaskSpec
        concurrency_module.ManagerState = manager_state

        async def invoke_blocking(_name, operation, *args, **kwargs):
            return operation(*args, **kwargs)

        concurrency_module.run_blocking = AsyncMock(side_effect=invoke_blocking)
        migration = types.ModuleType("management.services.model.outlet_migration")
        migration.migrate_legacy_outlets = MagicMock(return_value={"migrated": 2, "failed": 1})
        monkeypatch.setitem(sys.modules, migration.__name__, migration)
        concurrency_module.set_default_thread_manager = MagicMock()
        concurrency_module.clear_default_thread_manager = MagicMock()
        monkeypatch.setitem(
            sys.modules, "nexent.core.concurrency", concurrency_module
        )
        thread_lifecycle_module = types.ModuleType(
            "infrastructure.concurrency"
        )
        thread_lifecycle_module.config_thread_manager = ConfigThreadManager()
        monkeypatch.setitem(
            sys.modules,
            "infrastructure.concurrency",
            thread_lifecycle_module,
        )

        module_path = Path(backend_dir) / 'management' / 'api' / 'application.py'
        spec = importlib.util.spec_from_file_location("isolated_config_app", module_path)
        config_app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_app)

        assert all(router is not retired_router for router in config_app.app.included_routers)
        assert api_key_router in config_app.app.included_routers
        assert {route.path for route in api_key_router.routes} == {
            "/api-keys",
            "/api-keys/refresh",
        }
        assert [route[0] for route in config_app.app.get_routes] == [
            "/internal/thread-capacity"
        ]
        assert asyncio.run(config_app.thread_capacity()) == {
            "service_name": "config",
            "active_count": 0,
        }

        asyncio.run(config_app.validate_external_service_configuration())
        with patch.object(config_app, "ENABLE_AIDP_KNOWLEDGE", True):
            with pytest.raises(RuntimeError, match="AIDP_SERVER_URL and AIDP_API_KEY"):
                asyncio.run(config_app.validate_external_service_configuration())

        recover_config_tasks = MagicMock()
        schedule_upload_cleanup = AsyncMock()
        schedule_workbench_main_backfill = MagicMock()
        startup_recovery_module = types.ModuleType(
            "management.recovery"
        )
        startup_recovery_module.recover_config_tasks = recover_config_tasks
        startup_recovery_module.schedule_interrupted_upload_cleanup = (
            schedule_upload_cleanup
        )
        startup_recovery_module.schedule_workbench_main_backfill = (
            schedule_workbench_main_backfill
        )
        monkeypatch.setitem(
            sys.modules,
            "management.recovery",
            startup_recovery_module,
        )

        start_evaluation_maintenance = MagicMock()
        evaluation_maintenance_module = types.ModuleType(
            "management.services.evaluation.maintenance"
        )
        evaluation_maintenance_module.start = start_evaluation_maintenance
        evaluation_maintenance_module.stop = MagicMock()
        monkeypatch.setitem(
            sys.modules,
            "management.services.evaluation.maintenance",
            evaluation_maintenance_module,
        )

        dreaming_scheduler = MagicMock()
        dreaming_scheduler.start = AsyncMock()
        dreaming_scheduler.stop = AsyncMock()
        dreaming_scheduler_module = types.ModuleType(
            "management.services.memory.dreaming.scheduler"
        )
        dreaming_scheduler_module.dreaming_scheduler = dreaming_scheduler
        monkeypatch.setitem(
            sys.modules,
            "management.services.memory.dreaming.scheduler",
            dreaming_scheduler_module,
        )

        validate_external = AsyncMock()

        async def exercise_lifespan():
            async with config_app.config_lifespan(None):
                pass

        with patch.object(
            config_app,
            "validate_external_service_configuration",
            new=validate_external,
        ), patch.object(config_app, "ENABLE_AGENT_WORKBENCH", True):
            asyncio.run(exercise_lifespan())

        assert config_app.app.lifespan is config_app.config_lifespan
        migration.migrate_legacy_outlets.assert_called_once_with()
        concurrency_module.run_blocking.assert_awaited_once_with(
            "model-outlet-upgrade", migration.migrate_legacy_outlets
        )
        recover_config_tasks.assert_called_once_with()
        start_evaluation_maintenance.assert_called_once_with(
            config_app.config_thread_manager
        )
        schedule_upload_cleanup.assert_awaited_once_with("nexent-config")
        schedule_workbench_main_backfill.assert_called_once_with()
        validate_external.assert_awaited_once_with()
        dreaming_scheduler.start.assert_awaited_once_with()
        dreaming_scheduler.stop.assert_awaited_once_with()

    def test_create_app_with_multiple_routers(self):
        """Test that create_app can include multiple routers."""
        from management.utils.app_factory import create_app
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
        from management.utils.app_factory import create_app
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
        from management.utils.app_factory import create_app, register_exception_handlers
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
        from management.utils.app_factory import create_app, register_exception_handlers
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
        from management.utils.app_factory import create_app

        app = create_app(enable_monitoring=True)
        assert isinstance(app, FastAPI)

    def test_monitoring_can_be_disabled(self):
        """Test that monitoring can be disabled for config app."""
        from management.utils.app_factory import create_app

        app = create_app(enable_monitoring=False)
        assert isinstance(app, FastAPI)

    def test_monitoring_import_failure_handled(self):
        """Test that monitoring import failure is handled gracefully."""
        from management.utils.app_factory import create_app
        from unittest.mock import patch

        # Test with monitoring enabled but module not available
        with patch.dict('sys.modules', {'infrastructure.observability.bootstrap': None}):
            with patch('management.utils.app_factory.logger') as mock_logger:
                app = create_app(enable_monitoring=True)
                assert app is not None


class TestConfigAppSpeedMode:
    """Test class for speed mode configuration."""

    def test_is_speed_mode_import(self):
        """Test that IS_SPEED_MODE can be imported."""
        from contracts.constants.environment import IS_SPEED_MODE
        assert isinstance(IS_SPEED_MODE, bool)

    def test_speed_mode_conditional(self):
        """Test speed mode conditional logic."""
        from contracts.constants.environment import IS_SPEED_MODE
        from management.utils.app_factory import create_app

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
        from management.utils.app_factory import create_app

        app = create_app()
        assert hasattr(app, 'user_middleware')
        assert len(app.user_middleware) > 0

    def test_cors_middleware_present(self):
        """Test that CORS middleware is present."""
        from management.utils.app_factory import create_app

        app = create_app()

        cors_found = False
        for middleware in app.user_middleware:
            if middleware.cls.__name__ == "CORSMiddleware":
                cors_found = True
                break

        assert cors_found is True

    def test_middleware_order(self):
        """Test middleware order is preserved."""
        from management.utils.app_factory import create_app

        app = create_app()
        middleware_count = len(app.user_middleware)

        # Middleware should be applied in order
        assert middleware_count >= 1


class TestConfigAppRoutes:
    """Test class for route configuration."""

    def test_route_with_path_parameters(self):
        """Test routes with path parameters."""
        from management.utils.app_factory import create_app
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
        from management.utils.app_factory import create_app
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
        from management.utils.app_factory import create_app
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
        from management.utils.app_factory import create_app, register_exception_handlers

        app = create_app()
        register_exception_handlers(app)

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/non-existent")

        assert response.status_code == 404

    def test_500_error_format(self):
        """Test 500 error response format."""
        from management.utils.app_factory import create_app, register_exception_handlers

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
        from management.utils.app_factory import create_app

        app = create_app(root_path="/api")
        assert app.root_path == "/api"

        app_custom = create_app(root_path="/v1")
        assert app_custom.root_path == "/v1"

    def test_custom_root_path_with_routes(self):
        """Test custom root path with routes."""
        from management.utils.app_factory import create_app
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
