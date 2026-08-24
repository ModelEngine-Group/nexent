"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Card, Table, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { monitoringService } from "@/services/monitoringService";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

export default function ContextBudgetOperationsWidget({
  timeRange,
}: {
  timeRange: string;
}) {
  const { t } = useTranslation("common");
  const { data = [], isLoading } = useQuery({
    queryKey: ["contextBudgetMonitoring", timeRange],
    queryFn: () => monitoringService.fetchContextBudget(timeRange),
    staleTime: 30_000,
  });
  if (!isLoading && data.length === 0) return null;
  return (
    <Card
      size="small"
      className="mb-3"
      title={t("monitoring.contextBudget.title")}
      extra={<Tag>{timeRange}</Tag>}
    >
      <Table
        size="small"
        loading={isLoading}
        pagination={false}
        rowKey={(row) =>
          `${row.provider_protocol}:${row.model_name}:${row.capability_profile_version}`
        }
        dataSource={data}
        columns={[
          {
            title: t("monitoring.contextBudget.model"),
            render: (_value, row) => (
              <span>
                {row.provider_protocol} / {row.model_name}
                <br />
                <span className="text-xs text-gray-500">
                  {row.capability_profile_version}
                </span>
              </span>
            ),
          },
          {
            title: t("monitoring.contextBudget.requests"),
            dataIndex: "request_count",
          },
          {
            title: t("monitoring.contextBudget.overflow"),
            dataIndex: "overflow_rate",
            render: percent,
          },
          {
            title: t("monitoring.contextBudget.compaction"),
            dataIndex: "compaction_incidence",
            render: percent,
          },
          {
            title: t("monitoring.contextBudget.reduction"),
            dataIndex: "avg_compression_ratio",
            render: percent,
          },
          {
            title: t("monitoring.contextBudget.estimateError"),
            dataIndex: "mean_absolute_estimate_error",
            render: percent,
          },
          {
            title: t("monitoring.contextBudget.recovery"),
            dataIndex: "recovery_success_rate",
            render: percent,
          },
        ]}
      />
    </Card>
  );
}
