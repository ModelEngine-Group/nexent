/**
 * Session utilities
 * Pure functions for session management - no React dependencies
 *
 * After HttpOnly cookie migration:
 * - Tokens (access_token, refresh_token) are stored in HttpOnly cookies by server.js
 * - expires_at is stored in a non-HttpOnly cookie readable by frontend JS
 * - User info is stored in localStorage (non-sensitive display data)
 */

import { COOKIE_NAMES, STORAGE_KEYS } from "@/const/auth";
import { Session } from "@/types/auth";
import { User } from "@/types/auth";
import { authEventUtils } from "@/lib/authEvents";
import log from "@/lib/logger";

// Flag to prevent duplicate session expiration handling
let isHandlingSessionExpired = false;

/**
 * Read a cookie value by name from document.cookie
 */
function getCookieValue(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split("=")[1]) : null;
}

/**
 * Clear a cookie by setting it to expire immediately
 */
function clearCookie(name: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; path=/; max-age=0`;
}

/**
 * Get token expiry timestamp from the non-HttpOnly cookie
 */
export const getTokenExpiresAt = (): number | null => {
  const value = getCookieValue(COOKIE_NAMES.EXPIRES_AT);
  if (!value) return null;
  const num = Number(value);
  return isNaN(num) ? null : num;
};

/**
 * Check if an authenticated session exists (cookie-based)
 */
export const hasAuthCookies = (): boolean => {
  return getTokenExpiresAt() !== null;
};

/**
 * Save user info to localStorage (non-sensitive display data only)
 */
export const saveUserToStorage = (user: User): void => {
  if (typeof window !== "undefined") {
    localStorage.setItem(STORAGE_KEYS.USER_INFO, JSON.stringify(user));
  }
};

/**
 * Get user info from localStorage
 */
export const getUserFromStorage = (): User | null => {
  try {
    const stored =
      typeof window !== "undefined"
        ? localStorage.getItem(STORAGE_KEYS.USER_INFO)
        : null;
    if (!stored) return null;
    return JSON.parse(stored);
  } catch (error) {
    log.error("Failed to parse user info:", error);
    return null;
  }
};

/**
 * Remove user info from localStorage
 */
export const removeUserFromStorage = (): void => {
  if (typeof window !== "undefined") {
    localStorage.removeItem(STORAGE_KEYS.USER_INFO);
    localStorage.removeItem(STORAGE_KEYS.SESSION); // clean up legacy key
  }
};

/**
 * Build a Session object from available sources.
 * Tokens are no longer accessible; only expires_at is available from cookie.
 */
export const getSessionFromStorage = (): Session | null => {
  const expiresAt = getTokenExpiresAt();
  if (expiresAt === null) return null;
  return { expires_at: expiresAt };
};

/**
 * Save session to storage — kept for backward compatibility.
 * In the new model only expires_at is meaningful, and it's set via cookie by server.js.
 * This function now saves user info if provided on the session object.
 */
export const saveSessionToStorage = (session: Session): void => {
  // No-op for tokens — they are managed by server.js HttpOnly cookies.
  // The expires_at cookie is also set by server.js.
};

/**
 * Remove session (clear the non-HttpOnly expires_at cookie and localStorage user info)
 */
export const removeSessionFromStorage = (): void => {
  clearCookie(COOKIE_NAMES.EXPIRES_AT);
  removeUserFromStorage();
};

/**
 * Check if session is valid (cookie exists and not expired)
 */
export const checkSessionValid = (): boolean => {
  const expiresAt = getTokenExpiresAt();
  if (expiresAt === null) return false;

  const now = Date.now();
  return expiresAt * 1000 > now;
};

/**
 * Check if session has expired
 */
export const checkSessionExpired = (): boolean => {
  return !checkSessionValid();
};

/**
 * Clear session and emit expired event
 * Unified handling for session expiration with duplicate prevention
 */
export const handleSessionExpired = (): void => {
  if (isHandlingSessionExpired) {
    return;
  }
  isHandlingSessionExpired = true;

  log.info("Session expired, clearing and emitting event");
  removeSessionFromStorage();

  setTimeout(() => {
    authEventUtils.emitSessionExpired();
  }, 0);

  setTimeout(() => {
    isHandlingSessionExpired = false;
  }, 300);
};
