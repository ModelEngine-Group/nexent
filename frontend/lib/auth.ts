/**
 * Authentication utilities
 */

import { ApiError, fetchWithErrorHandling } from "@/services/api";
import { STORAGE_KEYS } from "@/const/auth";
import { generateAvatarUrl as generateAvatar } from "@/lib/avatar";
import { USER_ROLES } from "@/const/auth";
import { STATUS_CODES } from "@/const/auth";
import {
  checkSessionValid,
  getSessionFromStorage,
  handleSessionExpired,
} from "@/lib/session";

/**
 * Role color mapping - Ant Design color presets
 */
const ROLE_COLORS: Record<string, string> = {
  [USER_ROLES.SU]: "red",
  [USER_ROLES.ADMIN]: "purple",
  [USER_ROLES.DEV]: "cyan",
  [USER_ROLES.USER]: "geekblue",
  [USER_ROLES.SPEED]: "green",
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
 * Request with authorization headers
 * Only builds the request with auth token - no expiration checking
 * Expiration should be handled when backend returns 401
 */
export const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
  // Frontend pre-check: detect session expiry without hitting backend
  if (typeof window !== "undefined") {
    const session = getSessionFromStorage();
    if (session && !checkSessionValid()) {
      handleSessionExpired();
      throw new ApiError(
        STATUS_CODES.TOKEN_EXPIRED,
        "Login expired, please login again"
      );
    }
  }

  const sessionObj = getSessionFromStorage();

  const isFormData = options.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(sessionObj?.access_token && {
      Authorization: `Bearer ${sessionObj.access_token}`,
    }),
    ...options.headers,
  };

  // Use request interceptor with error handling
  return fetchWithErrorHandling(url, {
    ...options,
    headers,
  });
};

/**
 * Get the authorization header information for API requests
 * @returns HTTP headers object containing authentication and content type information
 */
export const getAuthHeaders = () => {
  const session =
    typeof window !== "undefined" ? localStorage.getItem("session") : null;
  const sessionObj = session ? JSON.parse(session) : null;

  return {
    "Content-Type": "application/json",
    "User-Agent": "AgentFrontEnd/1.0",
    ...(sessionObj?.access_token && {
      Authorization: `Bearer ${sessionObj.access_token}`,
    }),
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