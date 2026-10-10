"""D2 Northbound, notification, configuration, and service-boundary contracts."""

from __future__ import annotations
from shared.factories.conversation import _create_conversation

import asyncio
import time
import uuid

import pytest

from shared.auth import sign_in
from shared.config import load_yaml
from shared.asset_registry import AssetDependencyError
from shared.http import MODEL_TIMEOUT, assert_status, client, config_save_payload
from shared.factories.tenant import with_isolated_accounts


STAGE = pytest.mark.stage("D2")


async def _delete_conversation(identity, conversation_id: int) -> None:
    async with client("runtime", token=identity.access_token) as api:
        response = await api.delete(f"/conversation/{conversation_id}")
    assert_status(response, 200)


async def _create_api_user(admin_key: str, admin_identity) -> dict:
    temporary_group_id = None
    async with client("config", token=admin_identity.access_token) as config_api:
        default = await config_api.get(f"/groups/tenants/{admin_identity.tenant_id}/default")
        assert_status(default, 200)
        group_id = (default.json().get("data") or {}).get("default_group_id")
        if not group_id:
            groups = await config_api.post("/groups/list", json={"tenant_id": admin_identity.tenant_id})
            assert_status(groups, 200)
            records = groups.json().get("data") or []
            group_id = records[0].get("group_id") if records else None
        if not group_id:
            created = await config_api.post("/groups", json={
                "tenant_id": admin_identity.tenant_id,
                "group_name": f"auto-api-users-{uuid.uuid4().hex[:8]}",
                "group_description": "temporary group for D2 API users",
            })
            assert_status(created, 201)
            group_id = (created.json().get("data") or {})["group_id"]
            temporary_group_id = int(group_id)
    async with client("northbound", token=admin_key) as api:
        response = await api.post(
            "/nb/v1/api-users/batch",
            json={"role": "USER", "group_id": int(group_id), "count": 1},
        )
    assert_status(response, 201)
    data = response.json()["data"]
    users = data.get("users") if isinstance(data, dict) else data
    assert len(users) == 1
    users[0]["_temporary_group_id"] = temporary_group_id
    return users[0]


async def _delete_api_user(admin_identity, user_id: str) -> None:
    async with client("config", token=admin_identity.access_token) as api:
        response = await api.delete(f"/users/{user_id}")
    assert_status(response, 200)


async def _cleanup_api_user(admin_identity, user: dict) -> None:
    await _delete_api_user(admin_identity, str(user["user_id"]))
    group_id = user.get("_temporary_group_id")
    if group_id:
        async with client("config", token=admin_identity.access_token) as api:
            deleted = await api.delete(f"/groups/{group_id}")
        assert_status(deleted, (200, 404))


async def _put_after_rate_limit_window(api, path: str, **kwargs):
    response = await api.put(path, **kwargs)
    if response.status_code == 429:
        # The implementation uses a fixed wall-clock minute bucket and does
        # not emit Retry-After. Retry once in the next bucket so this case tests
        # idempotency rather than inheriting traffic from earlier D2 cases.
        await asyncio.sleep(max(1.0, 61.0 - (time.time() % 60.0)))
        response = await api.put(path, **kwargs)
    return response


























async def _asset_owner_with_key():
    if load_yaml("environment.yaml").get("features", {}).get("asset_owner") is not True:
        pytest.skip("SKIPPED_BY_POLICY: asset-owner feature is disabled in config/environment.yaml")
    try:
        identity = await sign_in("asset_owner")
    except (KeyError, RuntimeError) as exc:
        raise AssetDependencyError(
            "identities", "asset_owner",
            detail="Enabled asset-owner feature requires a configured OAuth-provisioned identity",
        ) from exc
    if identity.tenant_id != "asset_owner_tenant_id":
        raise AssetDependencyError(
            "identities", "asset_owner",
            detail="Configured identity is not in the asset-owner tenant",
        )
    async with client("config", token=identity.access_token) as api:
        created = await api.post("/user/tokens")
    assert_status(created, 200)
    data = created.json().get("data") or created.json()
    return identity, data["token_id"], data.get("access_key") or data["token"]












@STAGE
@pytest.mark.case_id("API-162")
@pytest.mark.asyncio
async def test_runtime_and_config_service_openapi_expose_only_owned_router_sets() -> None:
    async with client("config") as config_api, client("runtime") as runtime_api:
        config_schema = await config_api.get("/openapi.json")
        runtime_schema = await runtime_api.get("/openapi.json")
    assert_status(config_schema, 200)
    assert_status(runtime_schema, 200)
    config_paths = config_schema.json()["paths"]
    runtime_paths = runtime_schema.json()["paths"]
    assert "/model/list" in config_paths and "/conversation/create" not in config_paths
    assert "/conversation/create" in runtime_paths and "/model/list" not in runtime_paths


