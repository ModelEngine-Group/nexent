import { API_ENDPOINTS, ApiError } from "./api";
import { fetchWithAuth } from "@/lib/auth";
import type { User } from "./userService";

// Types
export interface Group {
  group_id: number;
  group_name: string;
  group_description?: string;
  tenant_id?: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
  user_count?: number;
}

export interface CreateGroupRequest {
  group_name: string;
  group_description?: string;
}

export interface UpdateGroupRequest {
  group_name?: string;
  group_description?: string;
}

export interface GroupListResponse {
  data: Group[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  message: string;
}

export interface GroupDetailResponse {
  data: Group;
  message: string;
}

export interface GroupMembersResponse {
  data: User[];
}

export interface CreateGroupResponse {
  data: Group;
  message: string;
}

/**
 * List groups for a specific tenant with pagination
 */
export async function listGroups(
  tenantId: string,
  page: number = 1,
  pageSize: number = 20
): Promise<{ groups: Group[]; total: number; totalPages: number }> {
  try {
    // Use backend's /groups/list endpoint with tenant_id in request body
    const response = await fetchWithAuth(API_ENDPOINTS.groups.list, {
      method: "POST",
      body: JSON.stringify({
        tenant_id: tenantId,
        page,
        page_size: pageSize,
        sort_by: "created_at",
        sort_order: "desc",
      }),
    });

    const result: GroupListResponse = await response.json();
    return {
      groups: result.data,
      total: result.pagination.total,
      totalPages: result.pagination.total_pages,
    };
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch groups");
  }
}

/**
 * Get group details by group ID
 */
export async function getGroup(groupId: number): Promise<Group> {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.groups.detail(groupId),
      {
        method: "GET",
      }
    );

    const result: GroupDetailResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch group details");
  }
}

/**
 * Get group members
 */
export async function getGroupMembers(groupId: number): Promise<User[]> {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.groups.members(groupId),
      {
        method: "GET",
      }
    );

    const result: GroupMembersResponse = await response.json();
    return result.data || [];
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch group members");
  }
}

/**
 * Create a new group in a tenant
 */
export async function createGroup(
  tenantId: string,
  payload: CreateGroupRequest
): Promise<Group> {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.groups.create, {
      method: "POST",
      body: JSON.stringify({
        tenant_id: tenantId,
        ...payload,
      }),
    });

    const result: CreateGroupResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to create group");
  }
}

/**
 * Update group information
 */
export async function updateGroup(
  groupId: number,
  payload: UpdateGroupRequest
): Promise<void> {
  try {
    await fetchWithAuth(API_ENDPOINTS.groups.update(groupId), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to update group");
  }
}

/**
 * Delete a group
 */
export async function deleteGroup(groupId: number): Promise<void> {
  try {
    await fetchWithAuth(API_ENDPOINTS.groups.delete(groupId), {
      method: "DELETE",
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to delete group");
  }
}

/**
 * Add user to group
 */
export async function addUserToGroup(
  groupId: number,
  userId: string
): Promise<void> {
  try {
    await fetchWithAuth(API_ENDPOINTS.groups.addMember(groupId), {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to add user to group");
  }
}

/**
 * Remove user from group
 */
export async function removeUserFromGroup(
  groupId: number,
  userId: string
): Promise<void> {
  try {
    await fetchWithAuth(
      API_ENDPOINTS.groups.removeMember(groupId, userId),
      {
        method: "DELETE",
      }
    );
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to remove user from group");
  }
}

/**
 * Update group members by setting the exact list of users
 */
export async function updateGroupMembers(
  groupId: number,
  userIds: string[]
): Promise<{ added_count: number; removed_count: number; total_members: number }> {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.groups.members(groupId),
      {
        method: "PUT",
        body: JSON.stringify({ user_ids: userIds }),
      }
    );

    const result = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to update group members");
  }
}

/**
 * Get tenant's default group ID
 */
export async function getTenantDefaultGroupId(tenantId: string): Promise<number | null> {
  try {
    const response = await fetchWithAuth(
      API_ENDPOINTS.groups.default(tenantId),
      {
        method: "GET",
      }
    );

    const result = await response.json();
    return result.data?.default_group_id || null;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to get tenant default group");
  }
}