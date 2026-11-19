# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Integration tests for quota API endpoints.

Tests the full request/response cycle using FastAPI TestClient
with mocked authentication and database dependencies.
"""

from contextlib import ExitStack
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import (
    AppException,
    QuotaExceededError,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.api.file.file_management import upload_files
from management.api.knowledge_base import quota as quota_app
from management.api.knowledge_base.quota import (
    personal_quota_router,
    platform_quota_router,
    tenant_quota_router,
)

from backend.http.server.app_factory import create_app
from infrastructure.agentos_identity import ServicePrincipal

GB = 1024 * 1024 * 1024


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with quota routers for testing."""
    app = create_app(
        title="Test Quota API",
        root_path="/api",
        enable_monitoring=False,
    )
    app.include_router(tenant_quota_router)
    app.include_router(platform_quota_router)
    app.include_router(personal_quota_router)
    return app


@pytest.fixture
def mock_tenant_usage(mocker):
    service = mocker.patch.object(quota_app, 'TenantQuotaUsage').return_value
    service.read = AsyncMock()
    return service.read


@pytest.fixture
def client():
    """TestClient with mocked auth and DB."""
    app = _make_test_app()
    with TestClient(
        app, headers={"Authorization": "Bearer test-token"}
    ) as c:
        yield c


@pytest.fixture
def mock_auth_admin():
    """Mock auth to return an ADMIN user."""
    with patch("management.api.knowledge_base.quota.get_current_user_id") as mock_auth:
        mock_auth.return_value = ("admin-user-id", "test-tenant")
        yield


@pytest.fixture
def mock_auth_su():
    """Mock auth to return an SU user."""
    with patch("management.api.knowledge_base.quota.get_current_user_id") as mock_auth:
        mock_auth.return_value = ("su-user-id", "asset_owner_tenant_id")
        yield


@pytest.fixture
def mock_auth_user():
    """Mock auth to return a regular USER."""
    with patch("management.api.knowledge_base.quota.get_current_user_id") as mock_auth:
        mock_auth.return_value = ("user-id", "test-tenant")
        yield


@pytest.fixture
def mock_quota_service():
    """Mock QuotaService instance methods for integration tests."""
    with patch("management.api.knowledge_base.quota.QuotaService") as mock_class:
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_platform_static():
    """Mock the async overview and remaining synchronous platform writes."""
    with patch("management.api.knowledge_base.quota.PlatformQuotaOverview") as overview:
        read = overview.return_value.read = AsyncMock()
        yield {"get_platform_overview": read}


@pytest.fixture
def mock_personal_auth():
    """Factory for patching the personal capacity permission dependency."""
    with ExitStack() as stack:
        def _set(
            role: str = "ADMIN",
            tenant_id: str = "test-tenant",
            user_id: str = "admin-user-id",
            permission: bool = True,
        ):
            stack.enter_context(
                patch(
                    "management.services.permission.identity.session.get_current_user_context",
                    return_value=(user_id, tenant_id, role),
                )
            )
            stack.enter_context(
                patch("permissions.depends.has_permission", return_value=permission)
            )

        yield _set


# ═══════════════════════════════════════════════════════════════════════
# Task 12.1 — GET /tenants/{id}/quota
# ═══════════════════════════════════════════════════════════════════════

