/**
 * Hook to check if tenant storage is at hard limit (uploads blocked).
 * Returns { isBlocked, message } derived from quota usage data.
 */
import { useState, useEffect, useCallback } from "react";
import { QUOTA_USAGE_CHANGED_EVENT } from "@/lib/quotaEvents";
import quotaService from "@/services/quotaService";

interface StorageBlockedState {
  isBlocked: boolean;
  message: string | null;
  usagePct: number | null;
  totalReadable: string | null;
  hardLimitReadable: string | null;
}

export function useStorageQuotaBlocked(
  tenantId: string | null | undefined
): StorageBlockedState {
  const [state, setState] = useState<StorageBlockedState>({
    isBlocked: false,
    message: null,
    usagePct: null,
    totalReadable: null,
    hardLimitReadable: null,
  });

  const checkQuota = useCallback(
    async (forceRefresh = false) => {
      if (!tenantId) return;
      try {
        const usage = await quotaService.getQuotaUsage(
          tenantId,
          forceRefresh,
          false
        );
        if (usage.tenant_warning_level === "blocked") {
          setState({
            isBlocked: true,
            message: `Storage full — ${usage.total_readable || "0"} / ${usage.hard_limit_readable || "?"}. Uploads are blocked.`,
            usagePct: usage.usage_pct,
            totalReadable: usage.total_readable,
            hardLimitReadable: usage.hard_limit_readable,
          });
        } else {
          setState({
            isBlocked: false,
            message: null,
            usagePct: usage.usage_pct,
            totalReadable: usage.total_readable,
            hardLimitReadable: usage.hard_limit_readable,
          });
        }
      } catch {
        // Silently ignore — quota API may not be configured
      }
    },
    [tenantId]
  );

  useEffect(() => {
    void checkQuota();
    const handleQuotaChanged = () => void checkQuota(true);
    window.addEventListener(QUOTA_USAGE_CHANGED_EVENT, handleQuotaChanged);
    return () => {
      window.removeEventListener(QUOTA_USAGE_CHANGED_EVENT, handleQuotaChanged);
    };
  }, [checkQuota]);

  return state;
}
