# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# User authentication related request models
class UserSignUpRequest(BaseModel):
    """User registration request model"""

    email: EmailStr
    password: str = Field(..., min_length=8)
    invite_code: str = Field(..., min_length=1)
    auto_login: Optional[bool] = True  # Whether to return session after signup

    @field_validator("invite_code")
    @classmethod
    def validate_invite_code(cls, value: str) -> str:
        """Reject empty or whitespace-only invitation codes."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Invitation code is required")
        return normalized


class UserSignInRequest(BaseModel):
    """User login request model"""

    email: EmailStr
    password: str


class OAuthCompleteRequest(BaseModel):
    """Complete a pending OAuth signup."""

    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=6)
    invite_code: str = Field(..., min_length=1)


class UpdatePasswordRequest(BaseModel):
    """Password update request model for changing user password"""

    old_password: str = Field(
        ..., min_length=1, description="Current password for verification"
    )
    new_password: str = Field(
        ..., min_length=8, description="New password to set (min 8 characters)"
    )


class UserUpdateRequest(BaseModel):
    """User update request model"""

    username: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    role: Optional[str] = Field(None, pattern="^(ADMIN|DEV|USER)$")


class UserDeleteRequest(BaseModel):
    """User delete request model"""

    new_owner_id: Optional[str] = None


class ApiUserBatchCreateRequest(BaseModel):
    """Request model for creating API-only users in one transaction."""

    role: Literal["DEV", "USER"] = "USER"
    group_id: Optional[int] = Field(None, ge=1)
    count: int = Field(1, ge=1, le=100)


class ApiKeyTargetRequest(BaseModel):
    """Identify a tenant user by exactly one supported field."""

    user_id: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None

    @model_validator(mode="after")
    def validate_single_target(self):
        if bool(self.user_id) == bool(self.email):
            raise ValueError("Exactly one of user_id or email must be provided")
        return self


class OAuthProviderDefinition(BaseModel):
    name: str
    display_name: str
    icon: str

    authorize_url: str
    authorize_method: str = "GET"
    authorize_params: Dict[str, str] = {}
    authorize_fragment: str = ""
    authorize_param_map: Dict[str, str] = {
        "client_id": "client_id",
        "redirect_uri": "redirect_uri",
        "scope": "scope",
        "state": "state",
    }
    encode_redirect_uri: bool = False

    token_url: str
    token_method: str = "POST"
    token_params_map: Dict[str, str] = {
        "client_id": "client_id",
        "client_secret": "client_secret",
        "code": "code",
        "grant_type": "grant_type",
    }
    token_extra_params: Dict[str, str] = {}
    token_error_key: Optional[str] = None
    token_error_message_key: Optional[str] = None
    token_response_id_key: Optional[str] = None

    userinfo_url: str
    userinfo_auth_scheme: str = "Bearer"
    userinfo_params: Dict[str, str] = {}
    userinfo_field_map: Dict[str, str] = {
        "id": "id",
        "email": "email",
        "username": "login",
    }
    userinfo_needs_email_fetch: bool = False
    userinfo_email_url: Optional[str] = None

    client_id_env: str
    client_secret_env: str
    enabled_check: Optional[str] = None


# Tenant Management Data Models
# ---------------------------------------------------------------------------
class TenantCreateRequest(BaseModel):
    """Request model for creating a tenant"""

    tenant_name: str = Field(..., min_length=1, description="Tenant display name")
    skill_ids: Optional[List[int]] = Field(
        default=None,
        description="Skill IDs to install for the new tenant (legacy, use skill_names instead)",
    )
    skill_names: Optional[List[str]] = Field(
        default=None,
        description="Skill names to install for the new tenant. "
        "Each name is used to derive a .zip filename from "
        "OFFICIAL_SKILLS_ZIP_PATH and installed via upload.",
    )
    locale: Optional[str] = Field(
        default=None,
        description="Frontend locale when creating the tenant (e.g. 'zh' or 'en').",
    )


class TenantUpdateRequest(BaseModel):
    """Request model for updating tenant information"""

    tenant_name: str = Field(..., min_length=1, description="New tenant display name")


# Pagination request model
class PaginationRequest(BaseModel):
    """Request model for pagination parameters"""

    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


# Group Management Data Models
# ---------------------------------------------------------------------------
class GroupCreateRequest(BaseModel):
    """Request model for creating a group"""

    tenant_id: str = Field(
        ..., min_length=1, description="Tenant ID where the group belongs"
    )
    group_name: str = Field(..., min_length=1, description="Group display name")
    group_description: Optional[str] = Field(
        None, description="Optional group description"
    )


class GroupUpdateRequest(BaseModel):
    """Request model for updating group information"""

    group_name: Optional[str] = Field(None, description="New group name")
    group_description: Optional[str] = Field(None, description="New group description")


class GroupListRequest(BaseModel):
    """Request model for listing groups"""

    tenant_id: str = Field(..., description="Tenant ID to filter groups")
    page: Optional[int] = Field(
        None,
        ge=1,
        description="Page number for pagination. If not provided, returns all data",
    )
    page_size: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Number of items per page. If not provided, returns all data",
    )
    sort_by: Optional[str] = Field("created_at", description="Field to sort by")
    sort_order: Optional[str] = Field("desc", description="Sort order (asc or desc)")
    search: Optional[str] = Field(None, max_length=200, description="Search group name")


class UserListRequest(BaseModel):
    """Request model for listing users"""

    tenant_id: str = Field(..., description="Tenant ID to filter users")
    page: Optional[int] = Field(
        None,
        ge=1,
        description="Page number for pagination. If not provided, returns all data",
    )
    page_size: Optional[int] = Field(
        None,
        ge=1,
        le=100,
        description="Number of items per page. If not provided, returns all data",
    )
    sort_by: Optional[str] = Field("created_at", description="Field to sort by")
    sort_order: Optional[str] = Field("desc", description="Sort order (asc or desc)")
    search: Optional[str] = Field(None, max_length=200, description="Search user email")
    roles: Optional[List[str]] = Field(None, description="Filter by user roles")
    group_ids: Optional[List[int]] = Field(None, description="Filter by user group IDs")


class GroupUserRequest(BaseModel):
    """Request model for adding/removing user from group"""

    user_id: str = Field(..., min_length=1, description="User ID to add/remove")
    group_ids: Optional[List[int]] = Field(
        None, description="List of group IDs (for batch operations)"
    )


class GroupMembersUpdateRequest(BaseModel):
    """Request model for batch updating group members"""

    user_ids: List[str] = Field(
        ..., description="List of user IDs to set as group members"
    )


class SetDefaultGroupRequest(BaseModel):
    """Request model for setting tenant's default group"""

    default_group_id: int = Field(
        ..., ge=1, description="Group ID to set as default for the tenant"
    )


