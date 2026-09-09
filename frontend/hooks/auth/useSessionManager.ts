"use client";

import { useCallback, useEffect, useRef } from "react";

import { useDeployment } from "@/components/providers/deploymentProvider";
import { casService } from "@/services/casService";
import { sessionService } from "@/services/sessionService";
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
import {
  getHeartbeatIntervalMs,
  getHeartbeatLockName,
  isHeartbeatDue,
  readHeartbeatAttempt,
  writeHeartbeatAttempt,
} from "@/lib/casHeartbeat";
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

export function useSessionManager(user?: User | null) {
  const { isSpeedMode, isDeploymentReady } = useDeployment();
  const reconcileExpiryRef = useRef<() => void>(() => {});
  const lastHeartbeatAttemptAtRef = useRef(0);
  const heartbeatIntervalMsRef = useRef(getHeartbeatIntervalMs(300));
  const lastHeartbeatUrlRef = useRef("");
  const isHeartbeatAttemptInFlightRef = useRef(false);

  useEffect(() => {
    lastHeartbeatAttemptAtRef.current = 0;
    heartbeatIntervalMsRef.current = getHeartbeatIntervalMs(300);
    lastHeartbeatUrlRef.current = "";
    isHeartbeatAttemptInFlightRef.current = false;
  }, [user?.authProvider, user?.id]);

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
        if (typeof document !== "undefined" && document.hidden) return;

        const now = Date.now();
        if (user?.authProvider === "cas" && user.id) {
          const hasKnownHeartbeat = Boolean(lastHeartbeatUrlRef.current);
          if (
            hasKnownHeartbeat &&
            !isHeartbeatDue(
              lastHeartbeatAttemptAtRef.current,
              now,
              heartbeatIntervalMsRef.current
            )
          ) {
            return;
          }
          if (
            !hasKnownHeartbeat &&
            now - lastActivityCheckAt < MIN_ACTIVITY_CHECK_INTERVAL_MS
          ) {
            return;
          }
          lastActivityCheckAt = now;

          const config = await casService.getConfig();
          if (
            !config.enabled ||
            config.login_mode === "disabled" ||
            !config.heartbeat_url.trim()
          ) {
            lastHeartbeatAttemptAtRef.current = 0;
            lastHeartbeatUrlRef.current = "";
            return;
          }
          heartbeatIntervalMsRef.current = getHeartbeatIntervalMs(
            config.heartbeat_interval_seconds
          );

          const attemptHeartbeat = async () => {
            if (isHeartbeatAttemptInFlightRef.current) return;
            if (!checkSessionValid() || document.hidden) return;

            const currentTime = Date.now();
            const sharedAttempt = readHeartbeatAttempt(user.id);
            let lastAttemptAt = 0;
            if (sharedAttempt?.url === config.heartbeat_url) {
              lastAttemptAt = sharedAttempt.attemptedAt;
              lastHeartbeatAttemptAtRef.current = sharedAttempt.attemptedAt;
              lastHeartbeatUrlRef.current = config.heartbeat_url;
            } else if (lastHeartbeatUrlRef.current === config.heartbeat_url) {
              lastAttemptAt = lastHeartbeatAttemptAtRef.current;
            }
            if (
              !isHeartbeatDue(
                lastAttemptAt,
                currentTime,
                heartbeatIntervalMsRef.current
              )
            ) {
              return;
            }

            lastHeartbeatAttemptAtRef.current = currentTime;
            lastHeartbeatUrlRef.current = config.heartbeat_url;
            writeHeartbeatAttempt(user.id, {
              url: config.heartbeat_url,
              attemptedAt: currentTime,
            });
            isHeartbeatAttemptInFlightRef.current = true;
            try {
              await casService.sendHeartbeat(config);
            } finally {
              isHeartbeatAttemptInFlightRef.current = false;
            }
          };

          if ("locks" in navigator && navigator.locks) {
            await navigator.locks.request(
              getHeartbeatLockName(user.id),
              { ifAvailable: true },
              async (lock) => {
                if (lock) await attemptHeartbeat();
              }
            );
          } else {
            await attemptHeartbeat();
          }
          return;
        }

        if (now - lastActivityCheckAt < MIN_ACTIVITY_CHECK_INTERVAL_MS) return;
        lastActivityCheckAt = now;

        if (isSessionExpiringSoon()) {
          const success = await refreshSession();

          if (!success) {
            log.debug("Token refresh failed, waiting for 401 from backend");
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
    const windowEvents: (keyof WindowEventMap)[] = ["focus"];

    const handler = () => {
      void maybeRefreshOnActivity();
    };

    documentEvents.forEach((eventName) => {
      document.addEventListener(eventName, handler, { passive: true });
    });
    windowEvents.forEach((eventName) => {
      window.addEventListener(eventName, handler, { passive: true });
    });

    return () => {
      documentEvents.forEach((eventName) => {
        document.removeEventListener(eventName, handler);
      });
      windowEvents.forEach((eventName) => {
        window.removeEventListener(eventName, handler);
      });
    };
  }, [isSpeedMode, user?.authProvider, user?.id]);

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
