"""Unit tests for backend.apps.api_key_app endpoints."""
from http import HTTPStatus
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api_key_app import router
from consts.exceptions import ForbiddenError, NotFoundException, UnauthorizedError, ValidationError


app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestApiKeyEndpoints:
    @patch("apps.api_key_app.list_tenant_api_keys")
    @patch("apps.api_key_app.get_current_user_context")
    def test_list_api_keys_passes_paging_and_requester_context(self, mock_context, mock_list):
        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")
        mock_list.return_value = {"items": [{"user_id": "user-1"}], "total": 1}

        response = client.get(
            "/api-keys?tenant_id=tenant-1&page=2&page_size=10&sort_order=asc",
            headers={"Authorization": "Bearer token"},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.json()["data"]["total"] == 1
        mock_list.assert_called_once_with(
            actor_tenant_id="tenant-1",
            actor_role="ADMIN",
            tenant_id="tenant-1",
            page=2,
            page_size=10,
            sort_order="asc",
        )

    @patch("apps.api_key_app.refresh_user_api_key")
    @patch("apps.api_key_app.get_current_user_context")
    def test_refresh_api_key_uses_email_target(self, mock_context, mock_refresh):
        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")
        mock_refresh.return_value = {"api_key": "nexent-new-key"}

        response = client.post(
            "/api-keys/refresh",
            headers={"Authorization": "Bearer token"},
            json={"email": "api.user@example.com"},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.json()["data"]["api_key"] == "nexent-new-key"
        mock_refresh.assert_called_once_with(
            actor_user_id="admin-1",
            actor_tenant_id="tenant-1",
            actor_role="ADMIN",
            user_id=None,
            email="api.user@example.com",
        )

    @patch("apps.api_key_app.revoke_user_api_keys")
    @patch("apps.api_key_app.get_current_user_context")
    def test_revoke_api_key_uses_user_id_target(self, mock_context, mock_revoke):
        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")
        mock_revoke.return_value = {"revoked_count": 2}

        response = client.delete(
            "/api-keys?user_id=user-1",
            headers={"Authorization": "Bearer token"},
        )

        assert response.status_code == HTTPStatus.OK
        assert response.json()["data"] == {"revoked_count": 2}
        mock_revoke.assert_called_once_with(
            actor_user_id="admin-1",
            actor_tenant_id="tenant-1",
            actor_role="ADMIN",
            user_id="user-1",
            email=None,
        )

    @patch("apps.api_key_app.list_tenant_api_keys", side_effect=UnauthorizedError("invalid token"))
    @patch("apps.api_key_app.get_current_user_context")
    def test_list_api_keys_maps_service_authorization_error(self, mock_context, _):
        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")

        response = client.get("/api-keys?tenant_id=tenant-1", headers={"Authorization": "Bearer token"})

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json()["detail"] == "invalid token"

    @patch("apps.api_key_app.refresh_user_api_key", side_effect=NotFoundException("user missing"))
    @patch("apps.api_key_app.get_current_user_context")
    def test_refresh_api_key_maps_missing_user_error(self, mock_context, _):
        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")

        response = client.post(
            "/api-keys/refresh",
            headers={"Authorization": "Bearer token"},
            json={"user_id": "user-1"},
        )

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json()["detail"] == "user missing"

    def test_revoke_api_key_rejects_missing_or_duplicate_targets(self):
        missing_response = client.delete("/api-keys", headers={"Authorization": "Bearer token"})
        duplicate_response = client.delete(
            "/api-keys?user_id=user-1&email=api.user@example.com",
            headers={"Authorization": "Bearer token"},
        )

        assert missing_response.status_code == HTTPStatus.BAD_REQUEST
        assert duplicate_response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (UnauthorizedError("invalid token"), HTTPStatus.UNAUTHORIZED),
        (ForbiddenError("not allowed"), HTTPStatus.FORBIDDEN),
        (NotFoundException("missing"), HTTPStatus.NOT_FOUND),
        (ValidationError("invalid request"), HTTPStatus.BAD_REQUEST),
        (ValueError("invalid value"), HTTPStatus.BAD_REQUEST),
    ],
)
def test_map_error_maps_domain_exceptions_to_http_status(exception, expected_status):
    from apps.api_key_app import _map_error

    with pytest.raises(HTTPException) as raised:
        _map_error(exception)

    assert raised.value.status_code == expected_status


def test_map_error_reraises_unexpected_exception():
    from apps.api_key_app import _map_error

    unexpected = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        _map_error(unexpected)


class TestApiKeyAuditEntries:
    @patch("apps.api_key_app.refresh_user_api_key")
    @patch("apps.api_key_app.get_current_user_context")
    def test_refresh_success_emits_audit_entry(self, mock_context, mock_refresh, caplog):
        import logging

        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")
        mock_refresh.return_value = {"api_key": "nexent-new-key"}

        with caplog.at_level(logging.INFO, logger="audit.security"):
            response = client.post(
                "/api-keys/refresh",
                headers={"Authorization": "Bearer token"},
                json={"user_id": "user-1"},
            )

        assert response.status_code == HTTPStatus.OK
        message = caplog.records[-1].getMessage()
        assert "[SEC_AUDIT]" in message
        assert "event=api_key_refresh" in message
        assert "result=success" in message
        assert "user_id=admin-1" in message
        assert 'details={"target_user_id":"user-1","target_email":null}' in message

    @patch("apps.api_key_app.refresh_user_api_key", side_effect=ForbiddenError("not allowed"))
    @patch("apps.api_key_app.get_current_user_context")
    def test_refresh_failure_emits_reason(self, mock_context, _, caplog):
        import logging

        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")

        with caplog.at_level(logging.INFO, logger="audit.security"):
            response = client.post(
                "/api-keys/refresh",
                headers={"Authorization": "Bearer token"},
                json={"email": "api.user@example.com"},
            )

        assert response.status_code == HTTPStatus.FORBIDDEN
        message = caplog.records[-1].getMessage()
        assert "event=api_key_refresh" in message
        assert "result=failure" in message
        assert "reason=forbidden" in message
        assert "user_id=admin-1" in message

    @patch("apps.api_key_app.revoke_user_api_keys")
    @patch("apps.api_key_app.get_current_user_context")
    def test_revoke_success_emits_audit_entry(self, mock_context, mock_revoke, caplog):
        import logging

        mock_context.return_value = ("admin-1", "tenant-1", "ADMIN")
        mock_revoke.return_value = {"revoked_count": 2}

        with caplog.at_level(logging.INFO, logger="audit.security"):
            response = client.delete(
                "/api-keys?user_id=user-1",
                headers={"Authorization": "Bearer token"},
            )

        assert response.status_code == HTTPStatus.OK
        message = caplog.records[-1].getMessage()
        assert "event=api_key_revoke" in message
        assert "result=success" in message
        assert 'details={"target_user_id":"user-1","target_email":null}' in message
