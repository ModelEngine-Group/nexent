"use client";

import { useCallback, useEffect, useRef } from "react";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { sessionService } from "@/services/sessionService";
import { casService } from "@/services/casService";
import {
  getTokenExpiresAt,
  hasAuthCookies,
  checkSessionValid,
  handleSessionExpired,
} from "@/lib/session";
import {
  TOKEN_REFRESH_BEFORE_EXPIRY_MS,
  MIN_ACTIVITY_CHECK_INTERVAL_MS,
} from "@/const/constants";
import { authEventUtils } from "@/lib/authEvents";
import { getSessionRenewalAction } from "@/lib/sessionRenewal";
import type { User } from "@/types/auth";
import log from "@/lib/logger";

/**
 * Check if token is expiring soon (within threshold).
 * Reads expires_at from the non-HttpOnly cookie.
 */
export const isSessionExpiringSoon = (): boolean => {
  const expiresAt = getTokenExpiresAt();
  if (expiresAt === null) return false;

  const now = Date.now();
  const msUntilExpiry = expiresAt * 1000 - now;

  return msUntilExpiry > 0 && msUntilExpiry <= TOKEN_REFRESH_BEFORE_EXPIRY_MS;
};

/**
 * Refresh session via server.js BFF layer.
 * refresh_token is sent automatically via HttpOnly cookie.
 * server.js updates the cookies on success.
 */
export const refreshSession = async (): Promise<boolean> => {
  if (!hasAuthCookies()) {
    return false;
  }

  const newSession = await sessionService.refreshToken();
  if (newSession) {
    log.info("Session refreshed successfully");
    return true;
  }

  log.warn("Session refresh failed");
  return false;
};

// ============================================================================
// Hook implementation
// ============================================================================

