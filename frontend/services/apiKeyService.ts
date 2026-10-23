import { fetchWithAuth } from "@/lib/auth";
import { API_ENDPOINTS, ApiError } from "./api";

export interface TenantApiKey {
  token_id: number;
  access_key: string;
  user_id: string;
  created_by?: string | null;
  creator_email?: string | null;
  owner_email?: string | null;
  owner_role?: string | null;
  create_time?: string | null;
  last_used_time?: string | null;
  total_usage_count: number;
}

export interface ApiKeyMutationResult {
  user_id: string;
  email?: string | null;
  api_key?: string | null;
  revoked_count: number;
}

export async function listTenantApiKeys(
  tenantId: string,
  page: number,
  pageSize: number
): Promise<{ items: TenantApiKey[]; total: number }> {
  try {
    const params = new URLSearchParams({
      tenant_id: tenantId,
      page: String(page),
      page_size: String(pageSize),
      sort_order: "desc",
    });
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.apiKeys.list}?${params}`
    );
    const result = await response.json();
    return result.data ?? { items: [], total: 0 };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(500, "Failed to fetch API keys");
  }
}

export async function refreshTenantApiKey(
  userId: string
): Promise<ApiKeyMutationResult> {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.apiKeys.refresh, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
    const result = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(500, "Failed to refresh API key");
  }
}

export async function revokeTenantApiKeys(
  userId: string
): Promise<ApiKeyMutationResult> {
  try {
    const params = new URLSearchParams({ user_id: userId });
    const response = await fetchWithAuth(
      `${API_ENDPOINTS.apiKeys.revoke}?${params}`,
      {
        method: "DELETE",
      }
    );
    const result = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(500, "Failed to revoke API key");
  }
}
