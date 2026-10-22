# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


OAUTH_PENDING_EXPIRE_SECONDS = 10 * 60
OAUTH_PENDING_PURPOSE = "oauth_account_completion"

CAS_SESSION_ACTIVE = "active"


CAS_SESSION_REVOKED = "revoked"
SYSTEM_TENANT_ID = "system"
SYSTEM_USER_ID = "system"


# Default User and Tenant IDs
DEFAULT_USER_ID = "user_id"
DEFAULT_TENANT_ID = "tenant_id"

# Invitation code type for asset administrator registration
ASSET_OWNER_INVITE_CODE_TYPE = "ASSET_OWNER_INVITE"

# User role identifier for asset administrators
ASSET_OWNER_ROLE = "ASSET_OWNER"

# Tenant ID for asset administrators (virtual tenant, not a real tenant)
ASSET_OWNER_TENANT_ID = "asset_owner_tenant_id"

# MinIO prefix for ASSET_OWNER-scoped attachment uploads (attachments/asset_owner/{user_id}/...)
ASSET_OWNER_ATTACHMENTS_PREFIX = "attachments/asset_owner"

# HTTP detail key: asset owner must register via OAuth, not email/password signup.
ASSET_OWNER_SIGNUP_USE_OAUTH_DETAIL = "ASSET_OWNER_USE_OAUTH"

# Roles that can edit all resources within a tenant (permission = EDIT).
# Keep this centralized to avoid drifting role logic across modules.
CAN_EDIT_ALL_USER_ROLES = {"SU", "ADMIN", "SPEED", "ASSET_OWNER"}

# Permission constants used by list endpoints (e.g., /agent/list, /mcp/list).
PERMISSION_READ = "READ_ONLY"
PERMISSION_EDIT = "EDIT"
PERMISSION_PRIVATE = "PRIVATE"


# Mock User Management Configuration (for speed mode)
MOCK_USER = {"id": DEFAULT_USER_ID, "email": "mock@example.com", "role": "admin"}

MOCK_SESSION = {
    "access_token": "mock_access_token",
    "refresh_token": "mock_refresh_token",
    "expires_at": None,  # Will be set dynamically
    "expires_in_seconds": 315360000,  # 10 years
}


# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

# Fixed test secret used by generate_test_jwt and unit tests.
MOCK_JWT_SECRET_KEY = "nexent-mock-jwt-secret"
