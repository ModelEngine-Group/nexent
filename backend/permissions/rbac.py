"""Role-based access control backed by role_permission_t."""

import logging
import threading
from typing import Dict, Optional, Set

from database.role_permission_db import get_all_role_permissions


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


def has_permission(role: Optional[str], permission: str) -> bool:
    """Return whether the normalized role has the lower-case permission string."""
    normalized_role = (role or "").upper()
    normalized_permission = (permission or "").lower()
    if not normalized_role or not normalized_permission:
        return False
    _ensure_loaded()
    with _PERMISSION_LOCK:
        return normalized_permission in _ROLE_PERMISSIONS.get(normalized_role, set())


def get_role_permissions(role: Optional[str]) -> Set[str]:
    """Return the cached permission set for a role."""
    normalized_role = (role or "").upper()
    _ensure_loaded()
    with _PERMISSION_LOCK:
        return set(_ROLE_PERMISSIONS.get(normalized_role, set()))
