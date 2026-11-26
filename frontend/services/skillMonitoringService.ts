// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type {
  SkillMonitoringPage,
  SkillMonitoringRankings,
  SkillMonitoringSelection,
  SkillMonitoringSummary,
  SkillMonitoringTrend,
} from "@/types/skillMonitoring";

async function readSkillMonitoring<T>(
  endpoint: string,
  scope: SkillMonitoringSelection,
  signal: AbortSignal,
  options?: Record<string, string>
): Promise<T> {
  const params = new URLSearchParams({
    start_date: scope.startDate,
    end_date: scope.endDate,
    ...options,
  });
  if (scope.tenantId !== null) params.set("tenant_id", scope.tenantId);
  if (scope.skillId !== null) params.set("skill_id", scope.skillId);
  for (const id of scope.groupIds) params.append("group_ids", String(id));
  const response = await fetchWithAuth(`${endpoint}?${params}`, { signal });
  return response.json();
}

export function getSkillMonitoringSummary(
  scope: SkillMonitoringSelection,
  signal: AbortSignal
) {
  return readSkillMonitoring<SkillMonitoringSummary>(
    API_ENDPOINTS.operations.skillMonitoringSummary,
    scope,
    signal
  );
}

export function getSkillMonitoringTrends(
  scope: SkillMonitoringSelection,
  signal: AbortSignal
) {
  return readSkillMonitoring<SkillMonitoringTrend>(
    API_ENDPOINTS.operations.skillMonitoringTrends,
    scope,
    signal
  );
}

export function getSkillMonitoringList(
  scope: SkillMonitoringSelection,
  options: {
    page: number;
    pageSize: number;
    search: string;
    descending: boolean;
  },
  signal: AbortSignal
) {
  return readSkillMonitoring<SkillMonitoringPage>(
    API_ENDPOINTS.operations.skillMonitoringList,
    scope,
    signal,
    {
      page: String(options.page),
      page_size: String(options.pageSize),
      search: options.search,
      descending: String(options.descending),
    }
  );
}

export function getSkillMonitoringRankings(
  scope: SkillMonitoringSelection,
  signal: AbortSignal
) {
  return readSkillMonitoring<SkillMonitoringRankings>(
    API_ENDPOINTS.operations.skillMonitoringRankings,
    scope,
    signal
  );
}
