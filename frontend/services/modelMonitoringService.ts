// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS } from "@/services/api";
import type { ModelMonitoringTrends } from "@/types/modelMonitoring";
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
