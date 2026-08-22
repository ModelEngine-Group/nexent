import { ASSET_OWNER_TENANT_ID, USER_ROLES } from "@/const/auth";

type UserTenantScope = {
  tenantId?: string;
  role?: string;
};

/**
 * Resolve tenant id for /agent/list calls.
 * Asset owners must rely on auth-header tenant resolution (never pass a stale/wrong query tenant).
 */
export function resolveAgentListTenantParam(
  user?: UserTenantScope | null
): string | undefined {
  if (!user) {
    return undefined;
  }
  if (user.role === USER_ROLES.ASSET_OWNER) {
    return undefined;
  }
  const trimmed = user.tenantId?.trim();
  if (!trimmed || trimmed === ASSET_OWNER_TENANT_ID) {
    return undefined;
  }
  return trimmed;
}

/**
 * React Query key segment for agent list hooks on authenticated pages.
 */
export function resolveAgentListQueryTenantId(
  user?: UserTenantScope | null
): string {
  return resolveAgentListTenantParam(user) ?? "";
}
