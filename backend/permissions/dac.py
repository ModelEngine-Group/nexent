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

        Creator-first semantics apply after the special DataMate and
        ASSET_OWNER paths: the creator of a PRIVATE KB always keeps full
        access even when the caller is an ADMIN/SU/DEV/SPEED.

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

        if str(resource.knowledge_sources or "") == "datamate":
            return ResourceAccess.read_only()

        if not normalized_user_tenant_id:
            return ResourceAccess.deny()

        is_asset_owner_record = record_tenant_id == str(effective_asset_owner_tenant_id)
        if is_asset_owner_record:
            if normalized_role == "ASSET_OWNER":
                return ResourceAccess.edit()
            if normalized_role in ASSET_OWNER_READER_ROLES:
                return ResourceAccess.read_only()
            return ResourceAccess.deny()

        if record_tenant_id and normalized_user_tenant_id and record_tenant_id != normalized_user_tenant_id:
            return ResourceAccess.deny()

        resource_groups = _normalize_group_ids(resource.group_ids)
        normalized_user_groups = [
            item for item in (user_groups or []) if item is not None
        ]

        if str(resource.created_by or "") == normalized_user_id:
            return ResourceAccess.creator(
                matched_groups=sorted(
                    set(str(item) for item in normalized_user_groups)
                    & set(str(item) for item in resource_groups)
                )
            )

        if normalized_role in MANAGEMENT_ROLES:
            if str(resource.ingroup_permission or "").upper() == PERMISSION_PRIVATE:
                return ResourceAccess.deny()
            return ResourceAccess.edit()

        if normalized_role not in GROUP_ACCESS_ROLES:
            return ResourceAccess.deny()

        if str(resource.ingroup_permission or "").upper() == PERMISSION_PRIVATE:
            return ResourceAccess.deny()

        matched_groups = sorted(
            set(str(item) for item in normalized_user_groups)
            & set(str(item) for item in resource_groups)
        )

        # Legacy data may leave both sides empty (NULL/empty groups). Keep the
        # old behavior where that combination counts as an intersection.
        if not matched_groups:
            if resource_groups or normalized_user_groups:
                return ResourceAccess.deny()

        ingroup_permission = str(resource.ingroup_permission or "").upper()
        if ingroup_permission == PERMISSION_EDIT:
            return ResourceAccess.edit()
        if ingroup_permission in ("", PERMISSION_READ):
            # Empty/None permission defaults to READ_ONLY for backward
            # compatibility with legacy knowledge base records.
            return ResourceAccess.read_only()
        if ingroup_permission == PERMISSION_PRIVATE:
            return ResourceAccess.deny()
        return ResourceAccess.deny()


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