class TestGetTenantQuota:
    """Integration tests for GET /tenants/{id}/quota."""

    def test_returns_config_structure(self, client, mock_auth_admin, mock_quota_service, mocker):
        mock_quota_service.get_hard_limit.return_value = {
            "hard_limit_bytes": 100 * GB,
            "hard_limit_readable": "100.0 GB",
            "hard_limit_editable": True,
        }
        mock_quota_service.get_warning_config.return_value = {
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
        }
        mock_quota_service.get_quota_summary.return_value = {
            "soft_allocated_total_bytes": 0,
            "soft_allocated_readable": "0 B",
            "hard_limit_bytes": 100 * GB,
            "oversubscription_ratio": 0,
            "kb_count": 3,
            "kbs_with_quota": 1,
        }

        read = mocker.patch.object(quota_app, "read_tenant_quota", return_value={
            **mock_quota_service.get_hard_limit.return_value,
            **mock_quota_service.get_warning_config.return_value,
            "summary": mock_quota_service.get_quota_summary.return_value,
        })
        resp = client.get("/api/tenants/test-tenant/quota")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hard_limit_bytes"] == 100 * GB
        assert data["hard_limit_readable"] == "100.0 GB"
        assert data["hard_limit_editable"] is True
        assert data["warning_enabled"] is True
        assert data["warning_threshold_pct"] == 80
        assert "summary" in data
        assert read.await_count == 1 and read.await_args.args[1].user_id == "admin-user-id"
        assert read.await_args.args[1].tenant_id == "test-tenant"

    def test_returns_forbidden_for_cross_tenant_access(self, client, mock_auth_user, mocker):
        from nexent.storage.errors import ScopeDenied
        mocker.patch.object(quota_app, "read_tenant_quota", side_effect=ScopeDenied())
        resp = client.get("/api/tenants/other-tenant/quota")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Task 12.2 — PUT /tenants/{id}/quota
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# Task 12.3 — GET /tenants/{id}/quota/usage
# ═══════════════════════════════════════════════════════════════════════

