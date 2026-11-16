# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Built-in role contracts shared by identity and authorization boundaries."""

from collections.abc import Iterable, Mapping

ORDINARY_ROLES = frozenset({"ADMIN", "DEV", "USER", "OPS"})
SPECIAL_ROLES = frozenset({"SU", "ASSET_OWNER"})
ROLE_ORDER = ("SU", "ADMIN", "DEV", "USER", "OPS", "ASSET_OWNER")
INVITATION_ROLES = {
    "ADMIN_INVITE": ("ADMIN",),
    "DEV_INVITE": ("DEV",),
    "USER_INVITE": ("USER",),
    "ASSET_OWNER_INVITE": ("ASSET_OWNER",),
}


def normalize_roles(value, *, ordinary_only: bool = False, allow_empty: bool = False) -> tuple[str, ...]:
    """Validate complete role sets; never silently discard retired or unknown roles."""
    if isinstance(value, str):
        values = (value,)
    elif value is None:
        values = ()
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        values = tuple(value)
    else:
        raise ValueError("Roles must be a list of built-in role codes")
    if any(not isinstance(role, str) or not role.strip() for role in values):
        raise ValueError("Roles must not contain empty values")
    roles = {role.strip().upper() for role in values}
    allowed = ORDINARY_ROLES if ordinary_only else ORDINARY_ROLES | SPECIAL_ROLES
    if roles - allowed:
        raise ValueError("Unknown or retired role")
    if not roles and not allow_empty:
        raise ValueError("At least one role is required")
    if roles & SPECIAL_ROLES and len(roles) != 1:
        raise ValueError("Special identities cannot be combined with ordinary roles")
    return tuple(role for role in ROLE_ORDER if role in roles)


def roles_from_record(record: Mapping | None) -> tuple[str, ...]:
    """Use the array as authority, with single-role fallback only for unmigrated records."""
    if not record:
        return ()
    values = record.get("user_roles", record.get("roles"))
    if values is None:
        values = record.get("user_role") or record.get("role")
    return normalize_roles(values, allow_empty=True)


def has_any_role(value, allowed: Iterable[str]) -> bool:
    """Fail closed for malformed identities while allowing legacy single-role callers."""
    try:
        return bool(set(normalize_roles(value, allow_empty=True)) & set(allowed))
    except ValueError:
        return False


def primary_role(value, preferred: str | None = None) -> str:
    """Return a compatibility display value, never an authorization decision."""
    roles = normalize_roles(value)
    return preferred if preferred in roles else roles[0]


def invitation_roles(record: Mapping) -> tuple[str, ...]:
    """Resolve old invitation types without guessing a role for unknown new types."""
    value = record.get("roles")
    if value is None:
        value = INVITATION_ROLES.get(record.get("code_type"))
    return normalize_roles(value)
