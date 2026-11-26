// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { getAuthHeaders } from "@/lib/auth";
import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";

import type { DenylistScope, DenylistState } from "@/types/resourceDenylist";
export type {
  DenylistItem,
  DenylistScope,
  DenylistState,
} from "@/types/resourceDenylist";

export async function loadResourceDenylist(
  scope: DenylistScope,
  signal?: AbortSignal
): Promise<DenylistState> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.resourceDenylist[scope],
    { headers: getAuthHeaders(), signal }
  );
  return response.json();
}

export async function saveResourceDenylist(
  scope: DenylistScope,
  revision: string,
  selected: string[]
): Promise<DenylistState> {
  const selection =
    scope === "global"
      ? {
          tool_names: selected.filter(
            (key) => !key.startsWith("mcp:") && !key.startsWith("skill:")
          ),
          resource_refs: selected.filter(
            (key) => key.startsWith("mcp:") || key.startsWith("skill:")
          ),
        }
      : { resource_refs: selected };
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.resourceDenylist[scope],
    {
      method: "PUT",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ revision, ...selection }),
    }
  );
  return response.json();
}
