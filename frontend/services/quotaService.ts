/**
 * Quota management API client.
 */
import { API_ENDPOINTS, ApiError } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import { emitQuotaUsageChanged } from "@/lib/quotaEvents";
import type {
  TenantQuotaConfig,
  QuotaUsageResponse,
  UpdateTenantQuotaPayload,
  PlatformQuotaOverview,
  UpdatePlatformCapacityPayload,
  UpdateTenantHardQuotaPayload,
} from "@/types/quota";

class QuotaService {
  // ── Tenant-Level Quota ──────────────────────────────────────────

  async getQuotaConfig(tenantId: string): Promise<TenantQuotaConfig> {
    const response = await fetch(API_ENDPOINTS.quota.config(tenantId), {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        response.status,
        data.message || "Failed to get quota config"
      );
    }
    return data;
  }

  async updateTenantQuota(
    tenantId: string,
    payload: UpdateTenantQuotaPayload
  ): Promise<TenantQuotaConfig> {
    const response = await fetch(API_ENDPOINTS.quota.config(tenantId), {
      method: "PUT",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        response.status,
        data.message || data.detail || "Failed to update quota"
      );
    }
    emitQuotaUsageChanged();
    return data;
  }

  async deleteTenantQuota(tenantId: string): Promise<void> {
    const response = await fetch(API_ENDPOINTS.quota.config(tenantId), {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        data.message || "Failed to delete quota"
      );
    }
    emitQuotaUsageChanged();
  }

  async getQuotaUsage(
    tenantId: string,
    forceRefresh?: boolean,
    detail?: boolean
  ): Promise<QuotaUsageResponse> {
    const params = new URLSearchParams();
    if (forceRefresh) params.set("force_refresh", "true");
    if (detail) params.set("detail", "true");

    const queryString = params.toString();
    const url =
      API_ENDPOINTS.quota.usage(tenantId) +
      (queryString ? `?${queryString}` : "");

    const response = await fetch(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        response.status,
        data.message || "Failed to get quota usage"
      );
    }
    return data;
  }

  // ── Platform-Level Quota (SU/ASSET_OWNER) ──────────────────────

  async getPlatformOverview(): Promise<PlatformQuotaOverview> {
    const response = await fetch(API_ENDPOINTS.quota.platformOverview, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        response.status,
        data.message || "Failed to get platform overview"
      );
    }
    return data;
  }

  async setPlatformCapacity(
    payload: UpdatePlatformCapacityPayload
  ): Promise<any> {
    const response = await fetch(API_ENDPOINTS.quota.platformCapacity, {
      method: "PUT",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        response.status,
        data.message || "Failed to set platform capacity"
      );
    }
    emitQuotaUsageChanged();
    return data;
  }

  async deletePlatformCapacity(): Promise<void> {
    const response = await fetch(API_ENDPOINTS.quota.platformCapacity, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        data.message || "Failed to delete platform capacity"
      );
    }
    emitQuotaUsageChanged();
  }

  async setTenantHardQuota(
    tenantId: string,
    payload: UpdateTenantHardQuotaPayload
  ): Promise<any> {
    const response = await fetch(
      API_ENDPOINTS.quota.platformTenantQuota(tenantId),
      {
        method: "PUT",
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
      }
    );
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        response.status,
        data.message || "Failed to set tenant hard quota"
      );
    }
    emitQuotaUsageChanged();
    return data;
  }

  async deleteTenantHardQuota(tenantId: string): Promise<void> {
    const response = await fetch(
      API_ENDPOINTS.quota.platformTenantQuota(tenantId),
      {
        method: "DELETE",
        headers: getAuthHeaders(),
      }
    );
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        data.message || "Failed to delete tenant hard quota"
      );
    }
    emitQuotaUsageChanged();
  }
}

const quotaService = new QuotaService();
export default quotaService;
