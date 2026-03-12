import { API_ENDPOINTS, ApiError } from "./api";
import { fetchWithAuth } from "@/lib/auth";

// Types
export interface User {
  id: string;
  username: string;
  role: string;
  email?: string;
  tenant_id?: string;
  created_at?: string;
  updated_at?: string;
}

export interface UpdateUserRequest {
  role: string;
}

export interface UserListResponse {
  data: User[];
  total?: number; // Root-level total for non-paginated responses
  pagination?: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  message: string;
}

export interface UserDetailResponse {
  data: User;
  message: string;
}

export interface CreateUserResponse {
  data: User;
  message: string;
}

/**
 * List users for a specific tenant
 * If page and pageSize are not provided, returns all users
 */
export async function listUsers(
  tenantId: string | null,
  page?: number,
  pageSize?: number
): Promise<{ users: User[]; total: number; totalPages?: number }> {
  if (!tenantId) return { users: [], total: 0 };

  try {
    const requestBody: any = {
      tenant_id: tenantId,
      sort_by: "created_at",
      sort_order: "desc",
    };

    // Only include pagination parameters if both are provided
    if (page !== undefined && pageSize !== undefined) {
      requestBody.page = page;
      requestBody.page_size = pageSize;
    }

    const response = await fetchWithAuth(API_ENDPOINTS.users.list, {
      method: "POST",
      body: JSON.stringify(requestBody),
    });

    const result: UserListResponse = await response.json();
    return {
      users: result.data,
      // Support both paginated (pagination.total) and non-paginated (root total) responses
      total: result.pagination?.total ?? result.total ?? 0,
      totalPages: result.pagination?.total_pages,
    };
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch users");
  }
}

/**
 * Get user details by user ID
 */
export async function getUser(userId: string): Promise<User> {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.users.detail(userId), {
      method: "GET",
    });

    const result: UserDetailResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch user details");
  }
}

/**
 * Update user information
 */
export async function updateUser(
  userId: string,
  payload: UpdateUserRequest
): Promise<User> {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.users.update(userId), {
      method: "PUT",
      body: JSON.stringify(payload),
    });

    const result: UserDetailResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to update user");
  }
}

/**
 * Delete a user (soft delete)
 */
export async function deleteUser(userId: string): Promise<void> {
  try {
    await fetchWithAuth(API_ENDPOINTS.users.delete(userId), {
      method: "DELETE",
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to delete user");
  }
}
