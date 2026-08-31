"""
Unit tests for northbound_user_app tenant-admin user creation endpoint.

The northbound app package pulls in the whole backend runtime (supabase,
sqlalchemy, redis ...), so the collaborators are stubbed through ``sys.modules``
before the module under test is imported. This mirrors the setup used by
``test_northbound_knowledge_app.py``.
"""
import os
import sys
import types
from dataclasses import dataclass
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


@dataclass
class NorthboundContext:
    request_id: str
    tenant_id: str
    user_id: str
    authorization: str
    token_id: int = 0


# ---------------------------------------------------------------------------
# Stub the collaborators
# ---------------------------------------------------------------------------
services_pkg = types.ModuleType("services")
services_pkg.__path__ = [os.path.join(backend_dir, "services")]
sys.modules["services"] = services_pkg

northbound_service_module = types.ModuleType("services.northbound_service")
northbound_service_module.NorthboundContext = NorthboundContext
sys.modules["services.northbound_service"] = northbound_service_module

user_management_service_module = types.ModuleType("services.user_management_service")
user_management_service_module.create_user_as_tenant_admin = AsyncMock()
user_management_service_module.ADMIN_CREATABLE_ROLES = ("USER", "DEV", "ADMIN")
sys.modules["services.user_management_service"] = user_management_service_module

database_pkg = types.ModuleType("database")
database_pkg.__path__ = [os.path.join(backend_dir, "database")]
sys.modules["database"] = database_pkg

user_tenant_db_module = types.ModuleType("database.user_tenant_db")
user_tenant_db_module.get_user_role_by_tenant = MagicMock(return_value="ADMIN")
sys.modules["database.user_tenant_db"] = user_tenant_db_module

# consts.exceptions only depends on the stdlib, so load the real module and
# keep the genuine ErrorCode -> HTTP status mapping under test.
consts_pkg = types.ModuleType("consts")
consts_pkg.__path__ = [os.path.join(backend_dir, "consts")]
sys.modules["consts"] = consts_pkg

northbound_app_module = types.ModuleType("apps.northbound_app")
northbound_app_module._get_northbound_context = AsyncMock()
sys.modules["apps.northbound_app"] = northbound_app_module

from apps.northbound_user_app import router  # noqa: E402
from consts.error_code import ErrorCode  # noqa: E402
from consts.exceptions import (  # noqa: E402
    AppException,
    TenantResourceLimitError,
    UserRegistrationException,
)

TENANT_ID = "tenant-1"
ADMIN_USER_ID = "admin-user-1"
NEW_USER_EMAIL = "new.user@example.com"
VALID_PASSWORD = "Passw0rd1"

CREATE_URL = "/nb/v1/users"


def make_ctx(user_id: str = ADMIN_USER_ID, tenant_id: str = TENANT_ID) -> NorthboundContext:
    return NorthboundContext(
        request_id="req-1",
        tenant_id=tenant_id,
        user_id=user_id,
        authorization="Bearer nb-api-key",
    )


def success_payload(role: str = "USER", email: str = NEW_USER_EMAIL):
    return {
        "user_id": "new-user-1",
        "user_email": email,
        "user_role": role,
        "tenant_id": TENANT_ID,
    }


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_collaborators():
    """Give every test a clean ADMIN caller and a successful service call."""
    role_mock = user_tenant_db_module.get_user_role_by_tenant
    role_mock.reset_mock()
    role_mock.side_effect = None
    role_mock.return_value = "ADMIN"

    create_mock = user_management_service_module.create_user_as_tenant_admin
    create_mock.reset_mock()
    create_mock.side_effect = None
    create_mock.return_value = success_payload()

    with patch(
        "apps.northbound_user_app._get_northbound_context", new_callable=AsyncMock
    ) as ctx_mock:
        ctx_mock.return_value = make_ctx()
        yield ctx_mock


class TestTenantAdminGate:
    """Only the ADMIN role inside the resolved tenant may create users."""

    @pytest.mark.parametrize("role", ["USER", "DEV", "SU", "OWNER"])
    def test_non_admin_roles_rejected(self, client, role):
        user_tenant_db_module.get_user_role_by_tenant.return_value = role

        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert "tenant administrator" in response.json()["detail"]
        user_management_service_module.create_user_as_tenant_admin.assert_not_called()

    def test_absent_role_rejected(self, client):
        """A caller with no tenant relationship has no role and is rejected."""
        user_tenant_db_module.get_user_role_by_tenant.return_value = None

        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.FORBIDDEN
        user_management_service_module.create_user_as_tenant_admin.assert_not_called()

    @pytest.mark.parametrize("role", ["ADMIN", "admin", "Admin"])
    def test_admin_role_allowed_regardless_of_case(self, client, role):
        user_tenant_db_module.get_user_role_by_tenant.return_value = role

        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.CREATED

    def test_role_resolved_against_caller_tenant(self, client):
        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.CREATED
        user_tenant_db_module.get_user_role_by_tenant.assert_called_once_with(
            ADMIN_USER_ID, TENANT_ID
        )

    def test_role_lookup_failure_returns_500(self, client):
        user_tenant_db_module.get_user_role_by_tenant.side_effect = RuntimeError("db down")

        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        user_management_service_module.create_user_as_tenant_admin.assert_not_called()


