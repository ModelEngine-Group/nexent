# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Write group changes through Casdoor and reconcile the local directory."""

import asyncio
import hashlib
import logging
import ssl
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from consts import const as settings
from contracts.constants import environment
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import ValidationError
from infrastructure.rdb.client import get_db_session
from management.db.identity.casdoor_groups import has_tenant_members, mirror_groups, tenant_bindings
from management.db.identity.group import ensure_group_capacity, lock_tenant_groups
from management.db.identity.models import TenantGroupInfo, TenantGroupUser
from management.services.permission.identity.casdoor import subject_key
from nexent.core.concurrency import ManagedTaskSpec

logger = logging.getLogger(__name__)
_DESCRIPTION = "nexentDescription"
_SYNC_INTERVAL = 15
_REQUEST_TIMEOUT = 5


class CasdoorGroupUnavailable(Exception):
    """Casdoor could not confirm the group operation or directory read."""


def synchronizes_tenant(tenant_id: str) -> bool:
    configured = environment.CASDOOR_GROUP_SYNC_TENANT_ID
    return bool(configured and configured == tenant_id)


def _organization() -> str:
    organization = settings.CASDOOR_ROLE_SYNC_ORGANIZATION
    if not settings.is_casdoor_enabled() or not organization or "/" in organization:
        raise CasdoorGroupUnavailable("Casdoor group synchronization requires a configured application and organization")
    return organization


def _scope(organization: str) -> str:
    return hashlib.sha256(f"{settings.CASDOOR_ENDPOINT}|{organization}".encode()).hexdigest()


@contextmanager
def _directory(tenant_id: str):
    organization = _organization()
    verify = (ssl.create_default_context(cafile=environment.OAUTH_CA_BUNDLE or None)
              if environment.OAUTH_SSL_VERIFY else False)
    with httpx.Client(
        base_url=settings.CASDOOR_BACKEND_ENDPOINT or settings.CASDOOR_ENDPOINT,
        auth=(settings.CASDOOR_CLIENT_ID, settings.CASDOOR_CLIENT_SECRET),
        verify=verify, timeout=_REQUEST_TIMEOUT, trust_env=False,
    ) as client, get_db_session() as session:
        lock_tenant_groups(session, tenant_id)
        yield client, session, organization


def _request(client: httpx.Client, path: str, *, params=None, payload=None):
    try:
        if payload is None:
            response = client.get(f"api/{path}", params=params)
        else:
            response = client.post(f"api/{path}", params=params, json=payload)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CasdoorGroupUnavailable("Casdoor did not respond to the group operation") from exc
    if not isinstance(result, dict) or result.get("status") != "ok" or "data" not in result:
        raise CasdoorGroupUnavailable("Casdoor rejected the group operation")
    return result["data"]


def _directory_list(client: httpx.Client, path: str, organization: str) -> list[dict]:
    data = _request(client, path, params={"owner": organization})
    if not isinstance(data, list) or any(not isinstance(row, dict) or row.get("owner") != organization for row in data):
        raise CasdoorGroupUnavailable("Casdoor returned an invalid group directory")
    return data


def _parse_groups(rows: list[dict], organization: str) -> dict[str, dict]:
    records = {}
    for row in rows:
        name = row.get("name")
        created_at = row.get("createdTime")
        display = row.get("displayName") or name
        parent = row.get("parentId")
        properties = row.get("properties")
        description = properties.get(_DESCRIPTION) if isinstance(properties, dict) else None
        if (not isinstance(name, str) or not name or "/" in name or name in records or len(name) > 100
                or not isinstance(created_at, str) or not created_at or len(created_at) > 99
                or not isinstance(display, str) or len(display) > 100
                or parent is not None and not isinstance(parent, str)
                or description is not None and (not isinstance(description, str) or len(description) > 500)):
            raise CasdoorGroupUnavailable("Casdoor returned invalid group metadata")
        records[name] = {
            "key": f"{name}/{created_at}", "name": display,
            "parent": None if parent in ("", organization, None) else parent,
            "description": description, "enabled": row.get("isEnabled") is True,
        }
    for name in records:
        seen = set()
        current = name
        while current is not None:
            if current in seen or current not in records:
                raise ValidationError("Casdoor group parents must form a hierarchy within the organization")
            seen.add(current)
            current = records[current]["parent"]
    return records


def _user_groups(row: dict) -> set[str]:
    if "groups" not in row:
        raise CasdoorGroupUnavailable("Casdoor did not return direct user groups")
    groups = row["groups"]
    if groups is None:
        return set()
    if not isinstance(groups, list) or any(not isinstance(group, str) or not group for group in groups):
        raise CasdoorGroupUnavailable("Casdoor returned invalid direct user groups")
    return set(groups)


