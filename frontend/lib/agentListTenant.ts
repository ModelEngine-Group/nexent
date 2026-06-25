import { USER_ROLES } from "@/const/auth";

type AgentListUser = { tenantId?: string; role?: string } | null | undefined;

/**
 * Resolve the tenant key passed to useAgentList.
 * - null: caller is waiting (e.g. tenant picker not selected)
 * - "": fetch /agent/list without tenant_id; backend resolves from auth cookies
 * Asset owners always use auth resolution to avoid stale default tenant_id values.
 */
export function resolveAgentListTenantKey(
  user: AgentListUser,
  explicitTenantId?: string | null
): string | null {
  if (explicitTenantId === null) {
    return null;
  }
  if (user?.role === USER_ROLES.ASSET_OWNER) {
    return "";
  }
  const fromUser = user?.tenantId?.trim();
  if (fromUser) {
    return fromUser;
  }
  const fromExplicit = explicitTenantId?.trim();
  if (fromExplicit) {
    return fromExplicit;
  }
  return "";
}
