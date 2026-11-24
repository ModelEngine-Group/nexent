// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Activity, Layers } from "lucide-react";
import { useTranslation } from "react-i18next";
import { UnavailableMonitoring } from "../shared/UnavailableMonitoring";

export function McpMonitoring({
  scope,
}: {
  scope: "all" | "service" | "tool";
}) {
  const { t } = useTranslation("common");
  const allServices = scope === "all";
  const singleTool = scope === "tool";
  const calls = t("ops.monitoring.mcp.calls");
  return (
    <UnavailableMonitoring
      summaryLabel={t("ops.monitoring.mcp.summary")}
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
              },
            ]
          : []),
        { title: calls, Icon: Activity },
      ]}
      trendTitle={t("ops.monitoring.mcp.trend")}
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
