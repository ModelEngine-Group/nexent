# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit operations authorization using the existing role permission data."""

import logging

import jwt
from configuration.database import configuration_database
from contracts.constants.environment import JWT_ISSUER, JWT_SECRET
from sqlalchemy import text

logger = logging.getLogger(__name__)

SYSTEM_CONFIG_ROUTE = "/system-config"


class OperationsUnauthorizedError(PermissionError):
    pass


class OperationsForbiddenError(PermissionError):
    pass


def _decode_user_id(authorization: str) -> str:
    if not authorization or not authorization.strip():
        raise OperationsUnauthorizedError("Authentication required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise OperationsUnauthorizedError("Bearer authentication required")
    if not JWT_SECRET:
        raise OperationsUnauthorizedError("Authentication is not configured")
    try:
        claims = jwt.decode(
            token.strip(),
            JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=JWT_ISSUER,
        )
    except jwt.InvalidTokenError as exc:
        raise OperationsUnauthorizedError(
            "Invalid or expired authentication token"
        ) from exc
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        raise OperationsUnauthorizedError("Invalid authentication token")
    return user_id


def authorize_operations(authorization: str | None) -> str:
    """Return the user ID only when its actual role has the ops route grant."""
    user_id = _decode_user_id(authorization or "")
    with configuration_database.session() as session:
        role = session.execute(
            text(
                "SELECT user_role FROM nexent.user_account_t "
                "WHERE user_id = :user_id AND delete_flag = 'N' LIMIT 1"
            ),
            {"user_id": user_id},
        ).scalar()
        if not role:
            raise OperationsForbiddenError(
                "Operations administrator authorization required"
            )
        permission = session.execute(
            text(
                "SELECT permission_subtype FROM nexent.role_permission_t "
                "WHERE user_role = :role AND permission_type = 'LEFT_NAV_MENU' "
                "AND permission_subtype = :route LIMIT 1"
            ),
            {"role": str(role).upper(), "route": SYSTEM_CONFIG_ROUTE},
        ).scalar()
    if permission != SYSTEM_CONFIG_ROUTE:
        raise OperationsForbiddenError(
            "Operations administrator authorization required"
        )
    return user_id