class TestCreateUser:
    def test_creates_user_with_default_role(self, client):
        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.CREATED
        assert response.json() == success_payload(role="USER")
        user_management_service_module.create_user_as_tenant_admin.assert_awaited_once_with(
            tenant_id=TENANT_ID,
            email=NEW_USER_EMAIL,
            initial_password=VALID_PASSWORD,
            created_by=ADMIN_USER_ID,
            name=None,
            role="USER",
        )

    def test_creates_user_with_explicit_role_and_name(self, client):
        user_management_service_module.create_user_as_tenant_admin.return_value = (
            success_payload(role="DEV")
        )

        response = client.post(
            CREATE_URL,
            json={
                "email": NEW_USER_EMAIL,
                "initial_password": VALID_PASSWORD,
                "name": "New User",
                "role": "DEV",
            },
        )

        assert response.status_code == HTTPStatus.CREATED
        assert response.json()["user_role"] == "DEV"
        user_management_service_module.create_user_as_tenant_admin.assert_awaited_once_with(
            tenant_id=TENANT_ID,
            email=NEW_USER_EMAIL,
            initial_password=VALID_PASSWORD,
            created_by=ADMIN_USER_ID,
            name="New User",
            role="DEV",
        )

    def test_response_is_mapped_from_service_result(self, client):
        user_management_service_module.create_user_as_tenant_admin.return_value = {
            "user_id": "another-user",
            "user_email": "another@example.com",
            "user_role": "ADMIN",
            "tenant_id": TENANT_ID,
        }

        response = client.post(
            CREATE_URL,
            json={
                "email": "another@example.com",
                "initial_password": VALID_PASSWORD,
                "role": "ADMIN",
            },
        )

        assert response.status_code == HTTPStatus.CREATED
        assert response.json() == {
            "user_id": "another-user",
            "user_email": "another@example.com",
            "user_role": "ADMIN",
            "tenant_id": TENANT_ID,
        }

    def test_weak_password_returns_400(self, client):
        user_management_service_module.create_user_as_tenant_admin.side_effect = AppException(
            ErrorCode.PROFILE_PASSWORD_WEAK, "Password must be stronger."
        )

        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": "password"}
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json()["detail"] == "Password must be stronger."

    def test_duplicate_email_returns_409(self, client):
        user_management_service_module.create_user_as_tenant_admin.side_effect = (
            UserRegistrationException(f"Email {NEW_USER_EMAIL} is already registered")
        )

        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.CONFLICT

    def test_tenant_resource_limit_returns_400(self, client):
        """TenantResourceLimitError is a ValueError subclass and must stay 400."""
        user_management_service_module.create_user_as_tenant_admin.side_effect = (
            TenantResourceLimitError("Maximum number of administrators reached")
        )

        response = client.post(
            CREATE_URL,
            json={
                "email": NEW_USER_EMAIL,
                "initial_password": VALID_PASSWORD,
                "role": "ADMIN",
            },
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "administrators" in response.json()["detail"]

    def test_unsupported_role_returns_400(self, client):
        user_management_service_module.create_user_as_tenant_admin.side_effect = ValueError(
            "Unsupported role 'SU'. Allowed roles: USER, DEV, ADMIN"
        )

        response = client.post(
            CREATE_URL,
            json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD, "role": "SU"},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Unsupported role" in response.json()["detail"]

    def test_unexpected_error_returns_500(self, client):
        user_management_service_module.create_user_as_tenant_admin.side_effect = RuntimeError(
            "supabase exploded"
        )

        response = client.post(
            CREATE_URL, json={"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD}
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Failed to create user"


class TestRequestValidation:
    """Pydantic guards run before the permission check."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": "not-an-email", "initial_password": VALID_PASSWORD},
            {"email": NEW_USER_EMAIL, "initial_password": "short"},
            {"email": NEW_USER_EMAIL},
            {"email": NEW_USER_EMAIL, "initial_password": VALID_PASSWORD, "unexpected": 1},
        ],
    )
    def test_invalid_payload_returns_422(self, client, payload):
        response = client.post(CREATE_URL, json=payload)

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        user_tenant_db_module.get_user_role_by_tenant.assert_not_called()
        user_management_service_module.create_user_as_tenant_admin.assert_not_called()
