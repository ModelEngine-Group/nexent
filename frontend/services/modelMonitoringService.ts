// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type {
  ModelListRequest,
  ModelMonitoringList,
  ModelMonitoringSelection,
  ModelMonitoringTrends,
} from "@/types/modelMonitoring";
import type { MonitoringDateScope } from "@/types/operations";

export async function getModelMonitoringTrends(
  scope: MonitoringDateScope,
  signal: AbortSignal
): Promise<ModelMonitoringTrends> {
  const params = new URLSearchParams({
    start_date: scope.startDate,
    end_date: scope.endDate,
  });
  if (scope.tenantId !== null) params.set("tenant_id", scope.tenantId);
  const response = await fetchWithAuth(
    `${API_ENDPOINTS.operations.modelMonitoringTrends}?${params}`,
    { signal }
  );
  return response.json();
}

export async function getModelMonitoringList(
  scope: ModelMonitoringSelection,
  list: ModelListRequest,
  signal: AbortSignal
): Promise<ModelMonitoringList> {
  const params = new URLSearchParams({
    start_date: scope.startDate,
    end_date: scope.endDate,
    page: String(list.page),
    page_size: String(list.pageSize),
  });
  if (scope.tenantId !== null) params.set("tenant_id", scope.tenantId);
  if (scope.modelId !== null) params.set("model_id", String(scope.modelId));
  for (const id of scope.groupIds) params.append("group_ids", String(id));
  if (list.search) params.set("search", list.search);
  const response = await fetchWithAuth(
    `${API_ENDPOINTS.operations.modelMonitoringList}?${params}`,
    { signal }
  );
  return response.json();
}
