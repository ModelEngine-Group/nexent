// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { MonitoringDateScope, MonitoringPublication } from "./operations";

export type McpCatalogService =
  | { service_id: number; name: string; type: "container" | "remote" }
  | { service_id: null; name: string; type: "builtin" };

export interface McpMonitoringSelection extends MonitoringDateScope {
  groupIds: number[];
  serviceId: number | null;
  builtin: boolean;
  toolName: string | null;
}

export interface McpMonitoringSummary extends MonitoringPublication {
  data: { tool_count: number; request_count: number | null };
}

export interface McpMonitoringTrend extends MonitoringPublication {
  data: { statistic_date: string; request_count: number | null }[];
}

export type McpMonitoringQueryKey = readonly [
  "mcpMonitoring",
  string,
  string,
  McpMonitoringSelection | null,
];
