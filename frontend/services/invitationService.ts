import { API_ENDPOINTS, ApiError } from "./api";
import { fetchWithAuth } from "@/lib/auth";

// Types
export interface Invitation {
  invitation_id: number;
  invitation_code: string;
  code_type: string;
  group_ids?: number[];
  capacity: number;
  used_times: number; // Backend includes this in list response
  expiry_date?: string;
  status: string;
  tenant_id?: string;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
}

export interface InvitationListRequest {
  tenant_id?: string;
  page?: number;
  page_size?: number;
}

export interface InvitationListResponse {
  data: {
    items: Invitation[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
  };
  message: string;
}

export interface CreateInvitationRequest {
  tenant_id: string;
  code_type: string;
  invitation_code?: string;
  group_ids?: number[];
  capacity: number;
  expiry_date?: string;
}

export interface UpdateInvitationRequest {
  capacity?: number;
  expiry_date?: string;
  group_ids?: number[];
}

export interface CreateInvitationResponse {
  data: Invitation;
  message: string;
}

export interface InvitationDetailResponse {
  data: Invitation;
  message: string;
}

/**
 * List invitations with pagination
 */
export async function listInvitations(
  request: InvitationListRequest
): Promise<{
  items: Invitation[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}> {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.invitations.list, {
      method: "POST",
      body: JSON.stringify({
        tenant_id: request.tenant_id,
        page: request.page || 1,
        page_size: request.page_size || 20,
      }),
    });

    const result: InvitationListResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch invitations");
  }
}

/**
 * Create a new invitation
 */
export async function createInvitation(
  payload: CreateInvitationRequest
): Promise<Invitation> {
  try {
    const response = await fetchWithAuth(API_ENDPOINTS.invitations.create, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    const result: CreateInvitationResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to create invitation");
  }
}

/**
 * Update an invitation
 */
export async function updateInvitation(
  invitationCode: string,
  payload: UpdateInvitationRequest
): Promise<void> {
  try {
    await fetchWithAuth(API_ENDPOINTS.invitations.update(invitationCode), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to update invitation");
  }
}

/**
 * Delete an invitation
 */
export async function deleteInvitation(invitationCode: string): Promise<void> {
  try {
    await fetchWithAuth(API_ENDPOINTS.invitations.delete(invitationCode), {
      method: "DELETE",
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to delete invitation");
  }
}
