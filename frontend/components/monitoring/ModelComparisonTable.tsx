"use client";

import React from "react";
import { Table, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import type { ModelMonitoringItem } from "@/types/monitoring";

interface ModelComparisonTableProps {
  models: ModelMonitoringItem[];
  loading: boolean;
  onModelClick?: (model: ModelMonitoringItem) => void;
}

export default function ModelComparisonTable({ models, loading, onModelClick }: ModelComparisonTableProps) {
  const { t } = useTranslation("common");

  const getFailureRateColor = (rate: number) => {
    if (rate < 0.5) return "#52c41a";
    if (rate < 1) return "#faad14";
    return "#ff4d4f";
  };

  const getErrorRateColor = (rate: number) => {
    if (rate < 1.5) return "#52c41a";
    if (rate < 3) return "#faad14";
    return "#ff4d4f";
  };

  const columns = [
    {
      title: t("monitoring.table.modelName"),
      dataIndex: "display_name",
      key: "display_name",
      render: (name: string, record: ModelMonitoringItem) => (
        <a
          className="text-blue-600 hover:text-blue-800 cursor-pointer font-medium"
          onClick={() => onModelClick?.(record)}
        >
          {name}
        </a>
      ),
    },
    {
      title: t("monitoring.table.requests"),
      dataIndex: "request_count",
      key: "request_count",
      sorter: (a: ModelMonitoringItem, b: ModelMonitoringItem) => a.request_count - b.request_count,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: t("monitoring.table.errorRate"),
      dataIndex: "error_rate",
      key: "error_rate",
      sorter: (a: ModelMonitoringItem, b: ModelMonitoringItem) => a.error_rate - b.error_rate,
      render: (v: number) => (
        <Tag color={getErrorRateColor(v)}>{v.toFixed(2)}%</Tag>
      ),
    },
    {
      title: t("monitoring.table.failureRate"),
      dataIndex: "failure_rate",
      key: "failure_rate",
      sorter: (a: ModelMonitoringItem, b: ModelMonitoringItem) => a.failure_rate - b.failure_rate,
      render: (v: number) => (
        <Tag color={getFailureRateColor(v)}>{v.toFixed(2)}%</Tag>
      ),
    },
    {
      title: t("monitoring.table.avgDuration"),
      dataIndex: "avg_duration",
      key: "avg_duration",
      sorter: (a: ModelMonitoringItem, b: ModelMonitoringItem) => a.avg_duration - b.avg_duration,
      render: (v: number) => `${v.toFixed(0)} ${t("monitoring.time.ms")}`,
    },
    {
      title: t("monitoring.table.avgTTFT"),
      dataIndex: "avg_ttft",
      key: "avg_ttft",
      render: (v: number) => `${v.toFixed(0)} ${t("monitoring.time.ms")}`,
    },
    {
      title: t("monitoring.table.tokens"),
      dataIndex: "total_tokens",
      key: "total_tokens",
      sorter: (a: ModelMonitoringItem, b: ModelMonitoringItem) => a.total_tokens - b.total_tokens,
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: t("monitoring.table.cost"),
      dataIndex: "total_cost",
      key: "total_cost",
      sorter: (a: ModelMonitoringItem, b: ModelMonitoringItem) => a.total_cost - b.total_cost,
      render: (v: number) => `$${v.toFixed(2)}`,
    },
    {
      title: t("monitoring.table.quality"),
      dataIndex: "quality_score",
      key: "quality_score",
      sorter: (a: ModelMonitoringItem, b: ModelMonitoringItem) => a.quality_score - b.quality_score,
      render: (v: number) => (
        <Tooltip title={`${v}/100`}>
          <div className="flex items-center gap-1">
            <div
              className="h-1.5 rounded-full"
              style={{
                width: "60px",
                backgroundColor: "#f0f0f0",
              }}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${v}%`,
                  backgroundColor: v >= 90 ? "#52c41a" : v >= 75 ? "#faad14" : "#ff4d4f",
                }}
              />
            </div>
            <span className="text-xs text-slate-500">{v.toFixed(0)}</span>
          </div>
        </Tooltip>
      ),
    },
  ];

  return (
    <Table
      dataSource={models}
      columns={columns}
      rowKey="model_id"
      loading={loading}
      pagination={false}
      size="middle"
      className="mt-4"
    />
  );
}
