// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type {
  McpCatalogService,
  McpMonitoringSelection,
  McpMonitoringSummary,
  McpMonitoringTrend,
} from "@/types/mcpMonitoring";

export async function getMcpMonitoringCatalog(
  tenantId: string | null,
  signal: AbortSignal
): Promise<McpCatalogService[]> {
  const endpoint = API_ENDPOINTS.operations.mcpMonitoringCatalog;
  const url = tenantId
    ? `${endpoint}?${new URLSearchParams({ tenant_id: tenantId })}`
    : endpoint;
  const response = await fetchWithAuth(url, { signal });
  return (await response.json()).data;
}

async function readMcpMonitoring<T>(
  endpoint: string,
  scope: McpMonitoringSelection,
  signal: AbortSignal
): Promise<T> {
  const params = new URLSearchParams({
    start_date: scope.startDate,
    end_date: scope.endDate,
  });
  if (scope.tenantId) params.set("tenant_id", scope.tenantId);
  for (const id of scope.groupIds) params.append("group_ids", String(id));
  if (scope.serviceId !== null)
    params.set("server_id", String(scope.serviceId));
  if (scope.builtin) params.set("server_type", "builtin");
  if (scope.toolName) params.set("tool_name", scope.toolName);
  const response = await fetchWithAuth(`${endpoint}?${params}`, { signal });
  return response.json();
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
