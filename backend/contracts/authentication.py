# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from dataclasses import dataclass
from enum import Enum
from typing import Optional, TypedDict


class CredentialKind(str, Enum):
    SESSION = "session"
    API_KEY = "api_key"
    INTERNAL = "internal"


@dataclass(frozen=True)
class AuthenticatedIdentity:
    user_id: str
    tenant_id: str
    role: str = ""
    language: str = "zh"
    token_id: Optional[int] = None
    kind: CredentialKind = CredentialKind.SESSION


@dataclass
class NorthboundContext:
    request_id: str
    tenant_id: str
    user_id: str
    authorization: str
    token_id: int = 0


OAUTH_PENDING_EXPIRE_SECONDS = 10 * 60
OAUTH_PENDING_PURPOSE = "oauth_account_completion"


class PendingOAuthIdentity(TypedDict):
    provider: str
    provider_user_id: str
    provider_email: str
    provider_username: str
