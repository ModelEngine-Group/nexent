# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Periodic reconciliation of tenant roles from a scoped Casdoor directory."""

import asyncio
import json
import logging
import ssl
import time
from contextlib import asynccontextmanager, suppress

import httpx

from consts import const as settings
from contracts.constants.environment import OAUTH_CA_BUNDLE, OAUTH_SSL_VERIFY
from contracts.errors.exceptions import TenantResourceLimitError
from management.db.identity.casdoor_roles import (
    CASDOOR_TENANT_ROLES,
    CasdoorRoleBinding,
    apply_casdoor_role,
    clear_initial_casdoor_role,
    list_casdoor_role_bindings,
    store_feature_grants,
)
from management.services.permission.identity.casdoor_feature_sync import evaluate_permissions, read_policies
from management.services.permission.identity.casdoor import subject_key
from nexent.core.concurrency import ManagedTaskSpec, ThreadManager
from permissions.casdoor_policy import make_snapshot

logger = logging.getLogger(__name__)
_INTERVAL_SECONDS = 15
_MAX_IN_FLIGHT = 8
_REQUEST_TIMEOUT_SECONDS = 5
_DEFAULT_ROLE_NAMES = {"USER": "nexent-user", "DEV": "nexent-developer", "ADMIN": "nexent-admin"}


def parse_role_map(raw: str) -> dict[str, str]:
    """Allow only explicit organization-local names and tenant role values."""
    roles = json.loads(raw)
    if not isinstance(roles, dict) or not roles or any(
        not name.strip() or name != name.strip() or "/" in name or role not in CASDOOR_TENANT_ROLES
        for name, role in roles.items()
    ):
        raise ValueError("CASDOOR_ROLE_MAP_JSON must map Casdoor role names to USER, DEV or ADMIN")
    return roles


def has_initial_role_mapping(role: str) -> bool:
    return settings.is_casdoor_role_sync_configured() and role in parse_role_map(settings.CASDOOR_ROLE_MAP_JSON).values()


async def _request(client: httpx.AsyncClient, endpoint: str, object_id: str, *, payload=None) -> dict | None:
    params = {"id": object_id}
    if payload is not None:
        params["columns"] = "users"
    try:
        async with asyncio.timeout(_REQUEST_TIMEOUT_SECONDS):
            if payload is None:
                response = await client.get(f"api/{endpoint}", params=params)
            else:
                response = await client.post(f"api/{endpoint}", params=params, json=payload)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning("Casdoor role request %s failed (%s)", endpoint, type(exc).__name__)
        return None
    if not isinstance(result, dict) or result.get("status") != "ok":
        logger.warning("Casdoor role request %s was rejected", endpoint)
        return None
    return result


async def _read_bound_user(client: httpx.AsyncClient, organization: str, binding: CasdoorRoleBinding) -> dict | None:
    if not binding.username or "/" in binding.username:
        return None
    result = await _request(client, "get-user", f"{organization}/{binding.username}")
    user = result.get("data") if result else None
    if not isinstance(user, dict) or user.get("owner") != organization or user.get("name") != binding.username:
        return None
    subject = user.get("id")
    if not isinstance(subject, str) or not subject or subject_key(subject) != binding.subject_key:
        return None
    return user


async def read_role(
    client: httpx.AsyncClient, organization: str, mapping: dict[str, str], binding: CasdoorRoleBinding,
) -> str | None:
    """Read a role only after verifying the provider's immutable subject and organization."""
    user = await _read_bound_user(client, organization, binding)
    if user is None:
        return None
    roles = user.get("roles")
    if not isinstance(roles, list) or any(not isinstance(role, dict) for role in roles):
        return None
    mapped = {
        mapping[role["name"]] for role in roles
        if role.get("owner") == organization and role.get("isEnabled") is True
        and isinstance(role.get("name"), str) and role["name"] in mapping
    }
    return next((role for role in reversed(CASDOOR_TENANT_ROLES) if role in mapped), "USER")


async def _role_with_members(client: httpx.AsyncClient, organization: str, name: str) -> dict | None:
    result = await _request(client, "get-role", f"{organization}/{name}")
    role = result.get("data") if result else None
    if (not isinstance(role, dict) or role.get("owner") != organization or role.get("name") != name
            or role.get("isEnabled") is not True):
        return None
    users = role.get("users")
    if users is None:
        return {**role, "users": []}
    if not isinstance(users, list) or not all(isinstance(user, str) for user in users):
        return None
    return role


