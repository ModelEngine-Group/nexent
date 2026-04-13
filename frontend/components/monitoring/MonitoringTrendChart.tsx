"use client";

import React, { useMemo } from "react";
import { Card, Segmented, Select, Spin, Empty } from "antd";
import { useTranslation } from "react-i18next";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";
import type { TrendPoint, ModelMonitoringItem } from "@/types/monitoring";

interface MonitoringTrendChartProps {
  trend: TrendPoint[];
  models: ModelMonitoringItem[];
  loading: boolean;
  selectedModelId?: string;
  onModelChange: (modelId: string | undefined) => void;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:00`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:00`;
}

export default function MonitoringTrendChart({
  trend,
  models,
  loading,
  selectedModelId,
  onModelChange,
}: MonitoringTrendChartProps) {
  const { t } = useTranslation("common");

  const [metric, setMetric] = React.useState<"requests" | "error_rate" | "failure_rate" | "duration" | "cost">("requests");

  const metricConfig = useMemo(() => ({
    requests: {
      key: "request_count",
      label: t("monitoring.table.requests"),
      color: "#1890ff",
      unit: "",
    },
    error_rate: {
      key: "error_rate",
      label: t("monitoring.table.errorRate"),
      color: "#faad14",
      unit: "%",
    },
    failure_rate: {
      key: "failure_rate",
      label: t("monitoring.table.failureRate"),
      color: "#ff4d4f",
      unit: "%",
    },
    duration: {
      key: "avg_duration",
      label: t("monitoring.table.avgDuration"),
      color: "#722ed1",
      unit: ` ${t("monitoring.time.ms")}`,
    },
    cost: {
      key: "cost",
      label: t("monitoring.table.cost"),
      color: "#13c2c2",
      unit: " USD",
    },
  }), [t]);

  const chartData = useMemo(() => {
    if (!trend.length) return [];
    const isFirstDay = trend.length <= 25;
    return trend.map((p) => ({
      name: isFirstDay ? formatTime(p.timestamp) : formatDate(p.timestamp),
      [metricConfig[metric].key]: p[metricConfig[metric].key as keyof TrendPoint] as number,
    }));
  }, [trend, metric, metricConfig]);

  const cfg = metricConfig[metric];

  const metricOptions = [
    { label: t("monitoring.table.requests"), value: "requests" },
    { label: t("monitoring.table.errorRate"), value: "error_rate" },
    { label: t("monitoring.table.failureRate"), value: "failure_rate" },
    { label: t("monitoring.table.avgDuration"), value: "duration" },
    { label: t("monitoring.table.cost"), value: "cost" },
  ];

  const modelOptions = [
    { label: t("monitoring.dashboard.models"), value: "" },
    ...models.map((m) => ({
      label: m.display_name,
      value: m.model_id,
    })),
  ];

  return (
    <Card
      size="small"
      bordered={false}
      className="shadow-sm"
      styles={{ body: { padding: "12px 16px" } }}
    >
      <div className="flex items-center justify-between mb-3">
        <Segmented
          options={metricOptions}
          value={metric}
          onChange={(v) => setMetric(v as typeof metric)}
          size="small"
        />
        <Select
          value={selectedModelId || ""}
          onChange={(v) => onModelChange(v || undefined)}
          size="small"
          style={{ width: 180 }}
          options={modelOptions}
          allowClear
          placeholder={t("monitoring.dashboard.models")}
        />
      </div>

      <Spin spinning={loading}>
        {chartData.length === 0 && !loading ? (
          <Empty description="No trend data" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id={`gradient-${cfg.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={cfg.color} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={cfg.color} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 11, fill: "#8c8c8c" }}
                interval={Math.max(0, Math.floor(chartData.length / 8))}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#8c8c8c" }}
                width={60}
              />
              <Tooltip
                formatter={(value: number) => [`${value}${cfg.unit}`, cfg.label]}
                contentStyle={{ fontSize: 12, borderRadius: 6 }}
              />
              <Area
                type="monotone"
                dataKey={cfg.key}
                stroke={cfg.color}
                strokeWidth={2}
                fill={`url(#gradient-${cfg.key})`}
                dot={chartData.length <= 30 ? { r: 2, fill: cfg.color } : false}
                activeDot={{ r: 4, stroke: cfg.color, strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </Spin>
    </Card>
  );
}
