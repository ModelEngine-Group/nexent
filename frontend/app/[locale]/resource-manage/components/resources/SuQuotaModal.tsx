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
  const [quotaInput, setQuotaInput] = useState("");
  const quotaValue = quotaInput === "" ? null : Number(quotaInput);

  // Reset local state when modal opens; then load data
  useEffect(() => {
    if (!open || !tenantId) return;

    // Reset on open
    setConfig(null);
    setUsageData(null);
    setPlatformOverview(null);
    setUnit("GB");
    setQuotaInput("");

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
          setQuotaInput(String(Math.round(currentBytes / MB)));
        } else {
          setUnit("GB");
          setQuotaInput(currentBytes ? String(Math.round(currentBytes / GB)) : "");
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
      if (quotaValue == null) {
        // Deleting this config restores the tenant to unlimited without
        // resetting its warning preferences.
        await quotaService.deleteTenantQuota(tenantId!);
      } else {
        await quotaService.updateTenantQuota(tenantId!, {
          hard_limit_gb: unit === "GB" ? quotaValue : undefined,
          hard_limit_mb: unit === "MB" ? quotaValue : undefined,
        });
      }
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
    setQuotaInput(
      valueBytes == null
        ? ""
        : String(Math.round(valueBytes / (nextUnit === "GB" ? GB : MB)))
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
                  <Descriptions.Item
                    label={t("quota.esPhysicalIndex", "ES Physical Index")}
                  >
                    {usageData.es_physical_readable || "0 B"}
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
            <div className="flex items-stretch">
            <input
              style={{ width: 200 }}
              className="ant-input rounded-r-none"
              value={quotaInput}
              onChange={(event) => {
                const nextValue = event.target.value;
                if (nextValue === "" || /^\d+$/.test(nextValue)) {
                  setQuotaInput(nextValue);
                }
              }}
              placeholder={t("quota.unlimited", "Unlimited")}
              inputMode="numeric"
            />
            <span className="flex items-center border border-l-0 border-solid border-[#d9d9d9] rounded-r-md bg-[#fafafa] px-3 text-sm text-[#555]">
              {unit}
            </span>
            </div>
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
