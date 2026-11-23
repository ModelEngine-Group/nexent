"""Domain constants for in-app notifications."""

# Resource types (drive frontend deep-link target)
RESOURCE_TYPE_AGENT_REPOSITORY = "agent_repository"
RESOURCE_TYPE_SKILL_REPOSITORY = "skill_repository"
RESOURCE_TYPE_MCP_REPOSITORY = "mcp_repository"

VALID_RESOURCE_TYPES = frozenset({
    RESOURCE_TYPE_AGENT_REPOSITORY,
    RESOURCE_TYPE_SKILL_REPOSITORY,
    RESOURCE_TYPE_MCP_REPOSITORY,
})

# Event types (drive title copy / icon)
EVENT_TYPE_REPOSITORY_REVIEW_APPROVED = "repository_review_approved"
EVENT_TYPE_REPOSITORY_REVIEW_REJECTED = "repository_review_rejected"
EVENT_TYPE_REPOSITORY_REVIEW_PENDING = "repository_review_pending"

VALID_EVENT_TYPES = frozenset({
    EVENT_TYPE_REPOSITORY_REVIEW_APPROVED,
    EVENT_TYPE_REPOSITORY_REVIEW_REJECTED,
    EVENT_TYPE_REPOSITORY_REVIEW_PENDING,
})

# Audience scope for a notification
SCOPE_SU = "SU"                       # all super admins (global, tenant-agnostic)
SCOPE_TENANT = "TENANT"               # all users in a given tenant
SCOPE_TENANT_ADMIN = "TENANT_ADMIN"   # admins of a given tenant
SCOPE_TENANT_USER = "TENANT_USER"     # regular users of a given tenant
SCOPE_USER = "USER"                   # a specific single user

VALID_NOTIFICATION_SCOPES = frozenset({
    SCOPE_SU, SCOPE_TENANT, SCOPE_TENANT_ADMIN, SCOPE_TENANT_USER, SCOPE_USER,
})

# Scopes that require a target tenant_id
TENANT_REQUIRED_SCOPES = frozenset({
    SCOPE_TENANT, SCOPE_TENANT_ADMIN, SCOPE_TENANT_USER,
})

# Role sets used to resolve receivers (user_tenant_t.user_role values)
SU_ROLES = frozenset({"SU", "SUPER_ADMIN"})
TENANT_ADMIN_ROLES = frozenset({"ADMIN"})
TENANT_USER_ROLES = frozenset({"USER"})