export function useSessionManager(authProvider?: User["authProvider"]) {
  const { isSpeedMode, isDeploymentReady } = useDeployment();
  const reconcileExpiryRef = useRef<() => void>(() => {});
  const lastCasRenewAttemptAtRef = useRef(0);
  const isCasRenewingRef = useRef(false);
  const hasCasRenewAttemptedRef = useRef(false);

  useEffect(() => {
    lastCasRenewAttemptAtRef.current = authProvider === "cas" ? Date.now() : 0;
    isCasRenewingRef.current = false;
    hasCasRenewAttemptedRef.current = false;
  }, [authProvider]);

  useEffect(() => {
    if (isSpeedMode || !isDeploymentReady) return;

    if (!hasAuthCookies()) {
      return;
    }

    if (checkSessionValid()) {
      return;
    }

    handleSessionExpired();
  }, [isSpeedMode, isDeploymentReady]);

  /**
   * Proactive session expiry watcher
   * Triggers session-expired even if user does not make any API request
   */
  useEffect(() => {
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

      const expiresAt = getTokenExpiresAt();
      if (expiresAt === null) {
        return;
      }

      const now = Date.now();
      const delayMs = expiresAt * 1000 - now;

      if (delayMs <= 0) {
        handleSessionExpired();
        return;
      }

      timeoutId = window.setTimeout(() => {
        if (!checkSessionValid()) {
          handleSessionExpired();
        }
      }, delayMs);

      // Reschedule periodically to account for token refresh extending expires_at
      const capturedExpiresAt = expiresAt;
      intervalId = window.setInterval(() => {
        const currentExpiresAt = getTokenExpiresAt();
        if (currentExpiresAt === null) {
          clearTimers();
          return;
        }
        if (!checkSessionValid()) {
          handleSessionExpired();
          return;
        }
        if (currentExpiresAt !== capturedExpiresAt) {
          scheduleExpiryCheck();
        }
      }, 30_000);
    };

    const reconcileExpiry = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      if (!checkSessionValid() && hasAuthCookies()) {
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
  }, [isSpeedMode, isDeploymentReady]);

  /**
   * Setup automatic token refresh on user activity
   * Refreshes token before expiry to implement sliding expiration
   */
  const setupTokenAutoRefresh = useCallback(() => {
    if (isSpeedMode) return () => {};

    let lastActivityCheckAt = 0;

    const maybeRefreshOnActivity = async () => {
      try {
        reconcileExpiryRef.current();

        if (!checkSessionValid()) return;

        const now = Date.now();
        if (now - lastActivityCheckAt < MIN_ACTIVITY_CHECK_INTERVAL_MS) return;
        lastActivityCheckAt = now;

        if (typeof document !== "undefined" && document.hidden) return;

        if (authProvider === "cas") {
          const config = await casService.getConfig();
          if (!config.enabled || config.login_mode === "disabled") return;

          const expiresAt = getTokenExpiresAt();
          if (expiresAt === null) return;

          const currentTime = Date.now();
          const remainingLifetimeMs = expiresAt * 1000 - currentTime;
          const action = getSessionRenewalAction({
            authProvider,
            isVisible: !document.hidden,
            remainingLifetimeMs,
            localRefreshThresholdMs: TOKEN_REFRESH_BEFORE_EXPIRY_MS,
            currentTimeMs: currentTime,
            lastCasRenewAttemptAtMs: lastCasRenewAttemptAtRef.current,
            casRenewIntervalMs: config.renew_interval_seconds * 1000,
            casRenewSafetyWindowMs: config.renew_before_seconds * 1000,
            isCasRenewing: isCasRenewingRef.current,
            hasCasRenewAttempted: hasCasRenewAttemptedRef.current,
          });
          if (action !== "renew-cas") return;

          lastCasRenewAttemptAtRef.current = currentTime;
          isCasRenewingRef.current = true;
          hasCasRenewAttemptedRef.current = true;
          try {
            const success = await casService.renewInIframe(
              config.renew_timeout_seconds
            );
            if (success) {
              reconcileExpiryRef.current();
              authEventUtils.emitTokenRefreshed();
              log.info("CAS session renewed successfully");
            } else {
              log.warn("CAS session renewal failed");
            }
          } finally {
            isCasRenewingRef.current = false;
          }
          return;
        }

        const expiresAt = getTokenExpiresAt();
        if (expiresAt === null) return;
        const action = getSessionRenewalAction({
          authProvider,
          isVisible: !document.hidden,
          remainingLifetimeMs: expiresAt * 1000 - Date.now(),
          localRefreshThresholdMs: TOKEN_REFRESH_BEFORE_EXPIRY_MS,
          currentTimeMs: Date.now(),
          lastCasRenewAttemptAtMs: 0,
          casRenewIntervalMs: 0,
          casRenewSafetyWindowMs: 0,
          isCasRenewing: false,
          hasCasRenewAttempted: false,
        });
        if (action === "refresh-local") {
          const success = await refreshSession();

          if (!success) {
            log.debug("Token refresh failed, waiting for 401 from backend");
          } else {
            reconcileExpiryRef.current();
            authEventUtils.emitTokenRefreshed();
          }
        }
      } catch (error) {
        log.error("Activity-based refresh check failed:", error);
      }
    };

    const documentEvents: (keyof DocumentEventMap)[] = [
      "click",
      "keydown",
      "mousemove",
      "touchstart",
      "visibilitychange",
    ];

    const handler = () => {
      void maybeRefreshOnActivity();
    };

    window.addEventListener("focus", handler, { passive: true });
    documentEvents.forEach((eventName) => {
      document.addEventListener(eventName, handler, { passive: true });
    });

    return () => {
      window.removeEventListener("focus", handler);
      documentEvents.forEach((eventName) => {
        document.removeEventListener(eventName, handler);
      });
    };
  }, [authProvider, isSpeedMode]);

  useEffect(() => {
    const cleanupAutoRefresh = setupTokenAutoRefresh();
    return () => {
      cleanupAutoRefresh?.();
    };
  }, [setupTokenAutoRefresh]);

  return {
    isSessionExpiringSoon,
    refreshSession,
    setupTokenAutoRefresh,
  };
}
