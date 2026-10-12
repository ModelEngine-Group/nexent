"""Authentication fixtures for black-box API integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import load_secret_env, load_yaml
from .http import assert_status, client


@dataclass(frozen=True)
class TestIdentity:
    id: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    configured_tenant: str
    configured_role: str
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    user_id: str
    tenant_id: str
    role: str


def configured_user(identity_id: str) -> tuple[dict[str, Any], str]:
    users = load_yaml("users.yaml").get("users") or []
    record = next((item for item in users if item.get("id") == identity_id), None)
    if not record:
        raise RuntimeError(f"config/users.yaml has no user id={identity_id!r}")
    password_key = str(record.get("password_env_key") or "")
    password = load_secret_env().get(password_key, "")
    if not password:
        raise RuntimeError(f"config/secrets.env has no value for {password_key}")
    return record, password


def _find_string(value: Any, keys: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys and isinstance(child, str) and child:
                return child
        for child in value.values():
            found = _find_string(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_string(child, keys)
            if found:
                return found
    return None


async def sign_in(identity_id: str) -> TestIdentity:
    record, password = configured_user(identity_id)
    return await sign_in_credentials(identity_id, record, password)


async def sign_in_credentials(identity_id: str, record: dict[str, Any], password: str) -> TestIdentity:
    """Authenticate an ephemeral account without persisting it in shared config."""
    async with client("config") as anonymous:
        response = await anonymous.post("/user/signin", json={"email": record["username"], "password": password})
    assert_status(response, 200)
    payload = response.json()
    access_token = _find_string(payload, {"access_token", "accesstoken", "token"})
    if not access_token:
        raise AssertionError("signin response contains no access token")
    access_token = access_token.removeprefix("Bearer ").strip()
    refresh_token = _find_string(payload, {"refresh_token", "refreshtoken"})

    async with client("config", token=access_token) as authenticated:
        info_response = await authenticated.get("/user/current_user_info")
    assert_status(info_response, 200)
    info = info_response.json().get("data") or {}
    user = info.get("user") or {}
    user_id = str(user.get("user_id") or user.get("id") or info.get("user_id") or "")
    # current_user_info returns tenant_id inside data.user.  Falling back to the
    # human-readable config label (for example "tenant_a") makes every scoped
    # API call look cross-tenant because the backend authorizes with the real ID.
    tenant = info.get("tenant") or {}
    tenant_id = str(
        user.get("tenant_id")
        or user.get("tenantId")
        or tenant.get("tenant_id")
        or tenant.get("id")
        or info.get("tenant_id")
        or ""
    )
    role = str(user.get("role") or user.get("user_role") or info.get("role") or record.get("role") or "").upper()
    if not user_id or not tenant_id:
        raise AssertionError(f"current_user_info lacks user/tenant identity: {info}")
    return TestIdentity(
        id=identity_id,
        username=str(record["username"]),
        password=password,
        configured_tenant=str(record.get("tenant") or ""),
        configured_role=str(record.get("role") or ""),
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
    )
