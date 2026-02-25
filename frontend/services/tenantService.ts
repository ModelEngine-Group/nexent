import { API_ENDPOINTS, ApiError } from "./api";
import { fetchWithAuth } from "@/lib/auth";

// Types
export interface Tenant {
  tenant_id: string;
  tenant_name: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
  user_count?: number;
  group_count?: number;
}

export interface CreateTenantRequest {
  tenant_name: string;
}

export interface UpdateTenantRequest {
  tenant_name: string;
}

export interface TenantListResponse {
  data: Tenant[];
  message: string;
}

export interface TenantListPaginatedResponse {
  data: Tenant[];
  message: string;
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface TenantDetailResponse {
  data: Tenant;
  message: string;
}

export interface CreateTenantResponse {
  data: Tenant;
  message: string;
}

export interface ListTenantsParams {
  page?: number;
  page_size?: number;
}

/**
 * List tenants with pagination support (filtered by user permissions)
 */
export async function listTenants(params?: ListTenantsParams): Promise<TenantListPaginatedResponse> {
  try {
    const url = API_ENDPOINTS.tenant.list;

    const response = await fetchWithAuth(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        page: params?.page ?? 1,
        page_size: params?.page_size ?? 20,
      }),
    });

    const result: TenantListPaginatedResponse = await response.json();
    return result;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch tenants");
  }
}

/**
 * Get tenant details by tenant ID
 */
export async function getTenant(tenantId: string): Promise<Tenant> {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.tenant.detail(tenantId),
      {
        method: "GET",
      }
    );

    const result: TenantDetailResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch tenant details");
  }
}

/**
 * Create a new tenant
 */
export async function createTenant(
  payload: CreateTenantRequest
): Promise<Tenant> {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.tenant.create, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    const result: CreateTenantResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to create tenant");
  }
}

/**
 * Update tenant information
 */
export async function updateTenant(
  tenantId: string,
  payload: UpdateTenantRequest
): Promise<Tenant> {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.tenant.update(tenantId),
      {
        method: "PUT",
        body: JSON.stringify(payload),
      }
    );

    const result: TenantDetailResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to update tenant");
  }
}

/**
 * Delete a tenant
 */
export async function deleteTenant(tenantId: string): Promise<void> {
  try {
    await fetchWithAuth(API_ENDPOINTS.tenant.delete(tenantId), {
      method: "DELETE",
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to delete tenant");
  }
}
