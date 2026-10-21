# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorization syntax shared by every inbound authentication policy."""

from typing import Optional

from contracts.exceptions import TokenExpiredError


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