def _bound_users(session, tenant_id: str, rows: list[dict]) -> dict[str, dict]:
    by_subject = {}
    for row in rows:
        subject, name = row.get("id"), row.get("name")
        if not isinstance(subject, str) or not subject or not isinstance(name, str) or not name or "/" in name:
            raise CasdoorGroupUnavailable("Casdoor returned an invalid user identity")
        key = subject_key(subject)
        if key in by_subject:
            raise CasdoorGroupUnavailable("Casdoor returned a duplicate user identity")
        by_subject[key] = row
    matches = defaultdict(list)
    for user_id, key in tenant_bindings(session, tenant_id):
        if key in by_subject:
            matches[user_id].append(by_subject[key])
    return {user_id: users[0] for user_id, users in matches.items() if len(users) == 1}


def _project(client, session, organization: str, tenant_id: str, *, records=None) -> dict[str, int]:
    if records is None:
        records = _parse_groups(_directory_list(client, "get-groups", organization), organization)
    users = _bound_users(session, tenant_id, _directory_list(client, "get-users", organization))
    members = defaultdict(set)
    prefix = f"{organization}/"
    for user_id, row in users.items():
        for key in _user_groups(row):
            name = key.removeprefix(prefix)
            if key.startswith(prefix) and records.get(name, {}).get("enabled"):
                members[name].add(user_id)
    return mirror_groups(session, tenant_id, _scope(organization), records, members)


def _remote_name(session, tenant_id: str, organization: str, group_id: int) -> tuple[str, str]:
    row = session.query(TenantGroupInfo).filter_by(
        tenant_id=tenant_id, group_id=group_id, delete_flag="N", casdoor_scope=_scope(organization),
    ).one_or_none()
    if not row or not row.casdoor_group_key:
        raise ValidationError("Select a synchronized group in the same tenant")
    return row.casdoor_group_key.split("/", 1)[0], row.casdoor_group_key


def _validate_fields(name: str, description: str | None) -> None:
    if not name.strip() or len(name) > 100 or (description is not None and len(description) > 500):
        raise ValidationError("Invalid synchronized group name or description")


def create_synced_group(tenant_id: str, name: str, description: str | None, parent_id: int | None) -> int:
    _validate_fields(name, description)
    with _directory(tenant_id) as (client, session, organization):
        existing = _parse_groups(_directory_list(client, "get-groups", organization), organization)
        if any(group["name"] == name for group in existing.values()):
            raise ValidationError(f"Group name '{name}' already exists in this tenant")
        parent = organization
        if parent_id is not None:
            parent, key = _remote_name(session, tenant_id, organization, parent_id)
            if existing.get(parent, {}).get("key") != key:
                raise ValidationError("The selected Casdoor parent has changed")
        _project(client, session, organization, tenant_id, records=existing)
        ensure_group_capacity(session, tenant_id)
        internal_name = f"nexent-{uuid4().hex}"
        _request(client, "add-group", payload={
            "owner": organization, "name": internal_name, "displayName": name, "parentId": parent,
            "createdTime": datetime.now(timezone.utc).isoformat(),
            "type": "Virtual", "isEnabled": True, "isTopGroup": parent_id is None,
            "properties": {_DESCRIPTION: description} if description is not None else {},
        })
        group_ids = _project(client, session, organization, tenant_id)
        if internal_name not in group_ids:
            raise CasdoorGroupUnavailable("Casdoor did not confirm the new group")
        return group_ids[internal_name]


def update_synced_group(tenant_id: str, group_id: int, updates: dict) -> bool:
    with _directory(tenant_id) as (client, session, organization):
        name, key = _remote_name(session, tenant_id, organization, group_id)
        rows = _directory_list(client, "get-groups", organization)
        records = _parse_groups(rows, organization)
        if records.get(name, {}).get("key") != key:
            raise ValidationError("The Casdoor group has changed. Refresh the Nexent group list.")
        original = next(row for row in rows if row["name"] == name)
        changed = dict(original)
        if "group_name" in updates:
            changed["displayName"] = updates["group_name"]
        if "group_description" in updates:
            changed["properties"] = {**(original.get("properties") or {}), _DESCRIPTION: updates["group_description"]}
        if "parent_group_id" in updates:
            parent_id = updates["parent_group_id"]
            parent = organization
            if parent_id is not None:
                parent, parent_key = _remote_name(session, tenant_id, organization, parent_id)
                if records.get(parent, {}).get("key") != parent_key:
                    raise ValidationError("The selected Casdoor parent has changed")
            changed.update(parentId=parent, isTopGroup=parent_id is None)
        if "group_name" in updates:
            _validate_fields(updates["group_name"], None)
        expected = _parse_groups([changed if row["name"] == name else row for row in rows], organization)[name]
        if changed != original:
            _request(client, "update-group", params={"id": f"{organization}/{name}"}, payload=changed)
        confirmed = _parse_groups(_directory_list(client, "get-groups", organization), organization)
        if confirmed.get(name) != expected:
            raise CasdoorGroupUnavailable("Casdoor did not confirm the group update")
        return _project(client, session, organization, tenant_id, records=confirmed).get(name) == group_id


