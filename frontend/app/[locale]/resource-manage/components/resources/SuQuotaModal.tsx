"use client";

/**
 * SU (Super Admin) Quota Modal — Tenant Hard Limit Assignment
 *
 * Minimal UI focused on SU's sole responsibility:
 * allocating storage capacity to individual tenants.
 */
import React, { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  InputNumber,
  App,
  Descriptions,
  Progress,
  Card,
  Space,
  Segmented,
} from "antd";
import { CloudOutlined, DatabaseOutlined } from "@ant-design/icons";
import quotaService from "@/services/quotaService";
import {
  getQuotaConflictTranslationKey,
  type PlatformQuotaOverview,
  type QuotaUsageResponse,
} from "@/types/quota";

interface SuQuotaModalProps {
  open: boolean;
  tenantId: string | null;
  onCancel: () => void;
  onSuccess: () => void;
  onUsageChange?: (usage: QuotaUsageResponse) => void;
}

const GB = 1024 * 1024 * 1024;
const MB = 1024 * 1024;

export function SuQuotaModal({
  open,
  tenantId,
  onCancel,
  onSuccess,
  onUsageChange,
}: SuQuotaModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState<any>(null);
  const [usageData, setUsageData] = useState<any>(null);
  const [platformOverview, setPlatformOverview] =
    useState<PlatformQuotaOverview | null>(null);
  const [saving, setSaving] = useState(false);
  const [unit, setUnit] = useState<"GB" | "MB">("GB");
  const [quotaValue, setQuotaValue] = useState<number | null>(null);

  // Reset local state when modal opens; then load data
  useEffect(() => {
    if (!open || !tenantId) return;

    // Reset on open
    setConfig(null);
    setUsageData(null);
    setPlatformOverview(null);
    setUnit("GB");
    setQuotaValue(null);

    let cancelled = false;
    setLoading(true);

    (async () => {
      try {
        const [cfg, usage, overview] = await Promise.all([
          quotaService.getQuotaConfig(tenantId),
          quotaService.getQuotaUsage(tenantId, true, false),
          quotaService.getPlatformOverview(),
        ]);
        if (cancelled) return;

        setConfig(cfg);
        setUsageData(usage);
        setPlatformOverview(overview);
        onUsageChange?.(usage);

        const currentBytes: number | null = cfg?.hard_limit_bytes ?? null;
        if (currentBytes && currentBytes < GB) {
          setUnit("MB");
          setQuotaValue(Math.round(currentBytes / MB));
        } else {
          setUnit("GB");
          setQuotaValue(currentBytes ? Math.round(currentBytes / GB) : null);
        }
      } catch (err: any) {
        if (!cancelled) {
          console.error("Failed to load quota config:", err);
          message.error(err?.message || "Failed to load quota config");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, tenantId, onUsageChange]);

  const handleSave = async () => {
    try {
      setSaving(true);
      await quotaService.updateTenantQuota(tenantId!, {
        hard_limit_gb: unit === "GB" ? quotaValue : undefined,
        hard_limit_mb: unit === "MB" ? quotaValue : undefined,
      });
      message.success(t("quota.saveSuccess", "Tenant quota updated"));
      onSuccess();
    } catch (err: any) {
      const errorKey = getQuotaConflictTranslationKey(err);
      message.error(
        errorKey
          ? t(errorKey)
          : err.message ||
              t("quota.updateTenantQuotaFailed", "Tenant quota update failed")
      );
    } finally {
      setSaving(false);
    }
  };

  const hardLimitBytes = config?.hard_limit_bytes ?? null;
  const hardLimitGb = hardLimitBytes ? hardLimitBytes / GB : null;
  const usageBytes = usageData?.total_bytes ?? 0;
  const usagePct = usageData?.usage_pct ?? 0;
  const usedReadable =
    usageBytes >= GB
      ? `${(usageBytes / GB).toFixed(1)} GB`
      : `${(usageBytes / MB).toFixed(1)} MB`;
  const unitBytes = unit === "GB" ? GB : MB;
  const minimumQuota = Math.ceil(usageBytes / unitBytes);
  const currentQuotaBytes = hardLimitBytes || 0;
  const maximumQuota =
    platformOverview?.platform_capacity_bytes == null
      ? undefined
      : Math.floor(
          ((platformOverview.remaining_allocatable_bytes || 0) +
            currentQuotaBytes) /
            unitBytes
        );
  const validMaximumQuota =
    maximumQuota == null || maximumQuota < minimumQuota
      ? undefined
      : maximumQuota;

  const changeUnit = (nextUnit: "GB" | "MB") => {
    if (nextUnit === unit) return;
    const valueBytes = quotaValue == null ? null : quotaValue * unitBytes;
    setUnit(nextUnit);
    setQuotaValue(
      valueBytes == null
        ? null
        : Math.round(valueBytes / (nextUnit === "GB" ? GB : MB))
    );
  };

  return (
    <Modal
      title={t("quota.suTitle", "Tenant Storage Allocation")}
      open={open}
      onCancel={onCancel}
      onOk={handleSave}
      confirmLoading={saving}
      okText={t("common.save", "Save")}
      cancelText={t("common.cancel", "Cancel")}
      width={480}
      destroyOnClose
    >
      <div className="space-y-4">
        {/* Current status card */}
        <Card size="small" className="bg-gray-50">
          <Space direction="vertical" style={{ width: "100%" }}>
            <div className="flex items-center gap-2 text-gray-600 text-sm">
              <DatabaseOutlined />
              <span>{t("quota.currentUsage", "Current Usage")}</span>
            </div>
            {usageData ? (
              <div>
                <Progress
                  percent={Math.min(usagePct, 100)}
                  strokeColor={
                    usagePct >= 100
                      ? "#ff4d4f"
                      : usagePct >= 80
                        ? "#faad14"
                        : "#52c41a"
                  }
                  size="small"
                  style={{ marginBottom: 4 }}
                />
                <Descriptions size="small" column={2}>
                  <Descriptions.Item label={t("quota.used", "Used")}>
                    {usedReadable}
                  </Descriptions.Item>
                  <Descriptions.Item label={t("quota.kbCount", "KBs")}>
                    {usageData.kb_count ?? 0}
                  </Descriptions.Item>
                  {hardLimitGb != null && (
                    <Descriptions.Item
                      label={t("quota.hardLimit", "Hard Limit")}
                      span={2}
                    >
                      {hardLimitGb.toFixed(1)} GB
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </div>
            ) : (
              <span className="text-gray-400">
                {t("common.loading", "Loading...")}
              </span>
            )}
          </Space>
        </Card>

        {/* Hard limit input — controlled, no Form wrapper */}
        <div>
          <div className="flex items-center gap-1 text-sm font-medium mb-2">
            <CloudOutlined />
            <span>
              {t("quota.tenantHardLimit", "Tenant Hard Storage Limit")}
            </span>
          </div>
          <Space>
            <InputNumber
              style={{ width: 200 }}
              value={quotaValue}
              onChange={(v) => setQuotaValue(v ?? null)}
              addonAfter={unit}
              placeholder={t("quota.unlimited", "Unlimited")}
              min={minimumQuota}
              max={validMaximumQuota}
              precision={0}
              size="large"
            />
            <Segmented
              options={["GB", "MB"]}
              value={unit}
              onChange={(val) => changeUnit(val as "GB" | "MB")}
            />
          </Space>
          <div style={{ marginTop: 4, fontSize: 12, color: "#999" }}>
            {platformOverview?.platform_capacity_bytes == null
              ? t(
                  "quota.suHint",
                  "Set to empty for unlimited. This tenant cannot exceed this limit."
                )
              : t("quota.suAllocationHint", {
                  minimum: `${minimumQuota} ${unit}`,
                  maximum:
                    validMaximumQuota == null
                      ? t("quota.unlimited", "Unlimited")
                      : `${validMaximumQuota} ${unit}`,
                  defaultValue:
                    "Allowed range: {{minimum}} to {{maximum}}, based on current usage and remaining platform capacity.",
                })}
          </div>
        </div>
      </div>
    </Modal>
  );
}
