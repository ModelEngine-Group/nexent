# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Credential parsing and active-account checks shared by authentication policies."""

from typing import Optional

from contracts.errors.exceptions import TokenExpiredError
from management.db.identity import account as account_repository


def require_active_account(user_id: str) -> dict:
    """Reject deleted identities before any business authorization."""
    account = account_repository.get_account(user_id)
    if not account or account["delete_flag"] != "N":
        raise TokenExpiredError("Account is unavailable")
    return account


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Accept Bearer credentials and the established single-token legacy form."""
    if not authorization:
        return None
    if not isinstance(authorization, str):
        raise TokenExpiredError("Invalid authorization header")
    parts = authorization.strip().split()
    if not parts:
        return None
    if len(parts) == 1 and parts[0].lower() != "bearer":
        return parts[0]
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    raise TokenExpiredError("Invalid authorization header")