class TestGetTenantQuotaUsage:
    """Integration tests for GET /tenants/{id}/quota/usage."""

    def test_returns_usage_structure(self, client, mock_auth_admin, mock_tenant_usage):
        mock_tenant_usage.return_value = (('ADMIN',), {
            "total_bytes": 50 * GB,
            "total_readable": "50.0 GB",
            "kb_count": 3,
            "file_count": 127,
            "hard_limit_bytes": 100 * GB,
            "hard_limit_readable": "100.0 GB",
            "available_bytes": 50 * GB,
            "available_readable": "50.0 GB",
            "usage_pct": 50.0,
            "tenant_warning_level": "normal",
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
        })

        resp = client.get("/api/tenants/test-tenant/quota/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_bytes"] == 50 * GB
        assert data["usage_pct"] == pytest.approx(50.0)
        assert data["tenant_warning_level"] == "normal"

    def test_returns_composite_values_without_component_fields(
        self, client, mock_auth_admin, mock_tenant_usage
    ):
        composite_bytes = 500 * 1024 * 1024
        mock_tenant_usage.return_value = (('ADMIN',), {
            "total_bytes": composite_bytes,
            "total_readable": "500.0 MB",
            "kb_count": 1,
            "file_count": 1,
            "hard_limit_bytes": GB,
            "hard_limit_readable": "1.0 GB",
            "available_bytes": GB - composite_bytes,
            "available_readable": "524.0 MB",
            "usage_pct": 48.83,
            "tenant_warning_level": "normal",
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
            "breakdown": [{
                "knowledge_id": 1,
                "knowledge_name": "Composite KB",
                "index_name": "composite-kb",
                "soft_quota_bytes": GB,
                "soft_quota_readable": "1.0 GB",
                "actual_bytes": composite_bytes,
                "actual_readable": "500.0 MB",
                "usage_pct": 48.83,
                "file_count": 1,
                "kb_warning_level": "normal",
            }],
        })

        response = client.get("/api/tenants/test-tenant/quota/usage?detail=true")

        assert response.status_code == 200
        data = response.json()
        assert data["total_bytes"] == composite_bytes
        assert data["breakdown"][0]["actual_bytes"] == composite_bytes
        assert "minio_bytes" not in data
        assert "es_bytes" not in data

    def test_unlimited_tenant_preserves_null_limit_fields(
        self, client, mock_auth_admin, mock_tenant_usage
    ):
        mock_tenant_usage.return_value = (('ADMIN',), {
            "total_bytes": 300,
            "total_readable": "300 B",
            "kb_count": 1,
            "file_count": 0,
            "hard_limit_bytes": None,
            "hard_limit_readable": None,
            "available_bytes": None,
            "available_readable": None,
            "usage_pct": None,
            "tenant_warning_level": "normal",
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
        })

        response = client.get("/api/tenants/test-tenant/quota/usage")

        assert response.status_code == 200
        data = response.json()
        assert data["total_bytes"] == 300
        assert data["hard_limit_bytes"] is None
        assert data["available_bytes"] is None
        assert data["usage_pct"] is None

    def test_detail_includes_breakdown(self, client, mock_auth_admin, mock_tenant_usage):
        mock_tenant_usage.return_value = (('ADMIN',), {
            "total_bytes": 50 * GB,
            "total_readable": "50.0 GB",
            "kb_count": 2,
            "file_count": 50,
            "hard_limit_bytes": 100 * GB,
            "usage_pct": 50.0,
            "tenant_warning_level": "normal",
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
            "breakdown": [
                {"knowledge_id": 1, "knowledge_name": "KB-A", "usage_pct": 80, "kb_warning_level": "warning"},
                {"knowledge_id": 2, "knowledge_name": "KB-B", "usage_pct": 30, "kb_warning_level": "normal"},
            ],
            "soft_allocated_total_bytes": 30 * GB,
            "oversubscription_ratio": 0.3,
            "kbs_with_quota": 1,
        })

        resp = client.get("/api/tenants/test-tenant/quota/usage?detail=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "breakdown" in data
        assert len(data["breakdown"]) == 2

    def test_force_refresh_param_accepted(self, client, mock_auth_admin, mock_tenant_usage):
        mock_tenant_usage.return_value = (('ADMIN',), {
            "total_bytes": 50 * GB,
            "total_readable": "50.0 GB",
            "kb_count": 2,
            "file_count": 50,
            "hard_limit_bytes": 100 * GB,
            "usage_pct": 50.0,
            "tenant_warning_level": "normal",
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
        })

        resp = client.get("/api/tenants/test-tenant/quota/usage?force_refresh=true")
        assert resp.status_code == 200
        # verify force_refresh was passed as True
        mock_tenant_usage.assert_awaited_once_with('test-tenant', ServicePrincipal('admin-user-id', 'test-tenant'), force_refresh=True, detail=False, context=ANY)

    def test_user_detail_filters_inaccessible_knowledge_bases(
        self, client, mock_auth_user, mock_tenant_usage
    ):
        mock_tenant_usage.return_value = (('USER',), {
            "total_bytes": 5 * GB,
            "total_readable": "5 GB",
            "kb_count": 2,
            "file_count": 3,
            "hard_limit_bytes": 10 * GB,
            "usage_pct": 50,
            "tenant_warning_level": "normal",
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
            "breakdown": [
                {
                    "index_name": "visible-kb",
                    "knowledge_name": "Visible KB",
                    "kb_warning_level": "warning",
                },
                {
                    "index_name": "hidden-kb",
                    "knowledge_name": "Hidden KB",
                    "kb_warning_level": "exceeded",
                },
            ],
        })

        with patch(
            "management.api.knowledge_base.quota._get_manageable_index_names",
            return_value={"visible-kb"},
        ):
            resp = client.get(
                "/api/tenants/test-tenant/quota/usage?detail=true"
            )

        assert resp.status_code == 200
        assert resp.json()["breakdown"] == [
            {
                "index_name": "visible-kb",
                "knowledge_name": "Visible KB",
                "kb_warning_level": "warning",
            }
        ]


# ═══════════════════════════════════════════════════════════════════════
# Task 12.5 — Platform quota endpoints
# ═══════════════════════════════════════════════════════════════════════

class TestPlatformEndpoints:
    """Integration tests for /platform/quota/* endpoints."""

    def test_get_overview_requires_su(self, client, mock_auth_su, mock_platform_static):
        mock_platform_static["get_platform_overview"].return_value = {
            "platform_capacity_bytes": 500 * GB,
            "platform_capacity_readable": "500.0 GB",
            "tenants": [],
            "total_allocated_bytes": 0,
            "total_allocated_readable": "0 B",
            "total_actual_bytes": 0,
            "total_actual_readable": "0 B",
            "tenant_count": 0,
            "oversubscription_ratio": 0,
        }

        resp = client.get("/api/platform/quota/overview")
        assert resp.status_code == 200

    def test_get_overview_denied_for_admin(self, client, mock_auth_admin, mock_platform_static):
        from nexent.storage.errors import ScopeDenied

        mock_platform_static["get_platform_overview"].side_effect = ScopeDenied()
        resp = client.get("/api/platform/quota/overview")
        assert resp.status_code == 403

    def test_get_overview_rejects_retired_role(self, client, mock_platform_static):
        from nexent.storage.errors import ScopeDenied

        mock_platform_static["get_platform_overview"].side_effect = ScopeDenied()
        with patch(
            "management.api.knowledge_base.quota.get_current_user_id",
            return_value=("speed-user-id", "speed-tenant"),
        ):
            resp = client.get("/api/platform/quota/overview")

        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Task 12.6 — Tenant Isolation
# ═══════════════════════════════════════════════════════════════════════

class TestTenantIsolation:
    """Integration tests for tenant data isolation."""

    def test_admin_cannot_access_other_tenant_usage(self, client, mock_auth_user, mock_tenant_usage):
        """Tenant A user cannot access Tenant B's usage."""
        from nexent.storage.errors import ScopeDenied

        mock_tenant_usage.side_effect = ScopeDenied()
        resp = client.get("/api/tenants/tenant-b/quota/usage")
        assert resp.status_code == 403

    def test_admin_cannot_access_other_tenant_config(self, client, mock_auth_user, mocker):
        """Tenant A user cannot access Tenant B's quota config."""
        from nexent.storage.errors import ScopeDenied
        mocker.patch.object(quota_app, "read_tenant_quota", side_effect=ScopeDenied())
        resp = client.get("/api/tenants/tenant-b/quota")
        assert resp.status_code == 403


class TestQuotaRoleHelpers:
    """Unit tests for quota role resolution and developer KB visibility."""


    @pytest.mark.asyncio
    async def test_manageable_indices_only_include_edit_permissions(self):
        from time import monotonic

        from nexent.storage.models import OperationContext
        with patch('management.api.knowledge_base.quota.list_knowledge_indices', return_value={'index_permissions': {
            'editable':'EDIT','created':'CREATOR','readonly':'READ_ONLY'}}) as query:
            result = await quota_app._get_manageable_index_names('tenant','user','actual-tenant',
                context=OperationContext('quota-list',monotonic()+10))
            assert result == {'editable','created'}
            assert query.await_args.args[0].tenant_id == 'actual-tenant'
            assert query.await_args.args[1] == 'tenant'


class TestQuotaEndpointErrors:
    """Verify quota endpoints preserve their documented error contracts."""

    def test_get_tenant_quota_maps_service_error(self, client, mock_auth_admin):
        with patch(
            "management.api.knowledge_base.quota.read_tenant_quota", side_effect=RuntimeError("database down")
        ):
            response = client.get("/api/tenants/test-tenant/quota")

        assert response.status_code == 500
        assert "database down" in response.json()["message"]

    def test_get_tenant_quota_timeout_preserves_500_without_duplicate_error_log(self, client, mock_auth_admin, mocker, caplog):
        from nexent.storage.errors import DeadlineExceeded
        read = mocker.patch.object(quota_app, "read_tenant_quota", side_effect=DeadlineExceeded())
        response = client.get("/api/tenants/test-tenant/quota")
        assert response.status_code == 500
        assert "Error getting quota config" in response.json()["message"]
        assert read.await_count == 1
        assert not [record for record in caplog.records if record.levelname == "ERROR" and record.name == quota_app.logger.name]


    def test_platform_overview_maps_service_error(self, client, mock_auth_su, mock_platform_static):
        mock_platform_static["get_platform_overview"].side_effect = RuntimeError("overview failed")
        response = client.get("/api/platform/quota/overview")

        assert response.status_code == 500
        assert "overview failed" in response.json()["message"]


# ═══════════════════════════════════════════════════════════════════════
# Task 12.4 — Upload quota enforcement (HTTP 413 mapping)
# ═══════════════════════════════════════════════════════════════════════

class TestQuotaEnforcementAPI:
    """Integration tests for upload quota enforcement at the API level."""

    @pytest.mark.asyncio
    async def test_upload_route_preserves_quota_exceeded_error(self):
        """The upload route must not rewrite quota errors as generic HTTP 500."""
        error = QuotaExceededError(
            "Storage full",
            usage_bytes=0,
            hard_limit_bytes=1024,
            exceeded_by_bytes=1024,
        )
        upload_file = MagicMock()
        with patch(
            "management.api.file.file_management.get_current_user_id",
            return_value=("user-id", "tenant-id"),
        ), patch(
            "management.api.file.file_management.require_knowledge_base_edit_permission"
        ), patch(
            "management.api.file.file_management.upload_files_impl",
            side_effect=error,
        ):
            with pytest.raises(QuotaExceededError) as raised:
                await upload_files(
                    http_request=None,
                    file=[upload_file],
                    destination="minio",
                    folder="knowledge_base",
                    index_name="test-index",
                    authorization="Bearer token",
                )

        assert raised.value is error

    def test_quota_exceeded_error_returns_413(self):
        """The common app factory maps quota errors to HTTP 413."""
        err = QuotaExceededError(
            "Storage full",
            usage_bytes=95 * GB,
            hard_limit_bytes=100 * GB,
            exceeded_by_bytes=5 * GB,
        )
        app = create_app(enable_monitoring=False)

        @app.get("/quota-error")
        async def raise_quota_error():
            raise err

        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get("/quota-error")

        assert response.status_code == 413
        assert response.json() == {
            "error": "TenantStorageFull",
            "message": "Storage full",
            "usage_bytes": 95 * GB,
            "hard_limit_bytes": 100 * GB,
            "exceeded_by_bytes": 5 * GB,
        }


class TestPersonalCapacityAPI:
    """Integration tests for personal KB capacity endpoints."""

    def test_get_personal_self_capacity_requires_only_authentication(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth(role="USER", user_id="user-1")
        mock_quota_service.get_personal_self_capacity.return_value = {
            "used_bytes": 1024,
            "used_readable": "1.0 KB",
            "quota_bytes": 2048,
            "quota_readable": "2.0 KB",
            "quota_source": "individual",
            "usage_rate": 50.0,
            "is_over_quota": False,
            "kb_count": 1,
        }

        resp = client.get("/api/capacity/personal/me")

        assert resp.status_code == 200
        assert resp.json()["used_bytes"] == 1024
        mock_quota_service.get_personal_self_capacity.assert_called_once_with(
            "user-1"
        )

    def test_get_personal_self_capacity_maps_unavailable_error(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth(role="USER", user_id="user-1")
        mock_quota_service.get_personal_self_capacity.side_effect = (
            AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE, "es down")
        )

        resp = client.get("/api/capacity/personal/me")

        assert resp.status_code == 503
        assert resp.json()["code"] == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE.value

    def test_list_users_allows_admin(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth()
        mock_quota_service.list_personal_capacity_users.return_value = {
            "total": 1,
            "page": 1,
            "page_size": 20,
            "total_pages": 1,
            "items": [{"user_id": "user-1", "total_bytes": 0}],
        }

        resp = client.get("/api/capacity/personal/users")

        assert resp.status_code == 200
        assert resp.json()["items"][0]["user_id"] == "user-1"
        mock_quota_service.list_personal_capacity_users.assert_called_once_with(
            page=1,
            page_size=20,
            sort_by="total_bytes",
            sort_order="desc",
            keyword=None,
        )

    def test_list_users_requires_permission(self, client, mock_personal_auth):
        mock_personal_auth(permission=False)

        resp = client.get("/api/capacity/personal/users")

        assert resp.status_code == 403

    def test_admin_cannot_view_other_tenant(self, client, mock_personal_auth):
        mock_personal_auth(role="ADMIN", tenant_id="test-tenant")

        resp = client.get(
            "/api/capacity/personal/users",
            params={"tenant_id": "other-tenant"},
        )

        assert resp.status_code == 403
        assert "another tenant" in resp.json()["message"]

    @pytest.mark.parametrize("role", ["SU"])
    def test_su_can_view_other_tenant(
        self, client, mock_personal_auth, mock_quota_service, role
    ):
        mock_personal_auth(
            role=role,
            tenant_id="home-tenant",
            user_id="platform-user",
        )
        mock_quota_service.list_personal_capacity_users.return_value = {
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0,
            "items": [],
        }

        resp = client.get(
            "/api/capacity/personal/users",
            params={"tenant_id": "target-tenant"},
        )

        assert resp.status_code == 200
        mock_quota_service.list_personal_capacity_users.assert_called_once_with(
            page=1,
            page_size=20,
            sort_by="total_bytes",
            sort_order="desc",
            keyword=None,
        )

    def test_list_users_passes_keyword_and_usage_rate_sort(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth()
        mock_quota_service.list_personal_capacity_users.return_value = {
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0,
            "items": [],
        }

        resp = client.get(
            "/api/capacity/personal/users",
            params={
                "keyword": "beta",
                "sort_by": "usage_rate",
                "sort_order": "asc",
            },
        )

        assert resp.status_code == 200
        mock_quota_service.list_personal_capacity_users.assert_called_once_with(
            page=1,
            page_size=20,
            sort_by="usage_rate",
            sort_order="asc",
            keyword="beta",
        )

    def test_list_users_maps_service_error(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth()
        mock_quota_service.list_personal_capacity_users.side_effect = RuntimeError(
            "boom"
        )

        resp = client.get("/api/capacity/personal/users")

        assert resp.status_code == 500
        assert "Error listing personal KB capacity" in resp.json()["message"]

    def test_get_user_kbs_allows_admin(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth()
        mock_quota_service.get_personal_kb_details.return_value = {
            "total": 1,
            "page": 1,
            "page_size": 20,
            "total_pages": 1,
            "kbs": [{"kb_id": 1, "index_name": "kb-a"}],
        }

        resp = client.get("/api/capacity/personal/users/user-1/kbs")

        assert resp.status_code == 200
        assert resp.json()["kbs"][0]["kb_id"] == 1
        mock_quota_service.get_personal_kb_details.assert_called_once_with(
            "user-1", page=1, page_size=20
        )

    def test_get_summary_allows_admin(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth()
        mock_quota_service.get_personal_capacity_summary.return_value = {
            "user_count": 3,
            "kb_count": 7,
            "total_bytes": 1024,
            "allocated_quota_bytes": 2048,
        }

        resp = client.get("/api/capacity/personal/summary")

        assert resp.status_code == 200
        assert resp.json()["user_count"] == 3
        mock_quota_service.get_personal_capacity_summary.assert_called_once_with()

    def test_get_summary_requires_permission(
        self, client, mock_personal_auth
    ):
        mock_personal_auth(permission=False)

        resp = client.get("/api/capacity/personal/summary")

        assert resp.status_code == 403

    @pytest.mark.parametrize("role", ["SU"])
    def test_get_summary_su_can_view_other_tenant(
        self, client, mock_personal_auth, mock_quota_service, role
    ):
        mock_personal_auth(
            role=role,
            tenant_id="home-tenant",
            user_id="platform-user",
        )
        mock_quota_service.get_personal_capacity_summary.return_value = {
            "user_count": 1,
            "kb_count": 2,
        }

        resp = client.get(
            "/api/capacity/personal/summary",
            params={"tenant_id": "target-tenant"},
        )

        assert resp.status_code == 200
        mock_quota_service.get_personal_capacity_summary.assert_called_once_with()

    def test_set_user_quota_requires_value_or_unlimited(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = ValueError('Provide quota_limit_bytes or unlimited=true')

        resp = client.put(
            "/api/capacity/personal/users/user-1/quota", json={}
        )

        assert resp.status_code == 400
        assert "Provide quota_limit_bytes" in resp.json()["message"]

    def test_set_user_quota_maps_value_error(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = ValueError(
            "below usage"
        )

        resp = client.put(
            "/api/capacity/personal/users/user-1/quota",
            json={"quota_limit_bytes": 1024},
        )

        assert resp.status_code == 400
        assert "below usage" in resp.json()["message"]

    def test_set_user_quota_returns_localizable_below_usage_error(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = (
            AppException(
                ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE,
                "Personal KB quota 1 KB is below current usage 2 KB",
                details={"quota_limit_bytes": 1024, "usage_bytes": 2048},
            )
        )

        resp = client.put(
            "/api/capacity/personal/users/user-1/quota",
            json={"quota_limit_bytes": 1024},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE.value
        assert resp.json()["details"] == {
            "quota_limit_bytes": 1024,
            "usage_bytes": 2048,
        }

    def test_set_user_quota_maps_quota_exceeded(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = (
            AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED, "too high")
        )

        resp = client.put(
            "/api/capacity/personal/users/user-1/quota",
            json={"quota_limit_bytes": 1024},
        )

        assert resp.status_code == 403
        assert "too high" in resp.json()["message"]
        assert resp.json()["code"] == ErrorCode.TENANT_PERSONAL_KB_QUOTA_EXCEEDED.value

    def test_set_user_quota_maps_service_unavailable(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = (
            AppException(ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE, "es down")
        )

        resp = client.put(
            "/api/capacity/personal/users/user-1/quota",
            json={"quota_limit_bytes": 1024},
        )

        assert resp.status_code == 503
        assert resp.json()["message"] == "es down"
        assert resp.json()["code"] == ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE.value

    def test_set_user_quota_success(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.return_value = {
            "user_id": "user-1",
            "quota_limit_bytes": 1024,
            "quota_limit_readable": "1.0 KB",
        }

        resp = client.put(
            "/api/capacity/personal/users/user-1/quota",
            json={"quota_limit_bytes": 1024},
        )

        assert resp.status_code == 200
        assert resp.json()["quota_limit_bytes"] == 1024
        mock_personal_configuration.assert_awaited_once_with(
            'user-write', 'test-tenant', ServicePrincipal('admin-user-id', 'test-tenant'),
            {'subject_user_id': 'user-1', 'quota_limit_bytes': 1024, 'unlimited': False}
        )

    def test_get_default_quota_returns_unlimited(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.return_value = {'quota_limit_bytes': None, 'quota_limit_readable': None, 'unlimited': True}

        resp = client.get("/api/capacity/personal/default-quota")

        assert resp.status_code == 200
        assert resp.json()["quota_limit_bytes"] is None
        assert resp.json()["unlimited"] is True


    def test_get_default_quota_returns_value(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.return_value = {'quota_limit_bytes': 2048, 'quota_limit_readable': '2.0 KB', 'unlimited': False}

        resp = client.get("/api/capacity/personal/default-quota")

        assert resp.status_code == 200
        assert resp.json()["quota_limit_bytes"] == 2048
        assert resp.json()["unlimited"] is False


    def test_set_default_quota_requires_value_or_unlimited(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        from management.services.knowledge_base.personal_quota_configuration import (
            InvalidPersonalQuotaPayload,
        )

        mock_personal_auth()
        mock_personal_configuration.side_effect = InvalidPersonalQuotaPayload('Provide quota_limit_bytes or unlimited=true')

        resp = client.put(
            "/api/capacity/personal/default-quota", json={}
        )

        assert resp.status_code == 400
        assert "Provide quota_limit_bytes" in resp.json()["message"]

    def test_set_default_quota_success(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.return_value = {
            "quota_limit_bytes": 4096,
            "quota_limit_readable": "4.0 KB",
        }

        resp = client.put(
            "/api/capacity/personal/default-quota",
            json={"quota_limit_bytes": 4096},
        )

        assert resp.status_code == 200
        assert resp.json()["quota_limit_bytes"] == 4096
        mock_personal_configuration.assert_awaited_once_with('write', 'test-tenant', ServicePrincipal('admin-user-id', 'test-tenant'),
            {'quota_limit_bytes': 4096, 'unlimited': False})


    def test_list_users_rejects_unknown_sort_field(self, client, mock_personal_auth):
        mock_personal_auth()

        response = client.get(
            "/api/capacity/personal/users",
            params={"sort_by": "created_at"},
        )

        assert response.status_code == 400
        assert "sort_by must be one of" in response.json()["message"]

    def test_list_users_rejects_unknown_sort_order(self, client, mock_personal_auth):
        mock_personal_auth()

        response = client.get(
            "/api/capacity/personal/users",
            params={"sort_order": "sideways"},
        )

        assert response.status_code == 400
        assert "sort_order must be asc or desc" in response.json()["message"]

    def test_get_user_kbs_maps_unexpected_service_error(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth()
        mock_quota_service.get_personal_kb_details.side_effect = RuntimeError("db down")

        response = client.get("/api/capacity/personal/users/user-1/kbs")

        assert response.status_code == 500
        assert "Error getting personal KB details" in response.json()["message"]

    def test_get_summary_maps_unexpected_service_error(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth()
        mock_quota_service.get_personal_capacity_summary.side_effect = RuntimeError(
            "db down"
        )

        response = client.get("/api/capacity/personal/summary")

        assert response.status_code == 500
        assert "Error getting personal KB capacity summary" in response.json()["message"]

    def test_set_user_quota_unlimited_clears_quota(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.return_value = {
            "user_id": "user-1",
            "quota_limit_bytes": None,
        }

        response = client.put(
            "/api/capacity/personal/users/user-1/quota",
            json={"unlimited": True},
        )

        assert response.status_code == 200
        mock_personal_configuration.assert_awaited_once_with(
            'user-write', 'test-tenant', ServicePrincipal('admin-user-id', 'test-tenant'),
            {'subject_user_id': 'user-1', 'quota_limit_bytes': None, 'unlimited': True}
        )

    def test_set_user_quota_maps_unexpected_service_error(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = RuntimeError("db down")

        response = client.put(
            "/api/capacity/personal/users/user-1/quota",
            json={"quota_limit_bytes": 1024},
        )

        assert response.status_code == 500
        assert "Error setting personal KB quota" in response.json()["message"]

    def test_get_default_quota_maps_unexpected_service_error(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = RuntimeError(
            "db down"
        )

        response = client.get("/api/capacity/personal/default-quota")

        assert response.status_code == 500
        assert "Error getting personal KB default quota" in response.json()["message"]


    def test_set_default_quota_unlimited_clears_quota(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.return_value = {
            "quota_limit_bytes": None,
        }

        response = client.put(
            "/api/capacity/personal/default-quota",
            json={"unlimited": True},
        )

        assert response.status_code == 200
        mock_personal_configuration.assert_awaited_once_with('write', 'test-tenant', ServicePrincipal('admin-user-id', 'test-tenant'),
            {'quota_limit_bytes': None, 'unlimited': True})


    def test_set_default_quota_maps_unexpected_service_error(
        self, client, mock_personal_auth, mock_personal_configuration
    ):
        mock_personal_auth()
        mock_personal_configuration.side_effect = RuntimeError(
            "db down"
        )

        response = client.put(
            "/api/capacity/personal/default-quota",
            json={"quota_limit_bytes": 1024},
        )

        assert response.status_code == 500
        assert "Error setting personal KB default quota" in response.json()["message"]


    def test_get_personal_self_capacity_maps_unexpected_service_error(
        self, client, mock_personal_auth, mock_quota_service
    ):
        mock_personal_auth(role="USER", user_id="user-1")
        mock_quota_service.get_personal_self_capacity.side_effect = RuntimeError(
            "db down"
        )

        response = client.get("/api/capacity/personal/me")

        assert response.status_code == 500
        assert "Error getting personal KB capacity" in response.json()["message"]


class TestTokenExpiredMapping:
    """Every quota endpoint maps an expired token to 401."""

    @pytest.mark.parametrize(
        "method,url,payload",
        [
            ("get", "/api/tenants/test-tenant/quota", None),
            ("put", "/api/tenants/test-tenant/quota", {"hard_limit_gb": 50}),
            ("delete", "/api/tenants/test-tenant/quota", None),
            ("get", "/api/tenants/test-tenant/quota/usage", None),
        ],
    )
    def test_tenant_quota_endpoints_token_expired(self, client, method, url, payload):
        from contracts.errors.exceptions import TokenExpiredError

        with patch(
            "management.api.knowledge_base.quota.get_current_user_id",
            side_effect=TokenExpiredError("expired"),
        ):
            kwargs = {}
            if payload is not None:
                kwargs["json"] = payload
            response = getattr(client, method)(url, **kwargs)

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "method,url,payload",
        [
            ("get", "/api/platform/quota/overview", None),
            ("put", "/api/platform/quota/capacity", {"capacity_gb": 100}),
            ("delete", "/api/platform/quota/capacity", None),
            ("put", "/api/platform/quota/tenants/target-tenant", {"hard_limit_gb": 100}),
            ("delete", "/api/platform/quota/tenants/target-tenant", None),
        ],
    )
    def test_platform_quota_endpoints_token_expired(self, client, method, url, payload):
        from contracts.errors.exceptions import TokenExpiredError

        with patch(
            "management.api.knowledge_base.quota.get_current_user_id",
            side_effect=TokenExpiredError("expired"),
        ):
            kwargs = {}
            if payload is not None:
                kwargs["json"] = payload
            response = getattr(client, method)(url, **kwargs)

        assert response.status_code == 401


@pytest.fixture
def mock_personal_configuration(mocker):
    return mocker.patch.object(quota_app, 'personal_quota_configuration', new_callable=AsyncMock)
