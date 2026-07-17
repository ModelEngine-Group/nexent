"use client";

import { useCallback, useEffect, useRef } from "react";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useQuotaWarning } from "@/hooks/useQuotaWarning";
import { QUOTA_USAGE_CHANGED_EVENT } from "@/lib/quotaEvents";
import log from "@/lib/logger";
import quotaService from "@/services/quotaService";

const POLL_INTERVAL_MS = 5 * 60 * 1000;
const EVENT_DEBOUNCE_MS = 800;
const FOCUS_RECHECK_INTERVAL_MS = 60 * 1000;

interface QuotaWarningMonitorProps {
  enabled?: boolean;
}

export function QuotaWarningMonitor({
  enabled = true,
}: QuotaWarningMonitorProps) {
  const { user } = useAuthorizationContext();
  const userRole = user?.role;
  const tenantId = user?.tenantId;
  const {
    closeAllActiveNotifications,
    processPlatformQuotaStatus,
    processUsageQuotaStatus,
  } = useQuotaWarning(userRole, tenantId);
  const inFlightRef = useRef(false);
  const lastCheckedAtRef = useRef(0);
  const debounceTimerRef = useRef<number | null>(null);

  const checkWarnings = useCallback(
    async (forceRefresh: boolean) => {
      if (!enabled || !userRole || inFlightRef.current) return;

      inFlightRef.current = true;
      try {
        if (userRole === USER_ROLES.SU || userRole === USER_ROLES.ASSET_OWNER) {
          const overview = await quotaService.getPlatformOverview();
          processPlatformQuotaStatus(overview);
        } else if (tenantId) {
          const usage = await quotaService.getQuotaUsage(
            tenantId,
            forceRefresh,
            true
          );
          processUsageQuotaStatus(usage);
        }
        lastCheckedAtRef.current = Date.now();
      } catch (error) {
        log.warn("Failed to refresh quota warnings", error);
      } finally {
        inFlightRef.current = false;
      }
    },
    [
      enabled,
      processPlatformQuotaStatus,
      processUsageQuotaStatus,
      tenantId,
      userRole,
    ]
  );

  useEffect(() => {
    if (!enabled || !userRole) return;

    void checkWarnings(false);
    const pollTimer = window.setInterval(
      () => void checkWarnings(false),
      POLL_INTERVAL_MS
    );

    const refreshAfterQuotaChange = () => {
      if (inFlightRef.current) {
        debounceTimerRef.current = window.setTimeout(
          refreshAfterQuotaChange,
          EVENT_DEBOUNCE_MS
        );
        return;
      }
      debounceTimerRef.current = null;
      void checkWarnings(true);
    };

    const handleQuotaChanged = () => {
      if (debounceTimerRef.current) {
        window.clearTimeout(debounceTimerRef.current);
      }
      debounceTimerRef.current = window.setTimeout(
        refreshAfterQuotaChange,
        EVENT_DEBOUNCE_MS
      );
    };

    const handleVisibilityOrFocus = () => {
      if (
        document.visibilityState === "visible" &&
        Date.now() - lastCheckedAtRef.current >= FOCUS_RECHECK_INTERVAL_MS
      ) {
        void checkWarnings(false);
      }
    };

    window.addEventListener(QUOTA_USAGE_CHANGED_EVENT, handleQuotaChanged);
    window.addEventListener("focus", handleVisibilityOrFocus);
    document.addEventListener("visibilitychange", handleVisibilityOrFocus);

    return () => {
      window.clearInterval(pollTimer);
      if (debounceTimerRef.current) {
        window.clearTimeout(debounceTimerRef.current);
      }
      window.removeEventListener(QUOTA_USAGE_CHANGED_EVENT, handleQuotaChanged);
      window.removeEventListener("focus", handleVisibilityOrFocus);
      document.removeEventListener("visibilitychange", handleVisibilityOrFocus);
    };
  }, [checkWarnings, enabled, userRole]);

  useEffect(
    () => () => closeAllActiveNotifications(),
    [closeAllActiveNotifications, tenantId, userRole]
  );

  return null;
}
