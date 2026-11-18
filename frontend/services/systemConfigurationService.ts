// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { getAuthHeaders } from "@/lib/auth";
import type {
  SystemConfigurationChanges,
  SystemConfigurationListResponse,
  SystemConfigurationSaveResponse,
} from "@/types/systemConfiguration";
import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";

export async function listSystemConfigurations(
  signal?: AbortSignal
): Promise<SystemConfigurationListResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.systemConfigurations,
    {
      headers: getAuthHeaders(),
      signal,
    }
  );
  return response.json();
}

export async function saveSystemConfigurations(
  changes: SystemConfigurationChanges,
  signal?: AbortSignal
): Promise<SystemConfigurationSaveResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.systemConfigurations,
    {
      method: "PATCH",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ changes }),
      signal,
    }
  );
  return response.json();
}
