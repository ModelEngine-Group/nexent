"use client";

import { useCallback, useEffect, useRef } from "react";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { sessionService } from "@/services/sessionService";
import {
  getSessionFromStorage,
  saveSessionToStorage,
  checkSessionValid,
  checkSessionExpired,
  handleSessionExpired,
} from "@/lib/session";
import {
  TOKEN_REFRESH_BEFORE_EXPIRY_MS,
  MIN_ACTIVITY_CHECK_INTERVAL_MS,
} from "@/const/constants";
import log from "@/lib/logger";

import type { Session } from "@/types/auth";

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

/**
 * Refresh session if needed (token expiring soon)
 * Uses refresh_token to get new access_token
 * @returns Whether refresh was successful
 */
export const refreshSession = async (): Promise<boolean> => {
  const session = getSessionFromStorage();
  if (!session?.refresh_token) {
    return false;
  }

  const newSession = await sessionService.refreshToken(session.refresh_token);
  if (newSession) {
    saveSessionToStorage(newSession);
    log.info("Session refreshed successfully");
    return true;
  }

  log.warn("Session refresh failed");
  return false;
};

  // ============================================================================
  // Hook implementation
  // ============================================================================

export function useSessionManager() {
  const { isSpeedMode, isDeploymentReady } = useDeployment();
  const reconcileExpiryRef = useRef<() => void>(() => {});

  // Initialize session management when hook is used
  useEffect(() => {
    // In speed mode or before deployment is ready, skip session validation
    // This prevents the modal from showing when isSpeedMode is initially false
    // and then becomes true after API returns deployment_version
    if (isSpeedMode || !isDeploymentReady) return;

    const session = getSessionFromStorage();
    if (!session) {
      return;
    }

    if (checkSessionValid()) {
      // Session is valid, no action needed
      return;
    }

    // Session is expired or invalid
    handleSessionExpired();
  }, [isSpeedMode, isDeploymentReady]);

  /**
   * Proactive session expiry watcher
   * Triggers session-expired even if user does not make any API request
   */
  useEffect(() => {
    // In speed mode or before deployment is ready, skip session watching
    if (isSpeedMode || !isDeploymentReady) return;

    let timeoutId: number | null = null;
    let intervalId: number | null = null;

    const clearTimers = () => {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
        timeoutId = null;
      }
      if (intervalId !== null) {
        window.clearInterval(intervalId);
        intervalId = null;
      }
    };

    const scheduleExpiryCheck = () => {
      clearTimers();

      const session = getSessionFromStorage();
      if (!session?.expires_at) {
        return;
      }

      const now = Date.now();
      const delayMs = session.expires_at * 1000 - now;

      if (delayMs <= 0) {
        handleSessionExpired();
        return;
      }

      // Schedule an accurate one-shot check at expiry time
      timeoutId = window.setTimeout(() => {
        if (!checkSessionValid()) {
          handleSessionExpired();
        }
      }, delayMs);

      // Also reschedule periodically to account for token refresh extending expires_at
      intervalId = window.setInterval(() => {
        const s = getSessionFromStorage();
        if (!s) {
          clearTimers();
          return;
        }
        if (!checkSessionValid()) {
          handleSessionExpired();
          return;
        }
        if (s.expires_at !== session.expires_at) {
          scheduleExpiryCheck();
        }
      }, 30_000);
    };

    const reconcileExpiry = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      if (!checkSessionValid() && getSessionFromStorage()) {
        handleSessionExpired();
        return;
      }
      scheduleExpiryCheck();
    };

    reconcileExpiryRef.current = reconcileExpiry;
    scheduleExpiryCheck();

    return () => {
      reconcileExpiryRef.current = () => {};
      clearTimers();
    };
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
        // Keep expiry timer in sync when the page becomes active again
        reconcileExpiryRef.current();

        // Throttle activity-driven checks
        const now = Date.now();
        if (now - lastActivityCheckAt < MIN_ACTIVITY_CHECK_INTERVAL_MS) return;
        lastActivityCheckAt = now;

        // Do not run when page is hidden
        if (typeof document !== "undefined" && document.hidden) return;

        // Check if token is expiring soon
        if (isSessionExpiringSoon()) {
          const success = await refreshSession();

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
    isSessionExpiringSoon,

    // Business logic
    refreshSession,

    // Legacy functions
    setupTokenAutoRefresh,
  };
}
