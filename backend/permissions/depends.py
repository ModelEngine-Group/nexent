"""FastAPI permission dependencies."""

from typing import Callable, Optional

from consts.const import IS_SPEED_MODE
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from permissions.models import CurrentUser
from permissions.rbac import has_permission
from utils.auth_utils import get_current_user_context


_bearer_scheme = HTTPBearer(auto_error=False)


def authenticate(
    authorization: Optional[str] = Header(None),
    _credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    """Resolve the bearer token into a CurrentUser."""
    header_token = authorization
    if not header_token and _credentials:
        header_token = _credentials.credentials
    if not header_token and not IS_SPEED_MODE:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id, tenant_id, role = get_current_user_context(header_token)
    return CurrentUser(user_id=user_id, tenant_id=tenant_id, role=role)


def require(permission: str) -> Callable[[CurrentUser], CurrentUser]:
    """Return a dependency that requires the given permission string."""

    def dependency(current_user: CurrentUser = Depends(authenticate)) -> CurrentUser:
        if IS_SPEED_MODE and current_user.normalized_role == "SPEED":
            # Speed mode has no role_permission_t seeds, so allow the built-in
            # SPEED account to pass through permission checks.
            return current_user
        if not has_permission(current_user.normalized_role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {permission}",
            )
        return current_user

    return dependency
