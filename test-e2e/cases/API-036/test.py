"""D2 tenant, user, group, invitation and tenant API-key integration tests."""

from __future__ import annotations

import uuid

import pytest

from shared.http import assert_status, client
from shared.resource_ids import absent_numeric_id
from shared.factories.ownership import register_owned_http
from shared.asset_registry import mark_asset_state
from shared.factories.tenant import with_isolated_accounts


STAGE = pytest.mark.stage("D2")


def _payload(response):
    value = response.json()
    return value.get("data") if isinstance(value, dict) else None


async def _create_tenant(identity, label: str) -> dict:
    async with client("config", token=identity.access_token) as api:
        response = await api.post("/tenants", json={
            "tenant_name": f"auto-{label}-{uuid.uuid4().hex[:8]}",
            "skill_ids": [], "skill_names": [], "locale": "zh",
        })
    assert_status(response, 201)
    tenant = _payload(response)
    assert tenant and tenant.get("tenant_id")
    register_owned_http(identity,'owned_tenants',tenant['tenant_id'],f"/tenants/{tenant['tenant_id']}")
    return tenant


async def _delete_tenant(identity, tenant_id: str) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.delete(f"/tenants/{tenant_id}")
    assert_status(response, (200, 404))
    mark_asset_state('owned_tenants',str(tenant_id),'DELETED')


async def _create_group(identity, name: str | None = None) -> dict:
    async with client("config", token=identity.access_token) as api:
        response = await api.post("/groups", json={
            "tenant_id": identity.tenant_id,
            "group_name": name or f"auto-group-{uuid.uuid4().hex[:8]}",
            "group_description": "fixed D2 automation",
        })
    assert_status(response, 201)
    group = _payload(response)
    assert group and group.get("group_id")
    register_owned_http(identity,'owned_groups',group['group_id'],f"/groups/{group['group_id']}")
    return group


async def _delete_group(identity, group_id: int) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.delete(f"/groups/{group_id}")
    assert_status(response, (200, 404))
    mark_asset_state('owned_groups',str(group_id),'DELETED')






























async def _create_invitation(identity, *, capacity: int = 2) -> tuple[str, dict]:
    code = f"auto-invite-{uuid.uuid4().hex[:10]}"
    async with client("config", token=identity.access_token) as api:
        response = await api.post("/invitations", json={
            "tenant_id": identity.tenant_id, "code_type": "USER_INVITE",
            "invitation_code": code, "capacity": capacity,
        })
    assert_status(response, 201)
    created = _payload(response) or {}
    canonical_code = str(created.get('invitation_code') or code)
    register_owned_http(identity,'owned_invitations',canonical_code,f'/invitations/{canonical_code}')
    # Custom invitation codes are normalized to uppercase by the service.
    # Every subsequent operation must use the canonical returned value.
    return str(created.get("invitation_code") or code), created








@STAGE
@pytest.mark.case_id("API-036")
@pytest.mark.asyncio
async def test_invitation_unknown_expired_and_invalid_use_are_not_success(tenant_a_user) -> None:
    code = f"missing-{uuid.uuid4().hex}"
    async with client("config", token=tenant_a_user.access_token) as api:
        available = await api.get(f"/invitations/{code}/available")
        used = await api.post(f"/invitations/{code}/use")
    assert_status(available, 200)
    assert (_payload(available) or {}).get("available") is False
    assert_status(used, 404)
