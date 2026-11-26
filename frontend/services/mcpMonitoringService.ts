// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type {
  McpCatalogService,
  McpMonitoringDimension,
  McpMonitoringListOptions,
  McpMonitoringOverview,
  McpMonitoringPage,
  McpMonitoringRankings,
  McpMonitoringSelection,
  McpMonitoringSummary,
  McpMonitoringTrend,
} from "@/types/mcpMonitoring";
import type { MonitoringDateScope } from "@/types/operations";

export async function getMcpMonitoringCatalog(
  tenantId: string | null,
  groupIds: number[],
  signal: AbortSignal
): Promise<McpCatalogService[]> {
  const endpoint = API_ENDPOINTS.operations.mcpMonitoringCatalog;
  const params = new URLSearchParams();
  if (tenantId) params.set("tenant_id", tenantId);
  for (const id of groupIds) params.append("group_ids", String(id));
  const url =
    tenantId || groupIds.length > 0 ? `${endpoint}?${params}` : endpoint;
  const response = await fetchWithAuth(url, { signal });
  return (await response.json()).data;
}

function dateParams(scope: MonitoringDateScope): URLSearchParams {
  const params = new URLSearchParams({
    start_date: scope.startDate,
    end_date: scope.endDate,
  });
  if (scope.tenantId) params.set("tenant_id", scope.tenantId);
  return params;
}

async function readMonitoring<T>(
  endpoint: string,
  params: URLSearchParams,
  signal: AbortSignal
): Promise<T> {
  const response = await fetchWithAuth(`${endpoint}?${params}`, { signal });
  return response.json();
}

function readMcpMonitoring<T>(
  endpoint: string,
  scope: McpMonitoringSelection,
  signal: AbortSignal,
  options?: Record<string, string>
): Promise<T> {
  const params = dateParams(scope);
  if (scope.resourceGroup) params.set("resource_group", scope.resourceGroup);
  for (const id of scope.groupIds) params.append("group_ids", String(id));
  if (scope.serviceId !== null)
    params.set("server_id", String(scope.serviceId));
  if (scope.serverType) params.set("server_type", scope.serverType);
  if (scope.toolName) params.set("tool_name", scope.toolName);
  for (const [key, value] of Object.entries(options ?? {}))
    params.set(key, value);
  return readMonitoring<T>(endpoint, params, signal);
}

export function getMcpMonitoringSummary(
  scope: McpMonitoringSelection,
  signal: AbortSignal
) {
  return readMcpMonitoring<McpMonitoringSummary>(
    API_ENDPOINTS.operations.mcpMonitoringSummary,
    scope,
    signal
  );
}

export function getMcpMonitoringTrends(
  scope: McpMonitoringSelection,
  signal: AbortSignal
) {
  return readMcpMonitoring<McpMonitoringTrend>(
    API_ENDPOINTS.operations.mcpMonitoringTrends,
    scope,
    signal
  );
}

export function getMcpMonitoringRankings(
  scope: McpMonitoringSelection,
  dimension: McpMonitoringDimension,
  signal: AbortSignal
) {
  return readMcpMonitoring<McpMonitoringRankings>(
    API_ENDPOINTS.operations.mcpMonitoringRankings,
    scope,
    signal,
    { dimension, metric: "request_count" }
  );
}

export function getMcpMonitoringList(
  scope: McpMonitoringSelection,
  dimension: McpMonitoringDimension,
  options: McpMonitoringListOptions,
  signal: AbortSignal
) {
  return readMcpMonitoring<McpMonitoringPage>(
    API_ENDPOINTS.operations.mcpMonitoringList,
    scope,
    signal,
    {
      dimension,
      page: String(options.page),
      page_size: String(options.pageSize),
      search: options.search,
      sort_by: options.sortBy,
      descending: String(options.descending),
    }
  );
}

export function getMcpMonitoringOverview(
  scope: MonitoringDateScope,
  signal: AbortSignal
) {
  return readMonitoring<McpMonitoringOverview>(
    API_ENDPOINTS.operations.mcpMonitoringOverview,
    dateParams(scope),
    signal
  );
}
