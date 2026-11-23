import type { TFunction } from "i18next";

import { formatFileSize } from "@/lib/utils";
import type { KBQuotaStatus } from "@/types/quota";

export interface KnowledgeBaseQuotaDisplay {
  hasQuota: boolean;
  availableCapacity: string;
  totalCapacity: string;
  usagePercent: number;
}

export const getKnowledgeBaseQuotaDisplay = (
  quotaStatus: KBQuotaStatus | null | undefined,
  t: TFunction
): KnowledgeBaseQuotaDisplay => {
  if (!quotaStatus) {
    return {
      hasQuota: false,
      availableCapacity: "-",
      totalCapacity: "-",
      usagePercent: 0,
    };
  }

  const quotaBytes = quotaStatus.soft_quota_bytes;
  if (quotaBytes == null) {
    return {
      hasQuota: false,
      availableCapacity: t("knowledgeBase.capacity.unlimited"),
      totalCapacity: t("knowledgeBase.capacity.unlimited"),
      usagePercent: quotaStatus.actual_bytes > 0 ? 100 : 0,
    };
  }

  let usagePercent = quotaStatus.usage_pct;
  if (usagePercent == null) {
    if (quotaBytes > 0) {
      usagePercent = (quotaStatus.actual_bytes / quotaBytes) * 100;
    } else {
      usagePercent = quotaStatus.actual_bytes > 0 ? 100 : 0;
    }
  }

  return {
    hasQuota: true,
    availableCapacity: formatFileSize(
      Math.max(quotaBytes - quotaStatus.actual_bytes, 0)
    ),
    totalCapacity:
      quotaStatus.soft_quota_readable || formatFileSize(quotaBytes),
    usagePercent: Math.min(100, Math.max(0, usagePercent)),
  };
};
