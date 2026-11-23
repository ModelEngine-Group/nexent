// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type {
  AgentListRequest,
  AgentMonitoringList,
  AgentMonitoringMetric,
  AgentMonitoringRankings,
  AgentMonitoringSelection,
  AgentMonitoringSummary,
  AgentMonitoringTrends,
} from "@/types/agentMonitoring";

async function readAgentMonitoring<T>(
  endpoint: string,
  selection: AgentMonitoringSelection,
  signal: AbortSignal,
  options?: Record<string, string>
): Promise<T> {
  const params = new URLSearchParams({
    start_date: selection.startDate,
    end_date: selection.endDate,
    ...options,
  });
  if (selection.tenantId !== null) params.set("tenant_id", selection.tenantId);
  if (selection.agentId !== null)
    params.set("agent_id", String(selection.agentId));
  for (const groupId of selection.groupIds)
    params.append("group_ids", String(groupId));
  const response = await fetchWithAuth(`${endpoint}?${params}`, { signal });
  return response.json();
}

export function getAgentMonitoringList(
  selection: AgentMonitoringSelection,
  list: AgentListRequest,
  signal: AbortSignal
) {
  return readAgentMonitoring<AgentMonitoringList>(
    API_ENDPOINTS.operations.agentMonitoringList,
    selection,
    signal,
    {
      page: String(list.page),
      page_size: String(list.pageSize),
      sort_by: list.sortBy,
      descending: String(list.descending),
      ...(list.search ? { search: list.search } : {}),
    }
  );
}

export function getAgentMonitoringSummary(
  selection: AgentMonitoringSelection,
  signal: AbortSignal
) {
  return readAgentMonitoring<AgentMonitoringSummary>(
    API_ENDPOINTS.operations.agentMonitoringSummary,
    selection,
    signal
  );
}

export function getAgentMonitoringTrends(
  selection: AgentMonitoringSelection,
  signal: AbortSignal
) {
  return readAgentMonitoring<AgentMonitoringTrends>(
    API_ENDPOINTS.operations.agentMonitoringTrends,
    selection,
    signal
  );
}

export function getAgentMonitoringRankings(
  selection: AgentMonitoringSelection,
  metric: AgentMonitoringMetric,
  signal: AbortSignal
) {
  return readAgentMonitoring<AgentMonitoringRankings>(
    API_ENDPOINTS.operations.agentMonitoringRankings,
    selection,
    signal,
    { metric }
  );
}
