// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type {
  ModelListRequest,
  ModelMonitoringList,
  ModelMonitoringSelection,
  ModelMonitoringSummary,
  ModelMonitoringTrends,
} from "@/types/modelMonitoring";
import type { MonitoringDateScope } from "@/types/operations";

type ModelMetricScope = MonitoringDateScope &
  Partial<Pick<ModelMonitoringSelection, "modelId" | "groupIds">>;

function modelMonitoringParams(scope: ModelMetricScope) {
  const params = new URLSearchParams({
    start_date: scope.startDate,
    end_date: scope.endDate,
  });
  if (scope.tenantId !== null) params.set("tenant_id", scope.tenantId);
  if (scope.modelId != null) params.set("model_id", String(scope.modelId));
  for (const id of scope.groupIds ?? []) params.append("group_ids", String(id));
  return params;
}

async function readModelMonitoring<T>(
  endpoint: string,
  params: URLSearchParams,
  signal: AbortSignal
): Promise<T> {
  const response = await fetchWithAuth(`${endpoint}?${params}`, { signal });
  return response.json();
}

export function getModelMonitoringTrends(
  scope: ModelMetricScope,
  signal: AbortSignal
) {
  return readModelMonitoring<ModelMonitoringTrends>(
    API_ENDPOINTS.operations.modelMonitoringTrends,
    modelMonitoringParams(scope),
    signal
  );
}

export function getModelMonitoringSummary(
  scope: ModelMonitoringSelection,
  signal: AbortSignal
) {
  return readModelMonitoring<ModelMonitoringSummary>(
    API_ENDPOINTS.operations.modelMonitoringSummary,
    modelMonitoringParams(scope),
    signal
  );
}

export async function getModelMonitoringList(
  scope: ModelMonitoringSelection,
  list: ModelListRequest,
  signal: AbortSignal
): Promise<ModelMonitoringList> {
  const params = modelMonitoringParams(scope);
  params.set("page", String(list.page));
  params.set("page_size", String(list.pageSize));
  if (list.search) params.set("search", list.search);
  return readModelMonitoring<ModelMonitoringList>(
    API_ENDPOINTS.operations.modelMonitoringList,
    params,
    signal
  );
}
