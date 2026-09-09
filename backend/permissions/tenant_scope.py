"""Tenant-scope authorization helpers."""

from http import HTTPStatus

from fastapi import HTTPException
from permissions.models import CurrentUser

# Temporary policy for personal KB capacity APIs. Keep this policy in the
# permission layer until cross-tenant access is represented by RBAC.
_PERSONAL_KB_CROSS_TENANT_ROLES = frozenset({"SU", "SPEED"})


def resolve_personal_target_tenant(
    current_user: CurrentUser, tenant_id: str | None
) -> str:
    """Resolve the tenant used by personal KB capacity APIs."""
    target_tenant_id = tenant_id or current_user.tenant_id
    if (
        target_tenant_id != current_user.tenant_id
        and current_user.normalized_role not in _PERSONAL_KB_CROSS_TENANT_ROLES
    ):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Cannot access personal KB capacity for another tenant",
        )
    return target_tenant_id