def _set_remote_membership(client, organization: str, group: str, row: dict, add: bool) -> None:
    user_key = f"{organization}/{row['name']}"
    current = _request(client, "get-user", params={"id": user_key})
    if (not isinstance(current, dict) or current.get("owner") != organization
            or current.get("id") != row["id"] or current.get("name") != row["name"]):
        raise ValidationError("The Casdoor account binding has changed")
    direct = _user_groups(current)
    if (group in direct) == add:
        return
    updated = direct | {group} if add else direct - {group}
    payload = {key: value for key, value in current.items() if key not in {"password", "passwordSalt"}}
    payload["groups"] = sorted(updated)
    _request(client, "update-user", params={"id": user_key, "columns": "groups"}, payload=payload)
    confirmed = _request(client, "get-user", params={"id": user_key})
    if (not isinstance(confirmed, dict) or confirmed.get("id") != row["id"]
            or confirmed.get("owner") != organization or confirmed.get("name") != row["name"]
            or (group in _user_groups(confirmed)) != add):
        raise CasdoorGroupUnavailable("Casdoor did not confirm the membership change")


def change_synced_members(tenant_id: str, group_id: int, user_ids: set[str], *, mode: str) -> dict:
    """Apply a single member delta or replace the tenant's verified members."""
    with _directory(tenant_id) as (client, session, organization):
        name, key = _remote_name(session, tenant_id, organization, group_id)
        records = _parse_groups(_directory_list(client, "get-groups", organization), organization)
        if records.get(name, {}).get("key") != key or not records[name]["enabled"]:
            raise ValidationError("The Casdoor group has changed or is disabled")
        users = _bound_users(session, tenant_id, _directory_list(client, "get-users", organization))
        if user_ids - users.keys():
            raise ValidationError("Each member must have a verified Casdoor account in this tenant")
        group_key = f"{organization}/{name}"
        current = {user_id for user_id, row in users.items() if group_key in _user_groups(row)}
        if mode == "add":
            desired = current | user_ids
        elif mode == "remove":
            desired = current - user_ids
        else:
            desired = user_ids
        for user_id in sorted(current - desired):
            _set_remote_membership(client, organization, group_key, users[user_id], False)
        for user_id in sorted(desired - current):
            _set_remote_membership(client, organization, group_key, users[user_id], True)
        if _project(client, session, organization, tenant_id).get(name) != group_id:
            raise CasdoorGroupUnavailable("The membership could not be synchronized")
        memberships = {relation.user_id: relation for relation in session.query(TenantGroupUser).filter_by(
            group_id=group_id, delete_flag="N",
        ).all()}
        if set(memberships) != desired:
            raise CasdoorGroupUnavailable("Casdoor membership changed during the update. Refresh and retry.")
        result = {"group_id": group_id, "added_count": len(desired - current),
                  "removed_count": len(current - desired), "total_members": len(desired)}
        if mode == "add":
            user_id = next(iter(user_ids))
            result.update(user_id=user_id, already_member=user_id in current,
                          group_user_id=memberships[user_id].group_user_id)
        return result


def reconcile_group_directory(tenant_id: str) -> None:
    with _directory(tenant_id) as (client, session, organization):
        if has_tenant_members(session, tenant_id):
            _project(client, session, organization, tenant_id)


@asynccontextmanager
async def periodic_group_sync(manager):
    tenant_id = environment.CASDOOR_GROUP_SYNC_TENANT_ID
    if not tenant_id:
        yield
        return
    if tenant_id == ASSET_OWNER_TENANT_ID:
        raise ValueError("Casdoor groups must be mapped to a business tenant")
    _organization()

    async def poll():
        work = ManagedTaskSpec(task_name="casdoor-group-sync", owner=__name__)
        while True:
            try:
                await manager.run("background-service", work, reconcile_group_directory, tenant_id)
            except Exception as exc:
                logger.warning("Casdoor group directory refresh failed (%s)", type(exc).__name__)
            await asyncio.sleep(_SYNC_INTERVAL)

    task = asyncio.create_task(poll(), name="casdoor-group-sync")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
