// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { API_ENDPOINTS } from "@/services/api";
import { fetchWithAuth } from "@/lib/auth";
import type {
  OperationsAuthorization,
  OperationsResource,
  OperationsResourcePage,
} from "@/types/operations";

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

export async function listOperationsResources(
  tenantId: string | null,
  signal?: AbortSignal
): Promise<OperationsResource[]> {
  const pageSize = 100;
  const params = new URLSearchParams({ page_size: String(pageSize) });
  if (tenantId) params.set("tenant_id", tenantId);
  const resources: OperationsResource[] = [];
  let pageCount = 1;

  for (let page = 1; page <= pageCount; page += 1) {
    params.set("page", String(page));
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.operations.resources}?${params}`,
      { signal }
    );
    const { data }: { data: OperationsResourcePage } = await response.json();
    if (page === 1) pageCount = Math.ceil(data.total / pageSize);
    if (!data.items.length) break;
    resources.push(...data.items);
  }
  return resources;
}

export async function listOperationsMcpTools(
  serviceId: number,
  signal?: AbortSignal
): Promise<{ name: string }[]> {
  const params = new URLSearchParams({ mcp_id: String(serviceId) });
  const response = await fetchWithAuth(`${API_ENDPOINTS.mcp.tools}?${params}`, {
    signal,
  });
  const { tools }: { tools: { name: string }[] } = await response.json();
  return tools;
}
