"use client";

import React, { useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Card,
  Table,
  Progress,
  Tag,
  Button,
  InputNumber,
  Space,
  Typography,
  message,
  Modal,
} from "antd";
import {
  CheckOutlined,
  CloseOutlined,
  EditOutlined,
  SettingOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import quotaService from "@/services/quotaService";
import type { PlatformQuotaOverview, PlatformTenantQuota } from "@/types/quota";

const { Text, Title } = Typography;

const STROKE_COLORS = {
  normal: "#52c41a",
  warning: "#faad14",
  exceeded: "#d48806",
  blocked: "#ff4d4f",
};

function getProgressColor(usagePct: number | null | undefined): string {
  if (usagePct == null) return STROKE_COLORS.normal;
  if (usagePct >= 100) return STROKE_COLORS.blocked;
  if (usagePct >= 80) return STROKE_COLORS.warning;
  return STROKE_COLORS.normal;
}

export function PlatformQuotaPanel() {
  const { t } = useTranslation("common");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<PlatformQuotaOverview | null>(null);
  const [editingTenant, setEditingTenant] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<number | null>(null);
  const [capacityModalOpen, setCapacityModalOpen] = useState(false);
  const [capacityValue, setCapacityValue] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  const getWarningTag = (level: string | undefined): React.ReactNode => {
    const normalizedLevel = level || "normal";
    const colors: Record<string, string> = {
      normal: "green",
      warning: "orange",
      critical: "volcano",
      blocked: "red",
    };
    return (
      <Tag color={colors[normalizedLevel] || "default"}>
        {t(`quota.status.${normalizedLevel}`, normalizedLevel)}
      </Tag>
    );
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const overview = await quotaService.getPlatformOverview();
      setData(overview);
    } catch (err: any) {
      message.error(
        err.message ||
          t(
            "quota.loadPlatformOverviewFailed",
            "Failed to load platform overview"
          )
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Inline edit for tenant hard quota
  const startEditTenant = (tenantId: string, currentGb: number | null) => {
    setEditingTenant(tenantId);
    setEditValue(currentGb);
  };

  const saveTenantQuota = async (tenantId: string) => {
    setSaving(true);
    try {
      await quotaService.setTenantHardQuota(tenantId, {
        hard_limit_gb: editValue,
      });
      message.success(t("quota.tenantQuotaUpdated", "Tenant quota updated"));
      setEditingTenant(null);
      fetchData();
    } catch (err: any) {
      message.error(
        err.message ||
          t("quota.updateTenantQuotaFailed", "Failed to update tenant quota")
      );
    } finally {
      setSaving(false);
    }
  };

  const handleSaveCapacity = async () => {
    setSaving(true);
    try {
      await quotaService.setPlatformCapacity({
        capacity_gb: capacityValue,
      });
      message.success(
        t("quota.platformCapacityUpdated", "Platform capacity updated")
      );
      setCapacityModalOpen(false);
      fetchData();
    } catch (err: any) {
      message.error(
        err.message ||
          t(
            "quota.updatePlatformCapacityFailed",
            "Failed to update platform capacity"
          )
      );
    } finally {
      setSaving(false);
    }
  };

  // Fair share reference
  const tenantCount = data?.tenant_count || 0;
  const capacityGb = data?.platform_capacity_bytes
    ? Math.round(data.platform_capacity_bytes / (1024 * 1024 * 1024))
    : null;
  const fairShareGb =
    capacityGb && tenantCount > 0 ? capacityGb / tenantCount : null;
  const fairShareDisplay =
    fairShareGb != null
      ? Number.isInteger(fairShareGb)
        ? fairShareGb.toString()
        : fairShareGb.toFixed(2)
      : null;
  const isOversubscribed =
    data?.oversubscription_ratio != null && data.oversubscription_ratio > 1;

  const columns = [
    {
      title: t("quota.tenantName", "Tenant Name"),
      dataIndex: "tenant_name",
      key: "name",
    },
    {
      title: t("quota.hardLimit", "Hard Quota"),
      dataIndex: "hard_limit_bytes",
      key: "quota",
      render: (val: number | null, record: PlatformTenantQuota) => {
        if (editingTenant === record.tenant_id) {
          return (
            <Space>
              <InputNumber
                value={editValue}
                onChange={(v) => setEditValue(v)}
                addonAfter="GB"
                style={{ width: 120 }}
                autoFocus
                onPressEnter={() => saveTenantQuota(record.tenant_id)}
              />
              <Button
                size="small"
                type="primary"
                icon={<CheckOutlined />}
                loading={saving}
                onClick={() => saveTenantQuota(record.tenant_id)}
                aria-label={t("common.confirm", "Confirm")}
              />
              <Button
                size="small"
                icon={<CloseOutlined />}
                onClick={() => setEditingTenant(null)}
                aria-label={t("common.cancel", "Cancel")}
              />
            </Space>
          );
        }
        const gb = val ? Math.round(val / (1024 * 1024 * 1024)) : null;
        return (
          <Space>
            <Text>{gb ? `${gb} GB` : t("quota.unlimited", "Unlimited")}</Text>
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => startEditTenant(record.tenant_id, gb)}
            />
          </Space>
        );
      },
    },
    {
      title: t("quota.usage", "Usage"),
      key: "usage",
      render: (_: any, record: PlatformTenantQuota) => (
        <div style={{ minWidth: 140 }}>
          <Progress
            percent={record.usage_pct ?? 0}
            size="small"
            strokeColor={getProgressColor(record.usage_pct)}
            format={() => `${record.usage_pct ?? 0}%`}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.actual_readable || "0 B"}
            {record.hard_limit_readable
              ? ` / ${record.hard_limit_readable}`
              : ""}
          </Text>
        </div>
      ),
    },
    {
      title: t("quota.status", "Status"),
      dataIndex: "warning_level",
      key: "status",
      render: (level: string) => getWarningTag(level),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      {/* Platform Capacity Header */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Space direction="vertical" size={0}>
            <Text strong>
              {t("quota.platformCapacity", "Platform Capacity")}:{" "}
              {capacityGb
                ? `${capacityGb} GB`
                : t("quota.unlimited", "Not set")}
              {" | "}
              {t("quota.allocated", "Allocated")}:{" "}
              {data?.total_allocated_readable || "0 B"}
              {" | "}
              {t("quota.used", "Used")}: {data?.total_actual_readable || "0 B"}
            </Text>
            {fairShareDisplay != null && (
              <Text type="secondary">
                <InfoCircleOutlined style={{ marginRight: 4 }} />
                {t("quota.fairShare", "Fair Share")}: {capacityGb} GB &divide;{" "}
                {tenantCount} = {fairShareDisplay}{" "}
                {t("quota.gbPerTenant", "GB/tenant")}
              </Text>
            )}
          </Space>
          <Button
            icon={<SettingOutlined />}
            onClick={() => {
              setCapacityValue(capacityGb);
              setCapacityModalOpen(true);
            }}
          >
            {t("quota.quotaManagement", "Capacity Settings")}
          </Button>
        </Space>
      </Card>

      {isOversubscribed && data && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={t(
            "quota.platformOversubscribed",
            "Tenant quotas exceed platform capacity"
          )}
          description={t("quota.platformOversubscribedDescription", {
            allocated: data.total_allocated_readable || "0 B",
            capacity:
              data.platform_capacity_readable ||
              t("quota.unlimited", "Unlimited"),
            ratio: data.oversubscription_ratio?.toFixed(2),
            defaultValue:
              "{{allocated}} allocated / {{capacity}} capacity ({{ratio}}x). Tenant hard quotas remain independently enforced.",
          })}
        />
      )}

      {/* Per-Tenant Table */}
      <Table
        dataSource={data?.tenants || []}
        columns={columns}
        rowKey="tenant_id"
        loading={loading}
        pagination={false}
        size="small"
      />

      {/* Capacity Settings Modal */}
      <Modal
        title={t("quota.platformCapacity", "Platform Capacity")}
        open={capacityModalOpen}
        onCancel={() => setCapacityModalOpen(false)}
        onOk={handleSaveCapacity}
        confirmLoading={saving}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Text>
            {t("quota.setPlatformCapacity", "Set platform storage capacity")}:
          </Text>
          <InputNumber
            value={capacityValue}
            onChange={(v) => setCapacityValue(v)}
            addonAfter="GB"
            placeholder={t("quota.unlimited", "Unlimited")}
            style={{ width: "100%" }}
            min={0}
          />
        </Space>
      </Modal>
    </div>
  );
}
