// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type {
  AgentExecutionMetrics,
  AgentMonitoringDay,
  AgentMonitoringSelection,
} from "@/types/agentMonitoring";
import type { OperationsResource } from "@/types/operations";
import type { MonitoringRange } from "./monitoringFilters";

export type AgentTrendMetric =
  "execution_count" | "success_rate" | "total_tokens";

export function agentMonitoringSelection(
  tenantId: string | null | undefined,
  range: MonitoringRange | null,
  group: string,
  agent?: Pick<OperationsResource, "tenant_id" | "id">
): AgentMonitoringSelection | null {
  if (tenantId === undefined || !range) return null;
  return {
    tenantId: agent?.tenant_id ?? tenantId,
    agentId: agent?.id ?? null,
    groupIds: group ? [Number(group)] : [],
    startDate: range[0],
    endDate: range[1],
  };
}

export function successSampleCount(metrics: AgentExecutionMetrics) {
  const { succeeded_count, failed_count } = metrics;
  return succeeded_count === null || failed_count === null
    ? null
    : succeeded_count + failed_count;
}

export function getAgentSuccessRate(metrics: AgentExecutionMetrics) {
  const samples = successSampleCount(metrics);
  return samples ? metrics.success_rate : null;
}

export function getAgentTrendValue(
  day: AgentMonitoringDay,
  metric: AgentTrendMetric
) {
  switch (metric) {
    case "total_tokens":
      return day.tokens.total_tokens?.value ?? null;
    case "success_rate":
      return getAgentSuccessRate(day);
    case "execution_count":
      return day.execution_count;
  }
}

export function formatAgentMetric(
  value: number | string | null,
  metric: AgentTrendMetric,
  language: string
): string {
  if (value === null) return "—";
  if (typeof value === "string") {
    return new Intl.NumberFormat(language).format(BigInt(value));
  }
  if (metric === "success_rate") {
    return new Intl.NumberFormat(language, {
      style: "percent",
      maximumFractionDigits: 2,
    }).format(value);
  }
  return new Intl.NumberFormat(language).format(value);
}
