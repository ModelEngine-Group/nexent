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
  PersonalCapacityUsersResponse,
  PersonalDefaultQuota,
  PersonalKbDetailResponse,
  PersonalQuotaPayload,
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
        data.error || response.status,
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
        data.error || response.status,
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
        data.error || response.status,
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
        data.error || response.status,
        data.message || "Failed to get quota usage"
      );
    }
    return data;
  }

  // ── Platform-Level Quota (SU/ASSET_OWNER/SPEED) ────────────────

  async getPlatformOverview(): Promise<PlatformQuotaOverview> {
    const response = await fetch(API_ENDPOINTS.quota.platformOverview, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        data.error || response.status,
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
        data.error || response.status,
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
        data.error || response.status,
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
        data.error || response.status,
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
        data.error || response.status,
        data.message || "Failed to delete tenant hard quota"
      );
    }
    emitQuotaUsageChanged();
  }

  // ── Personal KB Capacity (ADMIN/SU) ────────────────────────────────

  private buildPersonalCapacityUrl(
    base: string,
    params: Record<string, string | number | null | undefined>
  ): string {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        query.set(key, String(value));
      }
    }
    const queryString = query.toString();
    return queryString ? `${base}?${queryString}` : base;
  }

  async listPersonalCapacityUsers(params: {
    tenantId?: string | null;
    page?: number;
    page_size?: number;
    sort_by?: string;
    sort_order?: string;
  }): Promise<PersonalCapacityUsersResponse> {
    const url = this.buildPersonalCapacityUrl(
      API_ENDPOINTS.quota.personalUsers,
      {
        tenant_id: params.tenantId,
        page: params.page,
        page_size: params.page_size,
        sort_by: params.sort_by,
        sort_order: params.sort_order,
      }
    );
    const response = await fetch(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        data.error || response.status,
        data.message || data.detail || "Failed to list personal KB capacity"
      );
    }
    return data;
  }

  async getPersonalKbDetails(
    userId: string,
    tenantId?: string | null,
    page?: number,
    page_size?: number
  ): Promise<PersonalKbDetailResponse> {
    const url = this.buildPersonalCapacityUrl(
      API_ENDPOINTS.quota.personalUserKbs(userId),
      {
        tenant_id: tenantId,
        page,
        page_size,
      }
    );
    const response = await fetch(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        data.error || response.status,
        data.message || data.detail || "Failed to get personal KB details"
      );
    }
    return data;
  }

  async setPersonalUserQuota(
    userId: string,
    tenantId: string | null,
    payload: PersonalQuotaPayload
  ): Promise<any> {
    const url = this.buildPersonalCapacityUrl(
      API_ENDPOINTS.quota.personalUserQuota(userId),
      { tenant_id: tenantId }
    );
    const response = await fetch(url, {
      method: "PUT",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        data.error || response.status,
        data.message || data.detail || "Failed to set personal KB quota"
      );
    }
    return data;
  }

  async getPersonalDefaultQuota(
    tenantId?: string | null
  ): Promise<PersonalDefaultQuota> {
    const url = this.buildPersonalCapacityUrl(
      API_ENDPOINTS.quota.personalDefaultQuota,
      { tenant_id: tenantId }
    );
    const response = await fetch(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        data.error || response.status,
        data.message || data.detail || "Failed to get personal KB default quota"
      );
    }
    return data;
  }

  async setPersonalDefaultQuota(
    tenantId: string | null,
    payload: PersonalQuotaPayload
  ): Promise<any> {
    const url = this.buildPersonalCapacityUrl(
      API_ENDPOINTS.quota.personalDefaultQuota,
      { tenant_id: tenantId }
    );
    const response = await fetch(url, {
      method: "PUT",
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new ApiError(
        data.error || response.status,
        data.message || data.detail || "Failed to set personal KB default quota"
      );
    }
    return data;
  }
}

const quotaService = new QuotaService();
export default quotaService;
