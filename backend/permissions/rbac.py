# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Role-based access control backed by role_permission_t."""

import logging
import threading
from typing import Dict, Optional, Set

from contracts.roles import normalize_roles, roles_from_record
from management.db.identity.role_permission import get_all_role_permissions

logger = logging.getLogger(__name__)

_PERMISSION_LOCK = threading.RLock()
_ROLE_PERMISSIONS: Dict[str, Set[str]] = {}
_INITIALIZED = False


def _normalize_permission(permission_type: str, permission_subtype: str) -> str:
    """Normalize a RESOURCE permission to lower-case type:subtype form."""
    return f"{permission_type}:{permission_subtype}".lower()


def init_rbac() -> None:
    """Load role permissions into the in-memory cache."""
    global _INITIALIZED
    try:
        records = get_all_role_permissions()
        with _PERMISSION_LOCK:
            _ROLE_PERMISSIONS.clear()
            for record in records:
                role = str(record.get("user_role") or "").upper()
                if not role:
                    continue
                permission_category = str(record.get("permission_category") or "")
                permission_type = str(record.get("permission_type") or "")
                permission_subtype = str(record.get("permission_subtype") or "")
                if permission_category == "RESOURCE" and permission_type and permission_subtype:
                    _ROLE_PERMISSIONS.setdefault(role, set()).add(
                        _normalize_permission(permission_type, permission_subtype)
                    )
            _INITIALIZED = True
            logger.info(
                "RBAC cache loaded: %d roles", len(_ROLE_PERMISSIONS)
            )
    except Exception:
        logger.exception("Failed to load RBAC cache; permission checks will retry lazily")
        with _PERMISSION_LOCK:
            _INITIALIZED = False


def _ensure_loaded() -> None:
    if not _INITIALIZED:
        init_rbac()


def has_permission(role, permission: str) -> bool:
    """Return whether the normalized role has the lower-case permission string."""
    try:
        roles = normalize_roles(role, allow_empty=True)
    except ValueError:
        return False
    normalized_permission = (permission or "").lower()
    if not roles or not normalized_permission:
        return False
    _ensure_loaded()
    with _PERMISSION_LOCK:
        return any(normalized_permission in _ROLE_PERMISSIONS.get(item, set()) for item in roles)


def get_role_permissions(role) -> Set[str]:
    """Return the cached permission set for a role."""
    try:
        roles = normalize_roles(role, allow_empty=True)
    except ValueError:
        return set()
    _ensure_loaded()
    with _PERMISSION_LOCK:
        return set().union(*(_ROLE_PERMISSIONS.get(item, set()) for item in roles))
