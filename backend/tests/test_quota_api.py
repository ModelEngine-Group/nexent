"""
Integration tests for quota API endpoints.

Tests the full request/response cycle using FastAPI TestClient
with mocked authentication and database dependencies.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from fastapi import HTTPException
from apps.app_factory import create_app
from apps.file_management_app import upload_files
from apps.quota_app import tenant_quota_router, platform_quota_router
from consts.exceptions import QuotaExceededError

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
    return app


@pytest.fixture
def client():
    """TestClient with mocked auth and DB."""
    app = _make_test_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_auth_admin():
    """Mock auth to return an ADMIN user."""
    with patch("apps.quota_app.get_current_user_id") as mock_auth, \
         patch("apps.quota_app.get_user_tenant_by_user_id") as mock_tenant, \
         patch("apps.quota_app._get_user_role") as mock_role, \
         patch("apps.quota_app._require_admin_or_su") as mock_require:
        mock_auth.return_value = ("admin-user-id", "test-tenant")
        mock_tenant.return_value = {"user_role": "ADMIN", "tenant_id": "test-tenant"}
        mock_role.return_value = "ADMIN"
        mock_require.return_value = "ADMIN"
        yield


@pytest.fixture
def mock_auth_su():
    """Mock auth to return an SU user."""
    with patch("apps.quota_app.get_current_user_id") as mock_auth, \
         patch("apps.quota_app.get_user_tenant_by_user_id") as mock_tenant, \
         patch("apps.quota_app._get_user_role") as mock_role, \
         patch("apps.quota_app._require_admin_or_su") as mock_require_admin, \
         patch("apps.quota_app._require_su_or_asset_owner") as mock_require_su:
        mock_auth.return_value = ("su-user-id", "asset_owner_tenant_id")
        mock_tenant.return_value = {"user_role": "SU", "tenant_id": "asset_owner_tenant_id"}
        mock_role.return_value = "SU"
        mock_require_admin.return_value = "SU"
        mock_require_su.return_value = "SU"
        yield


@pytest.fixture
def mock_auth_user():
    """Mock auth to return a regular USER."""
    with patch("apps.quota_app.get_current_user_id") as mock_auth, \
         patch("apps.quota_app.get_user_tenant_by_user_id") as mock_tenant, \
         patch("apps.quota_app._get_user_role") as mock_role, \
         patch("apps.quota_app._require_admin_or_su") as mock_require:
        mock_auth.return_value = ("user-id", "test-tenant")
        mock_tenant.return_value = {"user_role": "USER", "tenant_id": "test-tenant"}
        mock_role.return_value = "USER"
        mock_require.side_effect = HTTPException(
            status_code=403, detail="Requires ADMIN+"
        )
        yield


@pytest.fixture
def mock_quota_service():
    """Mock QuotaService instance methods for integration tests."""
    with patch("apps.quota_app.QuotaService") as mock_class:
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_platform_static():
    """Mock QuotaService static platform methods."""
    with patch("apps.quota_app.QuotaService.get_platform_overview") as mock_overview, \
         patch("apps.quota_app.QuotaService.set_platform_capacity") as mock_set_cap, \
         patch("apps.quota_app.QuotaService.set_tenant_hard_limit") as mock_set_tenant, \
         patch("apps.quota_app.QuotaService.delete_tenant_hard_limit") as mock_del:
        yield {
            "get_platform_overview": mock_overview,
            "set_platform_capacity": mock_set_cap,
            "set_tenant_hard_limit": mock_set_tenant,
            "delete_tenant_hard_limit": mock_del,
        }


# ═══════════════════════════════════════════════════════════════════════
# Task 12.1 — GET /tenants/{id}/quota
# ═══════════════════════════════════════════════════════════════════════

class TestGetTenantQuota:
    """Integration tests for GET /tenants/{id}/quota."""

    def test_returns_config_structure(self, client, mock_auth_admin, mock_quota_service):
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

        resp = client.get("/api/tenants/test-tenant/quota")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hard_limit_bytes"] == 100 * GB
        assert data["hard_limit_readable"] == "100.0 GB"
        assert data["hard_limit_editable"] is True
        assert data["warning_enabled"] is True
        assert data["warning_threshold_pct"] == 80
        assert "summary" in data

    def test_returns_forbidden_for_cross_tenant_access(self, client, mock_auth_user):
        resp = client.get("/api/tenants/other-tenant/quota")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Task 12.2 — PUT /tenants/{id}/quota
# ═══════════════════════════════════════════════════════════════════════

class TestPutTenantQuota:
    """Integration tests for PUT /tenants/{id}/quota."""

    def test_sets_hard_limit_when_editable(self, client, mock_auth_admin, mock_quota_service):
        mock_quota_service.get_hard_limit.return_value = {
            "hard_limit_bytes": None,
            "hard_limit_readable": None,
            "hard_limit_editable": True,
        }
        mock_quota_service.set_hard_limit.return_value = {
            "hard_limit_bytes": 50 * GB,
            "hard_limit_readable": "50.0 GB",
        }
        mock_quota_service.get_warning_config.return_value = {
            "warning_enabled": True,
            "warning_threshold_pct": 80,
            "critical_threshold_pct": 95,
        }

        resp = client.put(
            "/api/tenants/test-tenant/quota",
            json={"hard_limit_gb": 50},
        )
        assert resp.status_code == 200

    def test_rejects_when_not_editable(self, client, mock_auth_admin, mock_quota_service):
        mock_quota_service.get_hard_limit.return_value = {
            "hard_limit_bytes": 100 * GB,
            "hard_limit_readable": "100.0 GB",
            "hard_limit_editable": False,  # set by SU
        }

        resp = client.put(
            "/api/tenants/test-tenant/quota",
            json={"hard_limit_gb": 200},
        )
        assert resp.status_code == 403
        body = resp.json()
        msg = (body.get("message") or body.get("detail") or "").lower()
        assert "platform administrator" in msg

    def test_rejects_for_regular_user(self, client, mock_auth_user):
        resp = client.put(
            "/api/tenants/test-tenant/quota",
            json={"hard_limit_gb": 50},
        )
        assert resp.status_code == 403

    def test_sets_warning_config(self, client, mock_auth_admin, mock_quota_service):
        mock_quota_service.get_hard_limit.return_value = {
            "hard_limit_bytes": None,
            "hard_limit_readable": None,
            "hard_limit_editable": True,
        }
        mock_quota_service.get_warning_config.return_value = {
            "warning_enabled": False,
            "warning_threshold_pct": 70,
            "critical_threshold_pct": 90,
        }

        resp = client.put(
            "/api/tenants/test-tenant/quota",
            json={"warning_enabled": False, "warning_threshold_pct": 70, "critical_threshold_pct": 90},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# Task 12.3 — GET /tenants/{id}/quota/usage
# ═══════════════════════════════════════════════════════════════════════

class TestGetTenantQuotaUsage:
    """Integration tests for GET /tenants/{id}/quota/usage."""

    def test_returns_usage_structure(self, client, mock_auth_admin, mock_quota_service):
        mock_quota_service.get_usage.return_value = {
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
        }

        resp = client.get("/api/tenants/test-tenant/quota/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_bytes"] == 50 * GB
        assert data["usage_pct"] == 50.0
        assert data["tenant_warning_level"] == "normal"

    def test_detail_includes_breakdown(self, client, mock_auth_admin, mock_quota_service):
        mock_quota_service.get_usage.return_value = {
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
        }

        resp = client.get("/api/tenants/test-tenant/quota/usage?detail=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "breakdown" in data
        assert len(data["breakdown"]) == 2

    def test_force_refresh_param_accepted(self, client, mock_auth_admin, mock_quota_service):
        mock_quota_service.get_usage.return_value = {
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
        }

        resp = client.get("/api/tenants/test-tenant/quota/usage?force_refresh=true")
        assert resp.status_code == 200
        # verify force_refresh was passed as True
        mock_quota_service.get_usage.assert_called_with(force_refresh=True, detail=False)

    def test_user_detail_filters_inaccessible_knowledge_bases(
        self, client, mock_auth_user, mock_quota_service
    ):
        mock_quota_service.get_usage.return_value = {
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
        }

        with patch(
            "apps.quota_app._get_manageable_index_names",
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

    def test_get_overview_denied_for_admin(self, client, mock_auth_admin):
        resp = client.get("/api/platform/quota/overview")
        assert resp.status_code == 403

    def test_put_capacity_requires_su(self, client, mock_auth_su, mock_platform_static):
        mock_platform_static["set_platform_capacity"].return_value = {
            "capacity_bytes": 500 * GB,
            "capacity_readable": "500.0 GB",
        }

        resp = client.put("/api/platform/quota/capacity", json={"capacity_gb": 500})
        assert resp.status_code == 200

    def test_put_capacity_denied_for_admin(self, client, mock_auth_admin):
        resp = client.put("/api/platform/quota/capacity", json={"capacity_gb": 500})
        assert resp.status_code == 403

    def test_put_tenant_hard_quota(self, client, mock_auth_su, mock_platform_static):
        mock_platform_static["set_tenant_hard_limit"].return_value = {
            "hard_limit_bytes": 100 * GB,
            "hard_limit_readable": "100.0 GB",
        }

        resp = client.put(
            "/api/platform/quota/tenants/target-tenant",
            json={"hard_limit_gb": 100},
        )
        assert resp.status_code == 200

    def test_delete_tenant_hard_quota(self, client, mock_auth_su, mock_platform_static):
        mock_platform_static["delete_tenant_hard_limit"].return_value = True

        resp = client.delete("/api/platform/quota/tenants/target-tenant")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# Task 12.6 — Tenant Isolation
# ═══════════════════════════════════════════════════════════════════════

class TestTenantIsolation:
    """Integration tests for tenant data isolation."""

    def test_admin_cannot_access_other_tenant_usage(self, client, mock_auth_user):
        """Tenant A user cannot access Tenant B's usage."""
        resp = client.get("/api/tenants/tenant-b/quota/usage")
        assert resp.status_code == 403

    def test_admin_cannot_access_other_tenant_config(self, client, mock_auth_user):
        """Tenant A user cannot access Tenant B's quota config."""
        resp = client.get("/api/tenants/tenant-b/quota")
        assert resp.status_code == 403

    def test_admin_cannot_modify_other_tenant_quota(self, client, mock_auth_admin):
        """ADMIN of Tenant A cannot modify Tenant B's quota."""
        resp = client.put(
            "/api/tenants/tenant-b/quota",
            json={"hard_limit_gb": 100},
        )
        assert resp.status_code == 403


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
        with patch(
            "apps.file_management_app.get_current_user_id",
            return_value=("user-id", "tenant-id"),
        ), patch(
            "apps.file_management_app.upload_files_impl",
            side_effect=error,
        ):
            with pytest.raises(QuotaExceededError) as raised:
                await upload_files(
                    file=[MagicMock()],
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