# Invitation Management Data Models
# ---------------------------------------------------------------------------
class InvitationCreateRequest(BaseModel):
    """Request model for creating invitation code"""

    tenant_id: str = Field(
        ..., min_length=1, description="Tenant ID where the invitation belongs"
    )
    code_type: str = Field(
        ..., description="Invitation code type (ADMIN_INVITE, DEV_INVITE, USER_INVITE)"
    )
    invitation_code: Optional[str] = Field(
        None, description="Custom invitation code (auto-generated if not provided)"
    )
    group_ids: Optional[List[int]] = Field(None, description="Associated group IDs")
    capacity: int = Field(default=1, ge=1, description="Maximum usage capacity")
    expiry_date: Optional[str] = Field(None, description="Expiry date in ISO format")


class InvitationUpdateRequest(BaseModel):
    """Request model for updating invitation code"""

    capacity: Optional[int] = Field(None, ge=1, description="New capacity")
    expiry_date: Optional[str] = Field(None, description="New expiry date")
    group_ids: Optional[List[int]] = Field(None, description="New group IDs")


class InvitationResponse(BaseModel):
    """Response model for invitation information"""

    invitation_id: int = Field(..., description="Invitation ID")
    invitation_code: str = Field(..., description="Invitation code")
    code_type: str = Field(..., description="Code type")
    group_ids: Optional[List[int]] = Field(None, description="Associated group IDs")
    capacity: int = Field(..., description="Usage capacity")
    expiry_date: Optional[str] = Field(None, description="Expiry date")
    status: str = Field(..., description="Current status")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class InvitationListRequest(BaseModel):
    """Request model for listing invitation codes"""

    tenant_id: Optional[str] = Field(
        None, description="Tenant ID to filter by (optional)"
    )
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(20, ge=1, le=100, description="Number of items per page")
    sort_by: Optional[str] = Field(
        None, description="Sort field (create_time, update_time, etc.)"
    )
    sort_order: Optional[str] = Field(None, description="Sort order (asc, desc)")


class InvitationUseResponse(BaseModel):
    """Response model for invitation usage"""

    invitation_record_id: int = Field(..., description="Usage record ID")
    invitation_code: str = Field(..., description="Used invitation code")
    user_id: str = Field(..., description="User who used the code")
    invitation_id: int = Field(..., description="Invitation ID")
    code_type: str = Field(..., description="Code type")
    group_ids: Optional[List[int]] = Field(None, description="Associated group IDs")
