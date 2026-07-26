/**
 * Authentication utilities
 *
 * After HttpOnly cookie migration, Authorization headers are injected by
 * server.js proxy layer. Frontend no longer reads or sends JWT tokens directly.
 * Cookies are sent automatically with same-origin requests.
 */

import { ApiError, fetchWithErrorHandling } from "@/services/api";
import { generateAvatarUrl as generateAvatar } from "@/lib/avatar";
import { USER_ROLES } from "@/const/auth";
import { STATUS_CODES } from "@/const/auth";
import {
  checkSessionValid,
  hasAuthCookies,
  handleSessionExpired,
} from "@/lib/session";
import { authFlowState } from "@/lib/authFlow";

/**
 * Role color mapping - Ant Design color presets
 */
const ROLE_COLORS: Record<string, string> = {
  [USER_ROLES.SU]: "red",
  [USER_ROLES.ADMIN]: "purple",
  [USER_ROLES.DEV]: "cyan",
  [USER_ROLES.USER]: "geekblue",
  [USER_ROLES.SPEED]: "green",
  [USER_ROLES.ASSET_OWNER]: "gold",
};

/**
 * Get color corresponding to user role
 * @param role - User role string
 * @returns Ant Design color preset name
 */
export function getRoleColor(role: string): string {
  return ROLE_COLORS[role] || ROLE_COLORS[USER_ROLES.USER];
}

// Generate avatar based on email (re-export from avatar.tsx for backward compatibility)
export function generateAvatarUrl(email: string): string {
  return generateAvatar(email);
}

/**
 * Request with content-type header and session expiry pre-check.
 * Authorization is handled automatically via HttpOnly cookies + server.js proxy.
 */
export const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
  // Frontend pre-check: detect session expiry without hitting backend
  if (typeof window !== "undefined") {
    if (
      !authFlowState.isExplicitLogoutInProgress() &&
      hasAuthCookies() &&
      !checkSessionValid()
    ) {
      handleSessionExpired();
      throw new ApiError(
        STATUS_CODES.TOKEN_EXPIRED,
        "Login expired, please login again"
      );
    }
  }

  const isFormData = options.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...options.headers,
  };

  return fetchWithErrorHandling(url, {
    ...options,
    headers,
  });
};

/**
 * Get common headers for API requests.
 * Authorization is handled automatically via HttpOnly cookies + server.js proxy.
 */
export const getAuthHeaders = () => {
  return {
    "Content-Type": "application/json",
    "User-Agent": "AgentFrontEnd/1.0",
  };
};

/**
 * Remove locale prefix from pathname to get effective route
 */
export function getEffectiveRoutePath(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length > 0 && (segments[0] === "zh" || segments[0] === "en")) {
    segments.shift();
  }
  return "/" + (segments.join("/") || "");
}

/**
 * Roles whose users can manage the tenant's model catalog (add/edit/delete
 * model records, fix bare-capacity rows). Used by W11 V1.5 bare-capacity
 * surfaces (per-row badge in Manage Models, agent-edit selector warning,
 * dashboard widget) to gate the "open repair" affordance per spec L167-178.
 *
 * USER is intentionally excluded: regular agent authors see a non-actionable
 * notice telling them to ask an administrator, not a link they cannot follow.
 * ASSET_OWNER manages assets (knowledge/agents) but not model records.
 */
const MODEL_MANAGEMENT_ROLES: ReadonlySet<string> = new Set([
  USER_ROLES.SU,
  USER_ROLES.ADMIN,
  USER_ROLES.DEV,
  USER_ROLES.SPEED,
]);

/**
 * Return true when the given role can act on the W11 repair affordances.
 * Speed-mode deployments bypass role gating (single-user dev experience).
 */
export function canManageModels(
  role: string | undefined | null,
  isSpeedMode = false
): boolean {
  if (isSpeedMode) return true;
  if (!role) return false;
  return MODEL_MANAGEMENT_ROLES.has(role);
}
