"""Data access control for knowledge base resources.

The DAC is deliberately pure: all database lookups happen in the caller so the
decision matrix stays easy to unit test.
"""

from typing import List, Optional

from consts.const import (
    ASSET_OWNER_TENANT_ID,
    PERMISSION_EDIT,
    PERMISSION_PRIVATE,
    PERMISSION_READ,
)
from permissions.models import Resource, ResourceAccess


MANAGEMENT_ROLES = {"SU", "ADMIN", "SPEED", "ASSET_OWNER"}
ASSET_OWNER_READER_ROLES = {"SU", "ADMIN", "SPEED", "DEV"}
GROUP_ACCESS_ROLES = {"USER", "DEV"}


class ResourceAccessControl:
    """Central knowledge base resource access decision engine."""

    @staticmethod
    def check(
        resource: Resource,
        user_id: str,
        role: Optional[str],
        user_groups: Optional[List[object]] = None,
        user_tenant_id: Optional[str] = None,
        asset_owner_tenant_id: Optional[str] = None,
    ) -> ResourceAccess:
        """Resolve access for one resource.

        Tenant and USER ownership boundaries apply before source-specific
        behavior. DataMate resources remain read-only after those boundaries.
        Creator-first semantics then apply to regular knowledge bases.

        ``asset_owner_tenant_id`` is injectable for callers that override the
        default tenant marker (for example in tests or for deployment configs).
        """
        normalized_role = (role or "").upper()
        normalized_user_id = str(user_id or "")
        record_tenant_id = str(resource.tenant_id or "")
        normalized_user_tenant_id = str(user_tenant_id or "")
        effective_asset_owner_tenant_id = (
            asset_owner_tenant_id
            if asset_owner_tenant_id is not None
            else ASSET_OWNER_TENANT_ID
        )

        if not normalized_user_tenant_id:
            return ResourceAccess.deny()
        if record_tenant_id == str(effective_asset_owner_tenant_id):
            return _check_asset_owner_access(normalized_role)
        if record_tenant_id and record_tenant_id != normalized_user_tenant_id:
            return ResourceAccess.deny()
        if normalized_role == "USER" and str(resource.created_by or "") != normalized_user_id:
            return ResourceAccess.deny()
        if str(resource.knowledge_sources or "") == "datamate":
            return ResourceAccess.read_only()

        resource_groups = _normalize_group_ids(resource.group_ids)
        normalized_user_groups = _normalize_group_ids(user_groups)
        matched_groups = _matched_groups(normalized_user_groups, resource_groups)

        if str(resource.created_by or "") == normalized_user_id:
            return ResourceAccess.creator(matched_groups=matched_groups)
        if normalized_role in MANAGEMENT_ROLES:
            return _check_management_access(resource)
        return _check_group_access(resource, normalized_role, matched_groups, resource_groups, normalized_user_groups)


def _normalize_group_ids(group_ids: Optional[List[object]]) -> List[object]:
    """Normalize group IDs while preserving their original scalar type."""
    if group_ids is None:
        return []
    if isinstance(group_ids, str):
        stripped = group_ids.strip()
        if not stripped:
            return []
        try:
            return [int(part) for part in stripped.replace("[", "").replace("]", "").split(",") if part.strip()]
        except (TypeError, ValueError):
            return [part.strip() for part in stripped.split(",") if part.strip()]
    return [item for item in group_ids if item is not None]


def _check_asset_owner_access(role: str) -> ResourceAccess:
    """Resolve access to resources owned by the asset-owner tenant."""
    if role == "ASSET_OWNER":
        return ResourceAccess.edit()
    if role in ASSET_OWNER_READER_ROLES:
        return ResourceAccess.read_only()
    return ResourceAccess.deny()


def _check_management_access(resource: Resource) -> ResourceAccess:
    """Resolve management-role access to a non-asset-owner resource."""
    if _is_private(resource):
        return ResourceAccess.deny()
    return ResourceAccess.edit()


def _check_group_access(
    resource: Resource,
    role: str,
    matched_groups: List[str],
    resource_groups: List[object],
    user_groups: List[object],
) -> ResourceAccess:
    """Resolve access for users whose permission is group-scoped."""
    if role not in GROUP_ACCESS_ROLES or _is_private(resource):
        return ResourceAccess.deny()

    # Legacy data may leave both sides empty (NULL/empty groups). Keep the
    # old behavior where that combination counts as an intersection.
    if not matched_groups and (resource_groups or user_groups):
        return ResourceAccess.deny()

    ingroup_permission = str(resource.ingroup_permission or "").upper()
    if ingroup_permission == PERMISSION_EDIT:
        return ResourceAccess.edit()
    if ingroup_permission in ("", PERMISSION_READ):
        # Empty/None permission defaults to READ_ONLY for backward
        # compatibility with legacy knowledge base records.
        return ResourceAccess.read_only()
    return ResourceAccess.deny()


def _is_private(resource: Resource) -> bool:
    """Return whether a resource is explicitly private."""
    return str(resource.ingroup_permission or "").upper() == PERMISSION_PRIVATE


def _matched_groups(user_groups: List[object], resource_groups: List[object]) -> List[str]:
    """Return the normalized group intersection for two resources."""
    normalized_user_groups = {str(item) for item in user_groups}
    normalized_resource_groups = {str(item) for item in resource_groups}
    return sorted(normalized_user_groups & normalized_resource_groups)
