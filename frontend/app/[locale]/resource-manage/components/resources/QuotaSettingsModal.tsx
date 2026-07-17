"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Form,
  InputNumber,
  Switch,
  Slider,
  Table,
  Button,
  Space,
  Progress,
  Tag,
  Tooltip,
  message,
  Typography,
  Divider,
  Row,
  Col,
  Segmented,
} from "antd";
import {
  InfoCircleOutlined,
  WarningOutlined,
  ExclamationCircleOutlined,
} from "@ant-design/icons";
import quotaService from "@/services/quotaService";
import type {
  TenantQuotaConfig,
  KBQuotaStatus,
  QuotaUsageResponse,
} from "@/types/quota";

const { Text, Title } = Typography;

interface QuotaSettingsModalProps {
  open: boolean;
  tenantId: string | null;
  onCancel: () => void;
  onSuccess: () => void;
  onUsageChange?: (usage: QuotaUsageResponse) => void;
}

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

function getWarningTag(level: string | undefined): React.ReactNode {
  if (!level || level === "normal") return <Tag color="green">Normal</Tag>;
  if (level === "warning") return <Tag color="orange">Warning</Tag>;
  if (level === "exceeded") return <Tag color="gold">Exceeded</Tag>;
  if (level === "critical") return <Tag color="volcano">Critical</Tag>;
  if (level === "blocked") return <Tag color="red">Blocked</Tag>;
  return null;
}

const GB = 1024 * 1024 * 1024;
const MB = 1024 * 1024;
const MIN_WARNING_THRESHOLD = 50;
const MAX_WARNING_THRESHOLD = 90;
const MIN_CRITICAL_THRESHOLD = 85;
const MAX_CRITICAL_THRESHOLD = 99;
const THRESHOLD_TRACK_COLORS = {
  normal: "#73d13d",
  warning: "#ffc53d",
  critical: "#ff7875",
};
const PUSHABLE_THRESHOLD_SLIDER_PROPS = {
  allowCross: true,
  pushable: 1,
};

function normalizeThresholds(
  warningThreshold: number,
  criticalThreshold: number
): [number, number] {
  const critical = Math.max(
    MIN_CRITICAL_THRESHOLD,
    Math.min(MAX_CRITICAL_THRESHOLD, criticalThreshold)
  );
  const warning = Math.max(
    MIN_WARNING_THRESHOLD,
    Math.min(MAX_WARNING_THRESHOLD, critical - 1, warningThreshold)
  );
  return [warning, Math.max(critical, warning + 1)];
}

