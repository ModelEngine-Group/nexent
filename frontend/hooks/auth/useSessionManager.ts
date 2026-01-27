"use client";

import { useCallback, useEffect } from "react";
import { usePathname } from "next/navigation";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { sessionService } from "@/services/sessionService";
import {
  getSessionFromStorage,
  saveSessionToStorage,
  removeSessionFromStorage,
  checkSessionValid as checkSessionValidFn,
  checkSessionExpired as checkSessionExpiredFn,
  handleSessionExpired,
} from "@/lib/session";
import { authEventUtils } from "@/lib/authEvents";
import {
  TOKEN_REFRESH_BEFORE_EXPIRY_MS,
  MIN_ACTIVITY_CHECK_INTERVAL_MS,
} from "@/const/constants";
import log from "@/lib/logger";

import type { Session } from "@/types/auth";

// ============================================================================
// Utility functions - Session status checking
// ============================================================================

// Re-export from lib/session for convenience
export const checkSessionValid = checkSessionValidFn;
export const checkSessionExpired = checkSessionExpiredFn;

/**
 * Check if token is expiring soon (within threshold)
 */
export const isSessionExpiringSoon = (): boolean => {
  const session = getSessionFromStorage();
  if (!session?.expires_at) return false;

  const now = Date.now();
  const msUntilExpiry = session.expires_at * 1000 - now;

  // Token must not be already expired, and remaining time must be within threshold
  return msUntilExpiry > 0 && msUntilExpiry <= TOKEN_REFRESH_BEFORE_EXPIRY_MS;
};

// ============================================================================
// Session operations
// ============================================================================

/**
 * Save session to localStorage
 */
export const saveSession = (session: Session): void => {
  saveSessionToStorage(session);
  log.info("Session saved to localStorage");
};

/**
 * Clear session and emit expired event
 * Unified handling for session expiration
 */
export const clearSession = (): void => {
  handleSessionExpired();
};

// ============================================================================
// Business logic functions
// ============================================================================

/**
 * Refresh session if needed (token expiring soon)
 * Uses refresh_token to get new access_token
 * @returns Whether refresh was successful
 */
export const refreshSessionIfNeeded = async (): Promise<boolean> => {
  const session = getSessionFromStorage();
  if (!session?.refresh_token) {
    return false;
  }

  const newSession = await sessionService.refreshToken(session.refresh_token);
  if (newSession) {
    saveSession(newSession);
    log.info("Session refreshed successfully");
    return true;
  }

  log.warn("Session refresh failed");
  return false;
};

/**
 * Unified handler for session expiration
 * Called when session is confirmed expired
 */
export const sessionExpiredHandler = (): void => {
  log.info("Handling session expiration");
  handleSessionExpired();
};

  // ============================================================================
  // Hook implementation
  // ============================================================================

export function useSessionManager() {
  const { isSpeedMode } = useDeployment();

  // Initialize session management when hook is used
  useEffect(() => {
    // In speed mode, skip session validation
    if (isSpeedMode) return;

    if (checkSessionValid()) {
      // Session is valid, no action needed
      return;
    }

    // Session is expired or invalid
    handleSessionExpired();
  }, [isSpeedMode]);

  /**
   * Setup automatic token refresh on user activity
   * Refreshes token before expiry to implement sliding expiration
   */
  const setupTokenAutoRefresh = useCallback(() => {
    // Skip in speed mode
    if (isSpeedMode) return () => {};

    let lastActivityCheckAt = 0;

    const maybeRefreshOnActivity = async () => {
      try {
        // Throttle activity-driven checks
        const now = Date.now();
        if (now - lastActivityCheckAt < MIN_ACTIVITY_CHECK_INTERVAL_MS) return;
        lastActivityCheckAt = now;

        // Do not run when page is hidden
        if (typeof document !== "undefined" && document.hidden) return;

        // Check if token is expiring soon
        if (isSessionExpiringSoon()) {
          const success = await refreshSessionIfNeeded();

          // If refresh failed, it means refresh_token is also invalid
          // The session will be cleared when backend returns 401 or when fetchWithAuth checks
          if (!success) {
            log.debug("Token refresh failed, waiting for 401 from backend");
          }
        }
      } catch (error) {
        log.error("Activity-based refresh check failed:", error);
      }
    };

    const events: (keyof DocumentEventMap | keyof WindowEventMap)[] = [
      "click",
      "keydown",
      "mousemove",
      "touchstart",
      "focus",
      "visibilitychange",
    ];

    const handler = () => {
      void maybeRefreshOnActivity();
    };

    events.forEach((evt) => {
      if (evt === "focus" || evt === "visibilitychange") {
        window.addEventListener(evt as any, handler, { passive: true });
      } else {
        document.addEventListener(evt as any, handler, { passive: true });
      }
    });

    return () => {
      events.forEach((evt) => {
        if (evt === "focus" || evt === "visibilitychange") {
          window.removeEventListener(evt as any, handler);
        } else {
          document.removeEventListener(evt as any, handler);
        }
      });
    };
  }, [isSpeedMode]);

  // Setup auto refresh
  useEffect(() => {
    const cleanupAutoRefresh = setupTokenAutoRefresh();
    return () => {
      cleanupAutoRefresh?.();
    };
  }, [setupTokenAutoRefresh]);

  return {
    // Utility functions
    checkSessionValid,
    checkSessionExpired,
    isSessionExpiringSoon,

    // Session operations
    saveSession,
    clearSession,
    handleSessionExpired,

    // Business logic
    refreshSessionIfNeeded,
    sessionExpiredHandler,

    // Legacy functions
    setupTokenAutoRefresh,
  };
}
