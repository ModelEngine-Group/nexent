// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { MonitoringDateScope, MonitoringPublication } from "./operations";

export type McpCatalogService =
  | { service_id: number; name: string; type: "container" | "remote" }
  | { service_id: null; name: string; type: "builtin" };

export type McpServerType =
  "container" | "remote" | "api_convert" | "builtin" | "unknown";

export interface McpServiceFilter {
  service_id: number | null;
  name: string;
  type: McpServerType | null;
}

export interface McpMonitoringSelection extends MonitoringDateScope {
  groupIds: number[];
  serviceId: number | null;
  serverType: McpServerType | null;
  toolName: string | null;
}

export interface McpMonitoringSummary extends MonitoringPublication {
  data: { tool_count: number; request_count: number | null };
}

interface McpDailyCalls {
  statistic_date: string;
  request_count: number | null;
}

export interface McpMonitoringTrend extends MonitoringPublication {
  data: McpDailyCalls[];
}

export interface McpMonitoringOverview extends MonitoringPublication {
  data: { calls_trend: McpDailyCalls[] };
}

export type McpMonitoringDimension = "services" | "tools";
export type McpMonitoringSort = "name" | "request_count" | "avg_duration_ms";

export interface McpMonitoringRow {
  tenant_id: string;
  mcp_server_id: number | null;
  mcp_server_name: string | null;
  mcp_server_type: McpServerType | null;
  tool_name?: string;
  active_tools?: number;
  metrics: {
    request_count: number | null;
    avg_duration_ms: number | null;
  };
}

export interface McpMonitoringListOptions {
  page: number;
  pageSize: number;
  search: string;
  sortBy: McpMonitoringSort;
  descending: boolean;
}

export interface McpMonitoringPage extends MonitoringPublication {
  data: { items: McpMonitoringRow[]; total: number };
}

export interface McpMonitoringRankings extends MonitoringPublication {
  data: McpMonitoringRow[];
}

export type McpMonitoringQueryKey = readonly [
  "mcpMonitoring",
  string,
  string,
  McpMonitoringSelection | null,
];