export function QuotaSettingsModal({
  open,
  tenantId,
  onCancel,
  onSuccess,
  onUsageChange,
}: QuotaSettingsModalProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<TenantQuotaConfig | null>(null);
  const [usageData, setUsageData] = useState<QuotaUsageResponse | null>(null);
  const [warningEnabled, setWarningEnabled] = useState(true);
  const [unit, setUnit] = useState<"GB" | "MB">("GB");
  const [thresholds, setThresholds] = useState<[number, number]>([80, 95]);
  const [activeThresholdIndex, setActiveThresholdIndex] = useState<
    number | null
  >(null);
  // Quota input managed as plain controlled state (not Form field)
  const [quotaValue, setQuotaValue] = useState<number | null>(null);

  // Fetch current quota config and usage
  const fetchData = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const [configData, usage] = await Promise.all([
        quotaService.getQuotaConfig(tenantId),
        quotaService.getQuotaUsage(tenantId, true, true),
      ]);
      setConfig(configData);
      setUsageData(usage);
      onUsageChange?.(usage);
      setWarningEnabled(configData.warning_enabled);

      const [warningThreshold, criticalThreshold] = normalizeThresholds(
        configData.warning_threshold_pct,
        configData.critical_threshold_pct
      );
      setThresholds([warningThreshold, criticalThreshold]);

      // Set warning form fields
      form.setFields([
        { name: "warning_enabled", value: configData.warning_enabled },
        {
          name: "warning_threshold_pct",
          value: warningThreshold,
        },
        {
          name: "critical_threshold_pct",
          value: criticalThreshold,
        },
      ]);

      // Set quota controlled state (outside Form)
      const quotaBytes = configData.hard_limit_bytes;
      if (quotaBytes && quotaBytes < GB) {
        setUnit("MB");
        setQuotaValue(Math.round(quotaBytes / MB));
      } else {
        setUnit("GB");
        setQuotaValue(quotaBytes ? Math.round(quotaBytes / GB) : null);
      }
    } catch (err: any) {
      message.error(err.message || "Failed to load quota settings");
    } finally {
      setLoading(false);
    }
  }, [tenantId, form, onUsageChange]);

  useEffect(() => {
    if (open) {
      fetchData();
    }
  }, [open, fetchData]);

  const handleThresholdChange = (value: number | number[]) => {
    if (!Array.isArray(value) || value.length !== 2) return;

    if (activeThresholdIndex === 0 && value[0] > MAX_WARNING_THRESHOLD) {
      const [currentWarning, currentCritical] = thresholds;
      const currentGap = currentCritical - currentWarning;
      const pushedCritical =
        currentGap === 1
          ? Math.min(MAX_CRITICAL_THRESHOLD, MAX_WARNING_THRESHOLD + 1)
          : currentCritical;
      setThresholds([MAX_WARNING_THRESHOLD, pushedCritical]);
      form.setFieldsValue({
        warning_threshold_pct: MAX_WARNING_THRESHOLD,
        critical_threshold_pct: pushedCritical,
      });
      return;
    }

    if (activeThresholdIndex === 1 && value[1] < MIN_CRITICAL_THRESHOLD) {
      const [currentWarning, currentCritical] = thresholds;
      const stoppedWarning =
        currentCritical === currentWarning + 1
          ? MIN_CRITICAL_THRESHOLD - 1
          : currentWarning;
      setThresholds([stoppedWarning, MIN_CRITICAL_THRESHOLD]);
      form.setFieldsValue({
        warning_threshold_pct: stoppedWarning,
        critical_threshold_pct: MIN_CRITICAL_THRESHOLD,
      });
      return;
    }

    const [warningThreshold, criticalThreshold] = normalizeThresholds(
      value[0],
      value[1]
    );
    setThresholds([warningThreshold, criticalThreshold]);
    form.setFieldsValue({
      warning_threshold_pct: warningThreshold,
      critical_threshold_pct: criticalThreshold,
    });
  };

  const thresholdPosition = (value: number) =>
    ((value - MIN_WARNING_THRESHOLD) /
      (MAX_CRITICAL_THRESHOLD - MIN_WARNING_THRESHOLD)) *
    100;
  const warningPosition = thresholdPosition(thresholds[0]);
  const criticalPosition = thresholdPosition(thresholds[1]);
  const thresholdSegmentTransition =
    "left 160ms cubic-bezier(0.2, 0, 0, 1), width 160ms cubic-bezier(0.2, 0, 0, 1)";

  const setActiveThresholdHandle = (target: EventTarget | null) => {
    if (!(target instanceof HTMLElement)) return;
    if (target.closest(".ant-slider-handle-1")) {
      setActiveThresholdIndex(0);
    } else if (target.closest(".ant-slider-handle-2")) {
      setActiveThresholdIndex(1);
    }
  };

  const handleSave = async () => {
    if (!tenantId) return;
    try {
      const values = await form.validateFields();

      // Validate: warning threshold must be less than critical threshold
      if (values.warning_threshold_pct >= values.critical_threshold_pct) {
        message.error(
          t(
            "quota.thresholdError",
            "Warning threshold must be less than critical threshold"
          )
        );
        return;
      }

      setSaving(true);

      const canEditHardLimit = config?.hard_limit_editable !== false;
      const payload: any = {
        warning_enabled: values.warning_enabled,
        warning_threshold_pct: values.warning_threshold_pct,
        critical_threshold_pct: values.critical_threshold_pct,
      };
      // Only include hard limit when user is allowed to change it
      if (canEditHardLimit) {
        if (unit === "GB") {
          payload.hard_limit_gb = quotaValue;
        } else {
          payload.hard_limit_mb = quotaValue;
        }
      }
      await quotaService.updateTenantQuota(tenantId, payload);

      message.success(
        t("quota.saveSuccess", "Quota settings saved successfully")
      );
      onSuccess();
    } catch (err: any) {
      if (err.message) {
        message.error(err.message);
      }
    } finally {
      setSaving(false);
    }
  };

  // Fair share reference
  const hardLimitGb = config?.hard_limit_bytes
    ? Math.round(config.hard_limit_bytes / GB)
    : null;
  const kbCount = usageData?.kb_count || 0;
  const fairShareGb =
    hardLimitGb && kbCount > 0 ? Math.round(hardLimitGb / kbCount) : null;

  // Per-KB breakdown columns
  const breakdownColumns = [
    {
      title: t("quota.kbName", "KB Name"),
      dataIndex: "knowledge_name",
      key: "name",
    },
    {
      title: t("quota.softQuota", "Soft Quota"),
      dataIndex: "soft_quota_readable",
      key: "quota",
      render: (val: string | null) => val || t("quota.unlimited", "Unlimited"),
    },
    {
      title: t("quota.actualUsage", "Actual Usage"),
      dataIndex: "actual_readable",
      key: "actual",
      render: (val: string | null) => val || "0 B",
    },
    {
      title: t("quota.usage", "Usage"),
      dataIndex: "usage_pct",
      key: "usage_pct",
      render: (pct: number | null, record: KBQuotaStatus) => (
        <div style={{ minWidth: 120 }}>
          <Progress
            percent={pct ?? 0}
            size="small"
            strokeColor={getProgressColor(pct)}
            format={() => (pct != null ? `${pct}%` : "-")}
          />
        </div>
      ),
    },
    {
      title: t("quota.status", "Status"),
      dataIndex: "kb_warning_level",
      key: "status",
      render: (level: string) => getWarningTag(level),
    },
  ];

  return (
    <Modal
      title={t("quota.title", "Quota Management")}
      open={open}
      onCancel={onCancel}
      width={800}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel", "Cancel")}
        </Button>,
        <Button key="save" type="primary" loading={saving} onClick={handleSave}>
          {t("common.save", "Save Settings")}
        </Button>,
      ]}
      destroyOnClose
    >
      {/* Tenant Hard Limit — controlled input, outside Form */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 8 }}>
          <Space>
            <span>{t("quota.hardLimit", "Tenant Hard Limit")}</span>
            {config?.hard_limit_editable === false && (
              <Tooltip
                title={t(
                  "quota.managedByPlatform",
                  "Managed by platform administrator"
                )}
              >
                <InfoCircleOutlined style={{ color: "#1890ff" }} />
              </Tooltip>
            )}
          </Space>
        </div>
        <Space>
          <InputNumber
            min={0}
            precision={0}
            value={quotaValue}
            onChange={(v) => setQuotaValue(v ?? null)}
            addonAfter={unit}
            placeholder={t("quota.unlimited", "Unlimited")}
            style={{ width: 200 }}
            disabled={config?.hard_limit_editable === false}
          />
          <Segmented
            options={["GB", "MB"]}
            value={unit}
            onChange={(val) => setUnit(val as "GB" | "MB")}
            disabled={config?.hard_limit_editable === false}
          />
        </Space>
      </div>

      {/* Warning config — still managed by Form */}
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          warning_enabled: true,
          warning_threshold_pct: 80,
          critical_threshold_pct: 95,
        }}
      >
        {/* Warning Toggle */}
        <Form.Item
          name="warning_enabled"
          label={t("quota.warningNotifications", "Warning Notifications")}
          valuePropName="checked"
        >
          <Switch onChange={(checked) => setWarningEnabled(checked)} />
        </Form.Item>

        <Form.Item name="warning_threshold_pct" hidden>
          <InputNumber />
        </Form.Item>
        <Form.Item name="critical_threshold_pct" hidden>
          <InputNumber />
        </Form.Item>

        <Form.Item
          label={t("quota.thresholdSettings", "Alert Thresholds")}
          help={t(
            "quota.thresholdRangeHelp",
            "Drag the two handles to set warning and critical thresholds."
          )}
        >
          <div
            style={{ position: "relative", padding: "11px 5px 0" }}
            onMouseDownCapture={(event) =>
              setActiveThresholdHandle(event.target)
            }
            onTouchStartCapture={(event) =>
              setActiveThresholdHandle(event.target)
            }
            onFocusCapture={(event) => setActiveThresholdHandle(event.target)}
          >
            <div
              aria-hidden
              style={{
                position: "absolute",
                top: 14,
                left: 5,
                right: 5,
                height: 6,
                overflow: "hidden",
                borderRadius: 3,
                opacity: warningEnabled ? 1 : 0.45,
                pointerEvents: "none",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  inset: "0 auto 0 0",
                  width: `${warningPosition}%`,
                  background: THRESHOLD_TRACK_COLORS.normal,
                  transition: thresholdSegmentTransition,
                }}
              />
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: `${warningPosition}%`,
                  width: `${criticalPosition - warningPosition}%`,
                  background: THRESHOLD_TRACK_COLORS.warning,
                  borderLeft: "1px solid rgba(255, 255, 255, 0.7)",
                  transition: thresholdSegmentTransition,
                }}
              />
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: `${criticalPosition}%`,
                  width: `${100 - criticalPosition}%`,
                  background: THRESHOLD_TRACK_COLORS.critical,
                  borderLeft: "1px solid rgba(255, 255, 255, 0.7)",
                  transition: thresholdSegmentTransition,
                }}
              />
            </div>
            <Slider
              {...PUSHABLE_THRESHOLD_SLIDER_PROPS}
              range
              min={MIN_WARNING_THRESHOLD}
              max={MAX_CRITICAL_THRESHOLD}
              step={1}
              value={thresholds}
              onChange={handleThresholdChange}
              onChangeComplete={() => setActiveThresholdIndex(null)}
              disabled={!warningEnabled}
              style={{
                position: "relative",
                zIndex: 1,
                marginBlockStart: 0,
                marginInline: 0,
              }}
              railStyle={{ background: "transparent" }}
              trackStyle={[{ background: "transparent" }]}
              handleStyle={[
                { zIndex: activeThresholdIndex === 0 ? 3 : 2 },
                { zIndex: activeThresholdIndex === 1 ? 3 : 2 },
              ]}
              marks={{ 50: "50%", 80: "80%", 90: "90%", 99: "99%" }}
              tooltip={{
                formatter: (v?: number) => (v != null ? `${v}%` : ""),
              }}
            />
          </div>
          <Space size={16} style={{ marginTop: 8 }}>
            <Text style={{ color: "#faad14" }}>
              {t("quota.warningThreshold", "Warning Threshold")}:{" "}
              {thresholds[0]}%
            </Text>
            <Text style={{ color: "#ff4d4f" }}>
              {t("quota.criticalThreshold", "Critical Threshold")}:{" "}
              {thresholds[1]}%
            </Text>
          </Space>
        </Form.Item>
      </Form>

      <Divider />

      {/* Tenant Usage Overview */}
      {usageData && (
        <div style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: "100%" }}>
            <Text strong>
              {t("quota.tenantUsage", "Tenant Usage")}:{" "}
              {usageData.total_readable || "0 B"}
              {usageData.hard_limit_readable
                ? ` / ${usageData.hard_limit_readable}`
                : ""}
            </Text>
            <Progress
              percent={usageData.usage_pct ?? 0}
              size="small"
              strokeColor={getProgressColor(usageData.usage_pct)}
            />
            {getWarningTag(usageData.tenant_warning_level)}
          </Space>
        </div>
      )}

      {/* Fair Share Reference */}
      {fairShareGb && (
        <Row style={{ marginBottom: 12 }}>
          <Col>
            <Text type="secondary">
              <InfoCircleOutlined style={{ marginRight: 4 }} />
              {t("quota.fairShare", "Fair Share Reference")}: {hardLimitGb} GB
              &divide; {kbCount} KBs = {fairShareGb} GB/KB
            </Text>
          </Col>
        </Row>
      )}

      {/* Per-KB Breakdown Table */}
      {usageData?.breakdown && usageData.breakdown.length > 0 && (
        <>
          <Title level={5}>
            {t("quota.perKbBreakdown", "Per-KB Breakdown")}
          </Title>
          <Table
            dataSource={usageData.breakdown}
            columns={breakdownColumns}
            rowKey="knowledge_id"
            size="small"
            pagination={false}
            style={{ marginBottom: 16 }}
          />
          <Text type="secondary">
            <InfoCircleOutlined style={{ marginRight: 4 }} />
            {t(
              "quota.editHint",
              "Set per-KB quotas in the KB list → action column → edit icon"
            )}
          </Text>
        </>
      )}

      {/* Quota Summary */}
      {usageData && (
        <div style={{ marginTop: 16 }}>
          <Text type="secondary">
            {t("quota.summary", "Summary")}: {usageData.kbs_with_quota ?? 0} KBs
            with quotas, {t("quota.totalAllocated", "allocated")}:{" "}
            {usageData.soft_allocated_readable || "0 B"},{" "}
            {t("quota.actual", "actual")}: {usageData.total_readable || "0 B"}
            {usageData.oversubscription_ratio != null &&
              usageData.oversubscription_ratio > 1 && (
                <Tooltip
                  title={t(
                    "quota.oversubscribed",
                    "Soft quotas exceed hard limit"
                  )}
                >
                  <WarningOutlined
                    style={{ color: "#faad14", marginLeft: 8 }}
                  />
                </Tooltip>
              )}
          </Text>
        </div>
      )}
    </Modal>
  );
}
