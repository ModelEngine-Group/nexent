"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Progress, Spin } from "antd";

import { QUOTA_USAGE_CHANGED_EVENT } from "@/lib/quotaEvents";
import quotaService from "@/services/quotaService";
import type { PersonalSelfCapacity } from "@/types/quota";

const GB = 1024 * 1024 * 1024;
const MB = 1024 * 1024;

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "-";
  if (bytes >= GB) return `${(bytes / GB).toFixed(1)} GB`;
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${bytes} B`;
}

export default function PersonalKnowledgeBaseCapacityBar() {
  const { t } = useTranslation("common");
  const [capacity, setCapacity] = useState<PersonalSelfCapacity | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const loadCapacity = useCallback(async () => {
    setLoading(true);
    try {
      const data = await quotaService.getPersonalSelfCapacity();
      setCapacity(data);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCapacity();
    window.addEventListener(QUOTA_USAGE_CHANGED_EVENT, loadCapacity);
    return () =>
      window.removeEventListener(QUOTA_USAGE_CHANGED_EVENT, loadCapacity);
  }, [loadCapacity]);

  if (loading && !capacity) {
    return (
      <div className="flex h-12 items-center justify-center border-t border-gray-200 px-4">
        <Spin size="small" />
      </div>
    );
  }

  if (failed && !capacity) {
    return (
      <div className="border-t border-gray-200 px-4 py-2">
        <Alert
          type="warning"
          showIcon
          message={t("knowledgeBase.personalCapacity.loadFailed")}
        />
      </div>
    );
  }

  if (!capacity) return null;

  const hasQuota = capacity.quota_bytes != null;
  const progress = hasQuota
    ? Math.min(100, Math.max(0, capacity.usage_rate ?? 0))
    : 0;
  const used = capacity.used_readable || formatBytes(capacity.used_bytes);
  const quota = capacity.quota_readable || formatBytes(capacity.quota_bytes);

  return (
    <div className="shrink-0 border-t border-gray-200 px-4 py-3">
      <div className="mb-1 flex items-center justify-between gap-3 text-xs text-gray-600">
        <span>{t("knowledgeBase.personalCapacity.title")}</span>
        <span className="font-medium text-gray-800">
          {hasQuota
            ? t("knowledgeBase.personalCapacity.withQuota", { used, quota })
            : t("knowledgeBase.personalCapacity.unlimited", { used })}
        </span>
      </div>
      <Progress
        percent={progress}
        showInfo={false}
        status={capacity.is_over_quota ? "exception" : "normal"}
        strokeColor={hasQuota ? undefined : "#94a3b8"}
      />
      <div className="mt-1 text-right text-[11px] text-gray-400">
        {t("quota.esPhysicalIndex", "ES Physical Index")}:{" "}
        {capacity.es_physical_readable || "0 B"}
      </div>
    </div>
  );
}
