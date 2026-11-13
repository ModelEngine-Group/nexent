// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { API_ENDPOINTS } from "@/services/api";
import { fetchWithAuth } from "@/lib/auth";
import type { OperationsAuthorization } from "@/types/operations";

export async function getOperationsAuthorization(): Promise<OperationsAuthorization> {
  const response = await fetchWithAuth(API_ENDPOINTS.operations.authorization);
  return (await response.json()).data;
}
export async function checkOperationsScope(
  module: string,
  tenantId?: string
): Promise<{ tenant_id: string | null; scope: string }> {
  const params = new URLSearchParams({ module });
  if (tenantId) params.set("tenant_id", tenantId);
  const response = await fetchWithAuth(
    `${API_ENDPOINTS.operations.scope}?${params}`
  );
  return (await response.json()).data;
}
