// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery } from "@tanstack/react-query";
import { Alert } from "antd";
import { Activity, Layers } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  getMcpMonitoringSummary,
  getMcpMonitoringTrends,
} from "@/services/mcpMonitoringService";
import type { McpMonitoringQueryKey } from "@/types/mcpMonitoring";
import { OverviewTrend } from "../overview/OverviewTrend";
import { UnavailableMonitoring } from "../shared/UnavailableMonitoring";

export function McpMonitoring({
  scope,
  queryKey,
  registeredServices,
  scopeLoading,
  hasRange,
}: {
  scope: "all" | "service" | "tool";
  queryKey: McpMonitoringQueryKey;
  registeredServices: { count: number | null; loading: boolean };
  scopeLoading: boolean;
  hasRange: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  const allServices = scope === "all";
  const singleTool = scope === "tool";
  const calls = t("ops.monitoring.mcp.calls");
  const trendTitle = t("ops.monitoring.mcp.trend");
  const selection = queryKey[3];
  const summary = useQuery({
    queryKey: [...queryKey, "summary"],
    queryFn: ({ signal }) => getMcpMonitoringSummary(selection!, signal),
    enabled: selection !== null,
  });
  const trends = useQuery({
    queryKey: [...queryKey, "trends"],
    queryFn: ({ signal }) => getMcpMonitoringTrends(selection!, signal),
    enabled: selection !== null,
  });
  const summaryLoading =
    scopeLoading || (selection !== null && summary.isPending);
  const published =
    !summary.isError && summary.data?.coverage_state !== "uncovered"
      ? summary.data?.data
      : undefined;
  const points = trends.data?.data.map((day) => ({
    date: day.statistic_date,
    value: day.request_count,
  }));
  const number = new Intl.NumberFormat(i18n.language);
  const format = (value: number | null, loading: boolean) =>
    loading ? t("common.loading") : value === null ? "—" : number.format(value);
  return (
    <UnavailableMonitoring
      summaryLabel={t("ops.monitoring.mcp.summary")}
      summaryBusy={
        summaryLoading || summary.isFetching || registeredServices.loading
      }
      summaryNotice={
        summary.isError && (
          <Alert type="error" title={t("ops.loadError")} showIcon />
        )
      }
      cards={[
        ...(!singleTool
          ? [
              {
                title: t(
                  allServices
                    ? "ops.monitoring.mcp.currentServices"
                    : "ops.monitoring.mcp.currentTools"
                ),
                Icon: Layers,
                value: allServices
                  ? format(registeredServices.count, registeredServices.loading)
                  : format(published?.tool_count ?? null, summaryLoading),
              },
            ]
          : []),
        {
          title: calls,
          Icon: Activity,
          value: format(published?.request_count ?? null, summaryLoading),
          unit:
            published?.request_count != null && !summaryLoading
              ? t("ops.monitoring.mcp.callUnit")
              : undefined,
        },
      ]}
      trendTitle={trendTitle}
      trendPanel={
        <OverviewTrend
          title={trendTitle}
          description={t("ops.monitoring.agent.daily")}
          emptyDescription={
            trends.data?.coverage_state === "uncovered" ||
            (points?.length && points.every(({ value }) => value === null))
              ? "—"
              : undefined
          }
          trend={{
            points,
            publication: trends.data,
            loading:
              scopeLoading ||
              (selection !== null && (trends.isPending || trends.isFetching)),
            failed: trends.isError,
            hasRange,
          }}
        />
      }
      rankingTitle={
        singleTool
          ? undefined
          : t(
              allServices
                ? "ops.monitoring.mcp.serviceTop"
                : "ops.monitoring.mcp.toolTop"
            )
      }
      details={{
        title: t(
          allServices
            ? "ops.monitoring.mcp.serviceDetails"
            : "ops.monitoring.mcp.toolDetails"
        ),
        nameLabel: t(
          allServices
            ? "ops.monitoring.mcp.serviceName"
            : "ops.monitoring.mcp.toolName"
        ),
        searchLabel: t(
          allServices
            ? "ops.monitoring.mcp.searchServices"
            : "ops.monitoring.mcp.searchTools"
        ),
        columns: [
          ...(allServices
            ? [
                { title: t("common.source"), key: "source" },
                {
                  title: t("ops.monitoring.mcp.activeTools"),
                  key: "active_tools",
                },
              ]
            : []),
          { title: calls, key: "calls" },
          { title: t("ops.monitoring.mcp.latency"), key: "latency" },
          ...(!singleTool
            ? [{ title: t("common.actions"), key: "actions" }]
            : []),
        ],
      }}
    />
  );
}