async def provision_initial_role(
    client: httpx.AsyncClient, organization: str, mapping: dict[str, str], binding: CasdoorRoleBinding,
) -> bool:
    """Add the invited account once, retaining all other direct role members."""
    names = sorted(name for name, role in mapping.items() if role == binding.initial_role)
    if not names or await _read_bound_user(client, organization, binding) is None:
        return False
    name = _DEFAULT_ROLE_NAMES.get(binding.initial_role)
    if name not in names:
        name = names[0]
    role = await _role_with_members(client, organization, name)
    if role is None:
        logger.warning("Casdoor invitation role is unavailable for provisioning")
        return False
    member = f"{organization}/{binding.username}"
    if member in role["users"]:
        return True
    # Keep the complete role for Casdoor versions that replace it instead of honoring columns.
    role = {**role, "users": [*role["users"], member]}
    result = await _request(client, "update-role", f"{organization}/{name}", payload=role)
    confirmed = await _role_with_members(client, organization, name) if result else None
    return confirmed is not None and member in confirmed["users"]


async def reconcile_roles(
    client: httpx.AsyncClient, organization: str, mapping: dict[str, str], manager: ThreadManager,
) -> int:
    """Reconcile one snapshot in bounded batches; isolate individual quota failures."""
    work = ManagedTaskSpec(task_name="casdoor-role-sync", owner=__name__)
    bindings = await manager.run("background-service", work, list_casdoor_role_bindings)
    observed_at = time.time()
    policies = await read_policies(client, organization) if bindings else None
    changed = 0
    for start in range(0, len(bindings), _MAX_IN_FLIGHT):
        batch = []
        for binding in bindings[start:start + _MAX_IN_FLIGHT]:
            if binding.initial_role is None:
                batch.append(binding)
            elif await provision_initial_role(client, organization, mapping, binding):
                await manager.run("background-service", work, clear_initial_casdoor_role, binding)
        roles = await asyncio.gather(*(read_role(client, organization, mapping, binding) for binding in batch))
        updates = [(binding, role) for binding, role in zip(batch, roles) if role and role != binding.role]
        for binding, role in sorted(updates, key=lambda update: CASDOOR_TENANT_ROLES.index(update[1])):
            try:
                changed += await manager.run("background-service", work, apply_casdoor_role, binding, role)
            except TenantResourceLimitError:
                logger.warning("Casdoor role promotion deferred by tenant administrator limit")
        verified = [(binding, role) for binding, role in zip(batch, roles) if role]
        if policies is not None and verified:
            grants = await evaluate_permissions(client, organization, policies, [b.username for b, _ in verified])
            if grants is not None:
                for (binding, role), allowed in zip(verified, grants):
                    await manager.run("background-service", work, store_feature_grants,
                                      binding._replace(role=role), make_snapshot(role, allowed, observed_at))
    return changed


async def _poll(client: httpx.AsyncClient, organization: str, mapping: dict[str, str], manager: ThreadManager):
    while True:
        try:
            changed = await reconcile_roles(client, organization, mapping, manager)
            if changed:
                logger.info("Casdoor role sync updated %d tenant accounts", changed)
        except Exception as exc:
            logger.warning("Casdoor role sync cycle failed (%s)", type(exc).__name__)
        await asyncio.sleep(_INTERVAL_SECONDS)


@asynccontextmanager
async def periodic_role_sync(manager: ThreadManager):
    """Own the reconciliation task and its provider connection pool in Config."""
    if not settings.is_casdoor_role_sync_configured():
        yield
        return
    organization = settings.CASDOOR_ROLE_SYNC_ORGANIZATION
    if "/" in organization:
        raise ValueError("CASDOOR_ROLE_SYNC_ORGANIZATION must be a single organization name")
    if "/" in settings.CASDOOR_PERMISSION_MODEL:
        raise ValueError("CASDOOR_PERMISSION_MODEL must be a single model name")
    mapping = parse_role_map(settings.CASDOOR_ROLE_MAP_JSON)
    endpoint = settings.CASDOOR_BACKEND_ENDPOINT or settings.CASDOOR_ENDPOINT
    tls = ssl.create_default_context(cafile=OAUTH_CA_BUNDLE or None) if OAUTH_SSL_VERIFY else False
    async with httpx.AsyncClient(
        base_url=endpoint, auth=(settings.CASDOOR_CLIENT_ID, settings.CASDOOR_CLIENT_SECRET),
        verify=tls, timeout=_REQUEST_TIMEOUT_SECONDS, trust_env=False,
    ) as client:
        task = asyncio.create_task(_poll(client, organization, mapping, manager), name="casdoor-role-sync")
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
