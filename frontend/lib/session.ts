/**
 * Session utilities
 * Pure functions for session management - no React dependencies
 */

import { STORAGE_KEYS } from "@/const/auth";
import { Session } from "@/types/auth";
import { authEventUtils } from "@/lib/authEvents";
import log from "@/lib/logger";

// Flag to prevent duplicate session expiration handling
let isHandlingSessionExpired = false;

/**
 * Save session to local storage
 */
export const saveSessionToStorage = (session: Session): void => {
  if (typeof window !== "undefined") {
    localStorage.setItem(STORAGE_KEYS.SESSION, JSON.stringify(session));
  }
};

/**
 * Remove session from local storage
 */
export const removeSessionFromStorage = (): void => {
  if (typeof window !== "undefined") {
    localStorage.removeItem(STORAGE_KEYS.SESSION);
  }
};

/**
 * Get session from local storage
 */
export const getSessionFromStorage = (): Session | null => {
  try {
    const storedSession =
      typeof window !== "undefined"
        ? localStorage.getItem(STORAGE_KEYS.SESSION)
        : null;
    if (!storedSession) return null;

    return JSON.parse(storedSession);
  } catch (error) {
    log.error("Failed to parse session info:", error);
    return null;
  }
};

/**
 * Check if session is valid (exists and not expired)
 */
export const checkSessionValid = (): boolean => {
  const session = getSessionFromStorage();
  if (!session?.access_token || !session?.expires_at) {
    return false;
  }

  const now = Date.now();
  return session.expires_at * 1000 > now;
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
  // Prevent duplicate triggers
  if (isHandlingSessionExpired) {
    return;
  }
  isHandlingSessionExpired = true;

  log.info("Session expired, clearing and emitting event");
  removeSessionFromStorage();

  // Emit event asynchronously to ensure isAuthenticated state has been updated
  // This fixes the closure trap where showSessionExpiredModal captures stale isAuthenticated value
  setTimeout(() => {
    authEventUtils.emitSessionExpired();
  }, 0);

  // Reset flag after 300ms to allow future triggers
  setTimeout(() => {
    isHandlingSessionExpired = false;
  }, 300);
};
