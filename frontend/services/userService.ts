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
 */
export async function listUsers(
  tenantId: string | null,
  page: number = 1,
  pageSize: number = 20
): Promise<{ users: User[]; total: number; totalPages: number }> {
  if (!tenantId) return { users: [], total: 0, totalPages: 0 };

  try {
    const response = await fetchWithAuth(API_ENDPOINTS.users.list, {
      method: "POST",
      body: JSON.stringify({
        tenant_id: tenantId,
        page,
        page_size: pageSize,
      }),
    });

    const result: UserListResponse = await response.json();
    return {
      users: result.data,
      total: result.pagination?.total || 0,
      totalPages: result.pagination?.total_pages || 0,
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
