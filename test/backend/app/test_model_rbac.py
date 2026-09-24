"""RBAC coverage tests for model management endpoints.

Verifies that mutating /model/* endpoints reject the DEV role (which only
holds model:read), read endpoints stay accessible to DEV, and the
cross-tenant /manage/* endpoints are restricted to SU.
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from http import HTTPStatus

# Add project root to sys.path so that the top-level `backend` package is importable
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Patch storage factory and MinIO config validation to avoid errors during
# initialization, mirroring test_model_managment_app.py.
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()


def _make_client(mocker, role: str, granted_permissions: set) -> TestClient:
    """Build a TestClient whose user has the given role and permissions."""
    mocker.patch('boto3.client')
    mocker.patch('backend.database.client.MinioClient')

    import types
    import sys as _sys
    if "management.services.knowledge_base.service" not in _sys.modules:
        services_vdb_mod = types.ModuleType("management.services.knowledge_base.service")

        def _get_vector_db_core():  # minimal stub
            return object()

        services_vdb_mod.get_vector_db_core = _get_vector_db_core
        _sys.modules["management.services.knowledge_base.service"] = services_vdb_mod

    from backend.apps.model_managment_app import router
    from permissions.depends import authenticate
    from permissions.models import CurrentUser

    mocker.patch(
        'permissions.depends.has_permission',
        side_effect=lambda _role, permission: permission in granted_permissions,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[authenticate] = lambda: CurrentUser(
        user_id="rbac_user", tenant_id="rbac_tenant", role=role)
    return TestClient(app)


# DEV holds only model:read in role_permission_t seeds.
_DEV_PERMISSIONS = {"model:read"}
_ADMIN_PERMISSIONS = {"model:create", "model:read", "model:update", "model:delete"}


@pytest.fixture
def dev_client(mocker):
    return _make_client(mocker, "DEV", _DEV_PERMISSIONS)


@pytest.fixture
def admin_client(mocker):
    return _make_client(mocker, "ADMIN", _ADMIN_PERMISSIONS)


@pytest.fixture
def su_client(mocker):
    # SU shares the ADMIN model seeds plus the manage role check.
    return _make_client(mocker, "SU", _ADMIN_PERMISSIONS)


auth_header = {"Authorization": "Bearer rbac_token"}


@pytest.mark.asyncio
async def test_dev_cannot_create_model(dev_client, mocker):
    mocker.patch(
        'backend.apps.model_managment_app.create_model_for_tenant',
        return_value={"auto_configured_defaults": []},
    )
    response = dev_client.post(
        "/model/create",
        json={
            "model_name": "openai/gpt-4o",
            "display_name": "GPT-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model_type": "llm",
            "model_factory": "openai",
        },
        headers=auth_header,
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_dev_cannot_update_model(dev_client):
    response = dev_client.post(
        "/model/update",
        params={"display_name": "GPT-4o"},
        json={"display_name": "GPT-4o-mini"},
        headers=auth_header,
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_dev_cannot_delete_model(dev_client):
    response = dev_client.post(
        "/model/delete",
        params={"display_name": "GPT-4o"},
        headers=auth_header,
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_dev_cannot_healthcheck_model(dev_client):
    response = dev_client.post(
        "/model/healthcheck",
        params={"display_name": "GPT-4o", "model_type": "llm"},
        headers=auth_header,
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_dev_can_read_model_list(dev_client, mocker):
    mocker.patch(
        'backend.apps.model_managment_app.list_models_for_tenant',
        return_value=[],
    )
    response = dev_client.get("/model/list", headers=auth_header)
    assert response.status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_dev_can_read_llm_list(dev_client, mocker):
    mocker.patch(
        'backend.apps.model_managment_app.list_llm_models_for_tenant',
        return_value=[],
    )
    response = dev_client.get("/model/llm_list", headers=auth_header)
    assert response.status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_admin_can_create_model(admin_client, mocker):
    mocker.patch(
        'backend.apps.model_managment_app.create_model_for_tenant',
        return_value={"auto_configured_defaults": []},
    )
    mocker.patch(
        'backend.apps.model_managment_app.pop_capacity_accept_signal',
        return_value=None,
    )
    response = admin_client.post(
        "/model/create",
        json={
            "model_name": "openai/gpt-4o",
            "display_name": "GPT-4o",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "model_type": "llm",
            "model_factory": "openai",
        },
        headers=auth_header,
    )
    assert response.status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_admin_cannot_access_manage_endpoints(admin_client, mocker):
    """ADMIN shares the SU model seeds, so manage/* must fall back to the
    SU role whitelist."""
    mocker.patch(
        'backend.apps.model_managment_app.list_models_for_admin',
        return_value={"models": [], "total": 0},
    )
    response = admin_client.post(
        "/model/manage/list",
        json={"tenant_id": "other_tenant", "page": 1, "page_size": 10},
        headers=auth_header,
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_su_can_access_manage_endpoints(su_client, mocker):
    mocker.patch(
        'backend.apps.model_managment_app.list_models_for_admin',
        return_value={"models": [], "total": 0},
    )
    response = su_client.post(
        "/model/manage/list",
        json={"tenant_id": "other_tenant", "page": 1, "page_size": 10},
        headers=auth_header,
    )
    assert response.status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_speed_role_bypasses_permission_checks(mocker):
    """SPEED passes require() without seeds, matching permissions.depends."""
    mocker.patch('permissions.depends.IS_SPEED_MODE', True)

    client = _make_client(mocker, "SPEED", set())
    mocker.patch(
        'backend.apps.model_managment_app.list_models_for_tenant',
        return_value=[],
    )
    response = client.get("/model/list", headers=auth_header)
    assert response.status_code == HTTPStatus.OK
